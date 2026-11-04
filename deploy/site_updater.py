#!/usr/bin/env python3
"""Host-only release coordinator. Never mount the Docker socket into the website."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.request
import uuid
from zoneinfo import ZoneInfo

REPOSITORY = 'Monkey181x/A-Algorithm-Club-Training-Platform'
BRANCH = 'main'
DEFAULT_SCHEDULE = {'mode': 'auto', 'time': '04:00'}
BUSY = ('running', 'queued')


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    os.replace(temporary, path)


def validate_schedule(value):
    if not isinstance(value, dict) or set(value) != {'mode', 'time'} or value['mode'] not in ('auto', 'notify', 'off') or not isinstance(value['time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value['time']):
        raise ValueError('无效的检查设置')
    return value


def extract(archive, destination):
    """GitHub archives must contain regular source files, no links or traversal."""
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        if sum(item.size for item in members) > 200 * 1024 * 1024:
            raise ValueError('源码归档过大')
        for member in members:
            parts = Path(member.name).parts
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()) or '..' in parts or member.name.startswith('/'):
                raise ValueError('源码归档包含不安全路径')
            relative = Path(*parts[1:])
            if relative == Path('.'):
                continue
            if relative.parts[0] in ('.env', 'media', 'staticfiles', 'backups', 'data', '.git'):
                raise ValueError('源码不得覆盖运行数据或配置')
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(member) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)


class Updater:
    def __init__(self, config):
        self.config = config
        self.project = Path(config['project']).resolve()
        self.control = Path(config['control']).resolve()
        self.control.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.compose = ['docker', 'compose', '-p', config['compose_project'], '--env-file', str(self.project / '.env'), '-f', str(self.project / 'compose.yaml')]
        self.state = read(self.control / 'status.json', {}) or {}
        self.log = None
        self.stop_event = threading.Event()

    def run(self, args, timeout=180, **kwargs):
        result = subprocess.run(args, cwd=self.project, timeout=timeout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        if self.log:
            self.log.write(result.stdout + result.stderr); self.log.flush()
        if result.returncode:
            raise RuntimeError('服务器操作失败，请查看更新日志')
        return result.stdout.decode().strip()

    def status(self, **values):
        self.state.update(values, updated_at=dt.datetime.now(dt.timezone.utc).isoformat())
        write(self.control / 'status.json', self.state)

    def heartbeat(self):
        while not self.stop_event.is_set():
            write(self.control / 'heartbeat.json', {'time': time.time()})
            self.stop_event.wait(5)

    def image(self):
        container = self.run(self.compose + ['ps', '-aq', 'web'])
        return self.run(['docker', 'inspect', container, '--format', '{{.Config.Image}}'])

    def revision(self):
        image = self.image()
        return self.run(['docker', 'image', 'inspect', image, '--format', '{{index .Config.Labels "org.opencontainers.image.revision"}}'])

    def check(self):
        routes, revisions = [], []
        for kind, name in [('git', 'GitHub Git 直连'), ('api', 'GitHub API 直连')]:
            started = time.monotonic()
            try:
                if kind == 'git':
                    text = self.run(['git', '-c', 'http.followRedirects=true', 'ls-remote', 'https://github.com/' + REPOSITORY + '.git', 'refs/heads/' + BRANCH], timeout=35)
                    revision = text.split()[0]
                else:
                    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/commits/' + BRANCH, headers={'User-Agent': 'club-site-updater', 'Accept': 'application/vnd.github+json'})
                    with urllib.request.urlopen(request, timeout=25) as response:
                        revision = json.load(response)['sha']
                if not re.fullmatch('[0-9a-f]{40}', revision):
                    raise ValueError('无效版本')
                revisions.append(revision)
                routes.append({'name': name, 'ok': True, 'seconds': round(time.monotonic() - started, 2)})
            except Exception:
                routes.append({'name': name, 'ok': False})
        if not revisions:
            self.status(routes=routes)
            raise RuntimeError('GitHub 直连暂不可用，已保留当前网站版本')
        if len(set(revisions)) != 1:
            raise RuntimeError('仓库版本在检查期间发生变化，请稍后重试')
        current, latest = self.revision(), revisions[0]
        self.status(current=current, latest=latest, routes=routes, checked_at=dt.datetime.now(dt.timezone.utc).isoformat(), message='发现新版本 ' + latest[:7] if current != latest else '已是最新版本')
        return latest

    def dump(self, target):
        with target.open('wb') as output:
            result = subprocess.run(self.compose + ['exec', '-T', 'db', 'sh', '-c', 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], stdout=output, stderr=subprocess.PIPE, timeout=300)
        if result.returncode or target.stat().st_size < 100:
            raise RuntimeError('数据库备份失败，更新已中止')
        with target.open('rb') as data:
            self.run(self.compose + ['exec', '-T', 'db', 'pg_restore', '--list'], stdin=data)

    def guard(self, image):
        # The shared application lock also excludes backup/restore and rejects
        # API writes while the new Web is publicly reachable during validation.
        code = "import os,sys,psycopg; c=psycopg.connect(dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'],host=os.environ.get('POSTGRES_HOST','db')); q=c.cursor(); q.execute('SELECT pg_try_advisory_lock(739184206)'); ok=q.fetchone()[0]; print('LOCKED' if ok else 'BUSY',flush=True); sys.stdin.read() if ok else sys.exit(2)"
        process = subprocess.Popen(['docker', 'run', '--rm', '-i', '--network', self.config['network'], '--env-file', str(self.project / '.env'), image, 'python', '-u', '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        import selectors
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            if not selector.select(20) or process.stdout.readline().strip() != b'LOCKED':
                process.stdin.close(); process.wait(timeout=20)
                raise RuntimeError('系统正在备份或处理业务，请稍后重试更新')
        finally:
            selector.close()
        return process

    def audit(self, image, backup, mode, host=None):
        args = ['docker', 'run', '--rm', '--network', host or self.config['network'], '--env-file', str(self.project / '.env'), '-v', str(Path(__file__).with_name('site_update_audit.py')) + ':/audit.py:ro', '-v', str(backup) + ':/audit']
        if host:
            args += ['-e', 'POSTGRES_HOST=' + host, '-e', 'POSTGRES_DB=club_check', '-e', 'POSTGRES_USER=postgres', '-e', 'POSTGRES_PASSWORD=isolated-check-only']
        return self.run(args + [image, 'python', '/audit.py', mode], timeout=300)

    def rehearsal(self, image, directory):
        self.status(message='正在数据库副本上演练迁移')
        directory.mkdir()
        self.dump(directory / 'database.dump')
        name = 'club-update-check-' + uuid.uuid4().hex[:12]
        self.run(['docker', 'network', 'create', name])
        try:
            self.run(['docker', 'run', '-d', '--name', name, '--network', name, '-e', 'POSTGRES_DB=club_check', '-e', 'POSTGRES_PASSWORD=isolated-check-only', 'postgres:16-alpine'])
            for attempt in range(45):
                try:
                    self.run(['docker', 'exec', name, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres'], timeout=5)
                    break
                except RuntimeError:
                    time.sleep(1)
            else:
                raise RuntimeError('迁移演练数据库未就绪')
            with (directory / 'database.dump').open('rb') as data:
                self.run(['docker', 'exec', '-i', name, 'pg_restore', '--no-owner', '--no-acl', '-U', 'postgres', '-d', 'club_check'], stdin=data, timeout=300)
            self.audit(image, directory, 'capture', name)
            args = ['docker', 'run', '--rm', '--network', name, '--env-file', str(self.project / '.env'), '-e', 'POSTGRES_HOST=' + name, '-e', 'POSTGRES_DB=club_check', '-e', 'POSTGRES_USER=postgres', '-e', 'POSTGRES_PASSWORD=isolated-check-only', image, 'python', 'manage.py']
            self.run(args + ['migrate', '--noinput'], timeout=600)
            self.run(args + ['check'], timeout=120)
            self.audit(image, directory, 'verify', name)
        finally:
            self.run(['docker', 'rm', '-f', '-v', name])
            self.run(['docker', 'network', 'rm', name])

    def update(self, revision):
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision) or self.check() != revision:
            raise ValueError('主分支已变化，请重新检查后更新')
        if self.state.get('current') == revision:
            return
        release = self.project / 'releases' / ('managed-' + revision[:12] + '-' + uuid.uuid4().hex[:8])
        release.mkdir(parents=True)
        self.log = (release / 'update.log').open('ab')
        old_image = self.image()
        old_compose = (self.project / 'compose.yaml').read_bytes()
        backup = self.project / 'deploy-backups' / release.name
        stopped = migrated = False
        guard = None
        try:
            mounts=json.loads(self.run(['docker','inspect',self.run(self.compose+['ps','-aq','web']),'--format','{{json .Mounts}}']))
            for name in ('media','static'):
                destination='/app/'+('staticfiles' if name=='static' else name)
                if not any(m['Destination']==destination and Path(m['Source']).resolve()==self.project/'data'/name for m in mounts):
                    raise RuntimeError('数据挂载与更新配置不一致，已保留原版本')
            if shutil.disk_usage(self.project).free < 2 * 1024 ** 3:
                raise RuntimeError('磁盘剩余空间不足，暂不更新')
            self.status(message='正在下载并校验最新源码')
            urls = ['https://codeload.github.com/' + REPOSITORY + '/tar.gz/' + revision,
                    'https://api.github.com/repos/' + REPOSITORY + '/tarball/' + revision]
            archive = release / 'source.tar.gz'
            for url in urls:
                started = time.monotonic()
                try:
                    request = urllib.request.Request(url, headers={'User-Agent': 'club-site-updater'})
                    with urllib.request.urlopen(request, timeout=60) as source, archive.open('wb') as target:
                        size = 0
                        while chunk := source.read(1024 * 1024):
                            size += len(chunk)
                            if size > 100 * 1024 * 1024:
                                raise ValueError('下载文件过大')
                            target.write(chunk)
                    extract(archive, release / 'source')
                    self.state.setdefault('routes', []).append({'name': 'GitHub 源码归档', 'ok': True, 'seconds': round(time.monotonic() - started, 2)})
                    break
                except Exception:
                    if (release / 'source').exists():
                        shutil.rmtree(release / 'source')
            else:
                raise RuntimeError('官方源码下载线路不可用，已保留当前版本')
            source = release / 'source'
            old_requirements = self.run(['docker', 'run', '--rm', '--network', 'none', old_image, 'sha256sum', '/app/requirements.txt']).split()[0]
            image = 'club-platform:managed-' + revision[:12]
            if hashlib.sha256((source / 'requirements.txt').read_bytes()).hexdigest() == old_requirements:
                # Clean the old source layer so deleted files cannot survive a release.
                dockerfile = 'FROM ' + old_image + '\nWORKDIR /app\nRUN find /app -mindepth 1 -maxdepth 1 -exec rm -rf {} +\nCOPY source/ /app/\n'
                (release / 'Dockerfile').write_text(dockerfile + 'LABEL org.opencontainers.image.revision=' + revision + '\n')
                build = ['docker', 'build', '--network', 'none', '-t', image, str(release)]
            else:
                build = ['docker', 'build', '--label', 'org.opencontainers.image.revision=' + revision, '-t', image, str(source)]
            self.status(message='正在构建新版本，网站仍可使用')
            self.run(build, timeout=1200)
            self.run(['docker', 'run', '--rm', '--network', 'none', image, 'python', 'manage.py', 'check'])
            self.rehearsal(image, release / 'rehearsal')
            if shutil.disk_usage(self.project).free < 2 * 1024 ** 3:
                raise RuntimeError('磁盘剩余空间不足，暂不更新')
            backup.mkdir(parents=True, mode=0o700)
            shutil.copy2(self.project / '.env', backup / '.env')
            (backup / 'compose.yaml').write_bytes(old_compose)
            self.status(message='正在暂停写入并备份全部数据', backup=str(backup))
            guard = self.guard(old_image)
            stopped = True
            self.run(self.compose + ['stop', 'beat', 'worker', 'web'], timeout=180)
            self.dump(backup / 'database.dump')
            for kind in ('media', 'static'):
                with tarfile.open(backup / (kind + '.tar.gz'), 'w:gz') as output:
                    output.add(self.project / 'data' / kind, arcname=kind)
            self.audit(old_image, backup, 'capture')
            compose = old_compose.decode()
            if compose.count(old_image) != 3:
                raise RuntimeError('部署配置与预期不一致')
            (self.project / 'compose.yaml').write_text(compose.replace(old_image, image))
            migrated = True
            self.status(message='正在迁移并校验原有数据')
            self.run(self.compose + ['run', '--rm', '--no-deps', '-T', 'web', 'python', 'manage.py', 'migrate', '--noinput'], timeout=600)
            self.audit(image, backup, 'verify')
            self.run(self.compose + ['run', '--rm', '--no-deps', '-T', 'web', 'python', 'manage.py', 'collectstatic', '--clear', '--noinput'], timeout=300)
            self.run(self.compose + ['up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '180', 'web'], timeout=240)
            self.run(self.compose + ['exec', '-T', 'web', 'python', 'manage.py', 'migrate', '--check'])
            # Verify the public entry before starting any background writers.
            with urllib.request.urlopen(self.config['health_url'], timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError('公网检查失败')
            self.run(self.compose + ['up', '-d', '--no-deps', '--force-recreate', 'worker', 'beat'])
            self.status(current=revision, message='更新完成，数据校验通过', last_success=dt.datetime.now(dt.timezone.utc).isoformat())
        except Exception:
            if stopped:
                self.status(message='新版本未通过验证，正在恢复原版本')
                self.run(self.compose + ['stop', 'beat', 'worker', 'web'], timeout=180)
                (self.project / 'compose.yaml').write_bytes(old_compose)
                if migrated:
                    self.run(self.compose + ['exec', '-T', 'db', 'sh', '-c', 'dropdb --force -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'])
                    with (backup / 'database.dump').open('rb') as data:
                        self.run(self.compose + ['exec', '-T', 'db', 'sh', '-c', 'pg_restore --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], stdin=data, timeout=600)
                    for kind in ('media', 'static'):
                        target = (self.project / 'data' / kind).resolve()
                        if target != self.project / 'data' / kind or target.is_symlink():
                            raise RuntimeError('回退路径校验失败，请人工恢复备份')
                        shutil.rmtree(target)
                        with tarfile.open(backup / (kind + '.tar.gz')) as archive:
                            archive.extractall(self.project / 'data', filter='data')
                    self.audit(old_image, backup, 'verify')
                self.run(self.compose + ['up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '180', 'web'], timeout=240)
                self.run(self.compose + ['up', '-d', '--no-deps', '--force-recreate', 'worker', 'beat'])
            raise
        finally:
            if guard is not None:
                guard.stdin.close()
                guard.wait(timeout=30)
            self.log.close(); self.log = None

    def process(self, request):
        action, data = request.get('action'), request.get('data', {})
        if action not in ('check', 'update', 'schedule') or not isinstance(data, dict):
            raise ValueError('无效操作')
        self.status(state='running', operation=request.get('id'), message='正在处理请求')
        if action == 'schedule':
            write(self.control / 'schedule.json', validate_schedule(data))
            self.status(message='检查设置已保存')
        elif action == 'check':
            self.check()
        elif action == 'update' and set(data) == {'revision'}:
            self.update(data['revision'])
        else:
            raise ValueError('无效操作')
        self.status(state='succeeded')

    def serve(self):
        lock = (self.control / 'daemon.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        threading.Thread(target=self.heartbeat, daemon=True).start()
        if self.state.get('state') in BUSY:
            self.status(state='failed', message='更新服务曾中断，请核对网站状态和备份后重试')
        while True:
            try:
                requests = sorted(self.control.glob('request-*.json'))
                if requests:
                    path = requests[0]
                    request = read(path, {})
                    self.process(request)
                    path.unlink(missing_ok=True)
                else:
                    schedule = validate_schedule(read(self.control / 'schedule.json', DEFAULT_SCHEDULE))
                    now = dt.datetime.now(ZoneInfo('Asia/Shanghai'))
                    date = now.date().isoformat()
                    last = read(self.control / 'last-scheduled.json', {})
                    if schedule['mode'] != 'off' and now.strftime('%H:%M') >= schedule['time'] and last.get('date') != date:
                        write(self.control / 'last-scheduled.json', {'date': date})
                        self.status(state='running', message='正在定时检查更新')
                        latest = self.check()
                        if schedule['mode'] == 'auto' and latest != self.state.get('current'):
                            self.update(latest)
                        self.status(state='succeeded')
            except Exception as error:
                # No raw command output, credentials or remote content in the UI.
                self.status(state='failed', message=str(error) if isinstance(error, (RuntimeError, ValueError)) else '更新未完成，请查看服务器更新日志及备份')
                if 'path' in locals() and path.exists():
                    path.rename(path.with_suffix('.failed'))
            time.sleep(3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    Updater(read(Path(args.config))).serve()
