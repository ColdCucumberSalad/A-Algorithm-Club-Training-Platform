#!/usr/bin/env python3
"""One-time host installation for the existing /opt/club-platform deployment."""
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
from zoneinfo import ZoneInfo


def install():
    if os.geteuid() != 0:
        raise SystemExit('请由服务器维护人员以 root 安装')
    project = Path('/opt/club-platform')
    source = Path(__file__).resolve().parent
    target = project / 'site-updater'
    control = project / 'data/site-updater'
    compose = project / 'compose.yaml'
    text = compose.read_text()
    if not (project / '.env').is_file() or '  web:\n' not in text or '  worker:\n' not in text:
        raise SystemExit('当前部署结构不支持自动安装')
    for directory in (target, control):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    before = target / ('compose-before-' + dt.datetime.now().strftime('%Y%m%dT%H%M%S') + '.yaml')
    shutil.copy2(compose, before)
    web_start, web_end = text.index('  web:\n'), text.index('  worker:\n')
    web = text[web_start:web_end]
    if 'SITE_UPDATE_DIR:' not in web:
        if '    environment:\n' not in web or '    volumes:\n' not in web:
            raise SystemExit('Web 环境或数据挂载配置不符合预期')
        web = web.replace('    environment:\n', '    environment:\n      SITE_UPDATE_DIR: /app/site-updater\n', 1)
        web = web.replace('    volumes:\n', '    volumes:\n      - /opt/club-platform/data/site-updater:/app/site-updater\n', 1)
        compose.write_text(text[:web_start] + web + text[web_end:])
    for name in ('site_updater.py', 'site_update_audit.py'):
        if (source / name).resolve() != (target / name).resolve():
            shutil.copy2(source / name, target / name)
        (target / name).chmod(0o700)
    config = target / 'config.json'
    if not config.exists():
        config.write_text(json.dumps({'project': str(project), 'control': str(control), 'compose_project': 'club-platform',
                                     'network': 'club-platform_default', 'health_url': 'https://rbc.monkey3.top/auth.html'}))
        config.chmod(0o600)
    if not (control / 'schedule.json').exists():
        (control / 'schedule.json').write_text(json.dumps({'mode': 'auto', 'time': '04:00'}))
        (control / 'last-scheduled.json').write_text(json.dumps({'date': dt.datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()}))
    shutil.copy2(source / 'site-updater.service', '/etc/systemd/system/club-site-updater.service')
    subprocess.run(['docker', 'compose', '-p', 'club-platform', '--env-file', str(project / '.env'), '-f', str(compose), 'config', '--quiet'], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'club-site-updater.service'], check=True)
    print('更新服务已安装；Web 重新创建后管理工作台即可连接。默认次日北京时间 04:00 检查并自动更新。')


if __name__ == '__main__':
    install()
