"""Narrow file queue for the host updater; the web process never accesses Docker."""
import json
import os
import time
import uuid
from pathlib import Path

DEFAULT_SCHEDULE = {'mode': 'auto', 'time': '04:00'}


def root():
    value = os.environ.get('SITE_UPDATE_DIR', '')
    if not value:
        return None
    return Path(value)


def read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def available(directory):
    return directory and directory.is_dir() and time.time() - read(directory / 'heartbeat.json', {}).get('time', 0) < 60


def summary():
    directory = root()
    if not directory:
        return {'available': False, 'message': '此部署尚未配置网站更新服务'}
    state = read(directory / 'status.json', {})
    state.update(available=bool(available(directory)), schedule=read(directory / 'schedule.json', DEFAULT_SCHEDULE))
    if not state['available']:
        state['message'] = '网站更新服务暂未连接，请检查服务器更新服务'
    return state


def enqueue(action, data, user_id):
    import fcntl
    directory = root()
    if not available(directory):
        raise ValueError('网站更新服务暂未连接')
    if action not in ('check', 'update', 'schedule'):
        raise ValueError('无效的更新操作')
    if action == 'schedule':
        import re
        if set(data) != {'mode', 'time'} or data['mode'] not in ('auto', 'notify', 'off') or not isinstance(data['time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', data['time']):
            raise ValueError('请选择检查方式和有效的北京时间')
    elif action == 'update':
        import re
        if set(data) != {'revision'} or not isinstance(data['revision'], str) or not re.fullmatch('[0-9a-f]{40}', data['revision']):
            raise ValueError('请先检查更新后选择最新版本')
    elif data:
        raise ValueError('无效的检查参数')
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'queue.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read(directory / 'status.json', {})
        if action == 'update' and state.get('recovery_required'):
            raise ValueError('上次更新需要人工恢复，暂不允许再次更新')
        if state.get('state') in ('queued', 'running') or any(directory.glob('request-*.json')):
            raise ValueError('已有更新操作进行中，请等待完成')
        identifier = str(uuid.uuid4())
        value = {'id': identifier, 'action': action, 'data': data, 'user_id': user_id, 'created_at': time.time()}
        temp = directory / (identifier + '.tmp')
        temp.write_text(json.dumps(value), encoding='utf-8')
        os.replace(temp, directory / ('request-' + identifier + '.json'))
    return identifier
