#!/usr/bin/env python3
"""Host-only release coordinator. Never mount the Docker socket into the website."""
import argparse
import datetime as dt
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
import urllib.error
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


def file_digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


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
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def github_json(path):
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + path, headers={'User-Agent': 'club-site-updater', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def verify_source(source, revision):
    commit = github_json('/git/commits/' + revision)
    if commit.get('sha') != revision:
        raise ValueError('官方提交编号校验失败')
    tree = github_json('/git/trees/' + commit['tree']['sha'] + '?recursive=1')
    if tree.get('truncated') or any(item['type'] not in ('blob', 'tree') for item in tree['tree']):
        raise ValueError('源码树不完整或包含不支持的子模块')
    expected = {item['path']: item['sha'] for item in tree['tree'] if item['type'] == 'blob'}
    actual = {}
    for path in source.rglob('*'):
        if path.is_file():
            content = path.read_bytes()
            actual[path.relative_to(source).as_posix()] = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
    if expected != actual:
        raise ValueError('源码与 GitHub 官方提交的文件哈希不一致，更新已中止')


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

    def build_release(self, source, image, revision):
        # The release's Dockerfile owns its base, OS packages, ENV and CMD.
        # Docker's own layer cache can reuse unchanged inputs safely.
        self.run(['docker', 'build', '--pull', '--label', 'org.opencontainers.image.revision=' + revision,
                  '-f', str(source / 'Dockerfile'), '-t', image, str(source)], timeout=1200)

    def refresh_proxy(self):
        services = self.run(self.compose + ['config', '--services']).splitlines()
        if 'nginx' in services:
            # Static proxy_pass resolves Web at Nginx startup. Restart also
            # recovers a previously failed proxy after a container IP change.
            self.run(self.compose + ['restart', 'nginx'], timeout=120)

    def verify_public(self):
        for attempt in range(6):
            try:
                with urllib.request.urlopen(self.config['health_url'], timeout=5) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                pass
            if attempt < 5:
                time.sleep(1)
        raise RuntimeError('公网检查失败')

    def start_web(self):
        self.run(self.compose + ['up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '180', 'web'], timeout=240)
        self.refresh_proxy()
        self.run(self.compose + ['exec', '-T', 'web', 'python', 'manage.py', 'migrate', '--check'])
        self.verify_public()

    def pause_applications(self):
        try:
            self.run(self.compose + ['stop', 'beat', 'worker', 'web'], timeout=180)
        except Exception:
            self.run(self.compose + ['kill', 'beat', 'worker', 'web'], timeout=60)
        if self.run(self.compose + ['ps', '--status', 'running', '-q', 'web', 'worker', 'beat']):
            raise RuntimeError('应用停写确认失败，请人工停止服务，数据库锁仍保留')

    def quarantine_interrupted(self):
        requests = list(self.control.glob('request-*.json'))
        active = next((read(path, {}) for path in requests if read(path, {}).get('id') == self.state.get('operation')), {})
        interrupted = self.state.get('state') in BUSY or bool(active and self.state.get('state') != 'succeeded')
        action = active.get('action') or self.state.get('action')
        recovery = self.state.get('recovery_required', False) or (interrupted and action not in ('check', 'schedule'))
        for path in requests:
            request = read(path, {})
            if (interrupted and request.get('id') == self.state.get('operation')) or (recovery and request.get('action') == 'update'):
                path.rename(path.with_suffix('.interrupted'))
        if interrupted or recovery:
            self.status(state='failed', recovery_required=bool(recovery),
                        message='更新服务曾中断，请求已隔离，请人工核对版本、备份和全部应用服务后恢复' if recovery else '检查操作曾中断，原请求已隔离，可重新检查')

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
        if re.fullmatch('[0-9a-f]{40}', current or '') and current != latest:
            # Only fast-forward releases: never silently replace a hotfix or
            # roll a live feature branch back to an older main revision.
            request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/compare/' + current + '...' + latest, headers={'User-Agent': 'club-site-updater'})
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    comparison = json.load(response)
                if comparison.get('status') != 'ahead':
                    raise ValueError('线上版本不在最新主分支之前，请人工核对，自动更新已中止')
            except ValueError:
                raise
            except Exception:
                # Git provides an independent fallback for the ancestry check.
                cache = self.project / 'site-updater' / 'git-cache'
                if not cache.exists():
                    self.run(['git', 'init', '--bare', str(cache)])
                self.run(['git', '-C', str(cache), 'fetch', '--filter=blob:none', '--no-tags', 'https://github.com/' + REPOSITORY + '.git', current, latest], timeout=180)
                self.run(['git', '-C', str(cache), 'merge-base', '--is-ancestor', current, latest])
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
        name = 'club-update-guard-' + uuid.uuid4().hex[:12]
        process = subprocess.Popen(['docker', 'run', '--rm', '-i', '--name', name, '--network', self.config['network'], '--env-file', str(self.project / '.env'), image, 'python', '-u', '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        import selectors
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            if not selector.select(20) or process.stdout.readline().strip() != b'LOCKED':
                subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                process.stdin.close(); process.wait(timeout=20)
                raise RuntimeError('系统正在备份或处理业务，请稍后重试更新')
        finally:
            selector.close()
        return process, name

    def release_guard(self, guard):
        process, name = guard
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        process.stdin.close()
        process.wait(timeout=20)

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
        if self.state.get('recovery_required'):
            raise RuntimeError('上次更新需要人工恢复，暂不允许再次更新')
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
        release_guard = True
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
                    'https://api.github.com/repos/' + REPOSITORY + '/tarball/' + revision,
                    'https://gh-proxy.com/https://github.com/' + REPOSITORY + '/archive/' + revision + '.tar.gz',
                    'https://ghfast.top/https://github.com/' + REPOSITORY + '/archive/' + revision + '.tar.gz']
            archive = release / 'source.tar.gz'
            for url in urls:
                started = time.monotonic()
                try:
                    request = urllib.request.Request(url, headers={'User-Agent': 'club-site-updater'})
                    with urllib.request.urlopen(request, timeout=60) as source, archive.open('wb') as target:
                        size = 0
                        deadline = time.monotonic() + 120
                        while chunk := source.read1(1024 * 1024):
                            size += len(chunk)
                            if size > 100 * 1024 * 1024 or time.monotonic() > deadline:
                                raise ValueError('源码下载过大或超时')
                            target.write(chunk)
                    extract(archive, release / 'source')
                    verify_source(release / 'source', revision)
                    self.state.setdefault('routes', []).append({'name': url.split('/')[2], 'ok': True, 'seconds': round(time.monotonic() - started, 2)})
                    break
                except Exception:
                    if (release / 'source').exists():
                        shutil.rmtree(release / 'source')
            else:
                raise RuntimeError('官方源码下载线路不可用，已保留当前版本')
            source = release / 'source'
            image = 'club-platform:managed-' + revision[:12]
            self.status(message='正在构建新版本，网站仍可使用')
            self.build_release(source, image, revision)
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
            checksums = {name: file_digest(backup / name) for name in ('database.dump', 'media.tar.gz', 'static.tar.gz', '.env', 'compose.yaml')}
            write(backup / 'checksums.json', checksums)
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
            self.start_web()
            if (self.project / '.env').read_bytes() != (backup / '.env').read_bytes():
                raise RuntimeError('环境配置发生变化，更新已中止')
            self.run(self.compose + ['up', '-d', '--no-deps', '--force-recreate', 'worker', 'beat'])
            self.status(current=revision, message='更新完成，数据校验通过', last_success=dt.datetime.now(dt.timezone.utc).isoformat())
        except Exception:
            if stopped:
                try:
                    self.status(message='新版本未通过验证，正在恢复原版本')
                    self.run(self.compose + ['stop', 'beat', 'worker', 'web'], timeout=180)
                    (self.project / 'compose.yaml').write_bytes(old_compose)
                    if migrated:
                        for name, digest in checksums.items():
                            if file_digest(backup / name) != digest:
                                raise RuntimeError('备份校验失败，已保持停写，请人工恢复')
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
                        # dropdb --force terminated the original lock session.
                        # Acquire a new session before reopening the old Web.
                        previous_guard = guard
                        guard = self.guard(old_image)
                        if previous_guard is not None:
                            self.release_guard(previous_guard)
                    self.start_web()
                    self.run(self.compose + ['up', '-d', '--no-deps', '--force-recreate', 'worker', 'beat'])
                except Exception as rollback_error:
                    release_guard = False
                    try:
                        self.status(state='failed', recovery_required=True, message='回退验证失败，正在停止应用服务，请人工恢复')
                    finally:
                        self.pause_applications()
                    release_guard = True
                    raise RuntimeError('回退验证失败，应用服务已停止，请人工核对备份并恢复') from rollback_error
            raise
        finally:
            if guard is not None and not release_guard:
                self.retained_guard = guard
            if guard is not None and release_guard:
                self.release_guard(guard)
            self.log.close(); self.log = None

    def process(self, request):
        action, data = request.get('action'), request.get('data', {})
        if action not in ('check', 'update', 'schedule') or not isinstance(data, dict):
            raise ValueError('无效操作')
        self.status(state='running', operation=request.get('id'), action=action, message='正在处理请求')
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
        import fcntl
        with (self.control / 'daemon.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                threading.Thread(target=self.heartbeat, daemon=True).start()
                self.quarantine_interrupted()
                while True:
                    try:
                        requests = sorted(self.control.glob('request-*.json'))
                        if requests:
                            path = requests[0]
                            request = read(path, {})
                            self.process(request)
                            path.unlink(missing_ok=True)
                        else:
                            if self.state.get('recovery_required'):
                                time.sleep(3)
                                continue
                            schedule = validate_schedule(read(self.control / 'schedule.json', DEFAULT_SCHEDULE))
                            now = dt.datetime.now(ZoneInfo('Asia/Shanghai'))
                            date = now.date().isoformat()
                            last = read(self.control / 'last-scheduled.json', {})
                            if schedule['mode'] != 'off' and now.strftime('%H:%M') >= schedule['time'] and last.get('date') != date:
                                write(self.control / 'last-scheduled.json', {'date': date})
                                self.status(state='running', action='check', operation=None, message='正在定时检查更新')
                                latest = self.check()
                                if schedule['mode'] == 'auto' and latest != self.state.get('current'):
                                    self.status(action='update')
                                    self.update(latest)
                                self.status(state='succeeded')
                    except Exception as error:
                        # No raw command output, credentials or remote content in the UI.
                        self.status(state='failed', message=str(error) if isinstance(error, (RuntimeError, ValueError)) else '更新未完成，请查看服务器更新日志及备份')
                        if 'path' in locals() and path.exists():
                            path.rename(path.with_suffix('.failed'))
                    time.sleep(3)
            finally:
                self.stop_event.set()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    Updater(read(Path(args.config))).serve()
