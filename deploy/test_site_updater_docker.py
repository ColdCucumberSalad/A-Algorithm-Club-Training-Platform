"""Local, disposable Docker tests; never uses a deployment's data or config.

Run: RUN_SITE_UPDATE_DOCKER_TESTS=1 python -m unittest discover -s deploy -p test_site_updater_docker.py -v
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
import uuid

from site_updater import Updater


@unittest.skipUnless(os.environ.get('RUN_SITE_UPDATE_DOCKER_TESTS') == '1', 'explicit local Docker test opt-in required')
class LocalDockerReleaseTests(unittest.TestCase):
    def test_dockerfile_runtime_and_nginx_forward_and_rollback(self):
        output = Path(__file__).resolve().parent.parent / 'output'
        output.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='site-updater-review-', dir=output)
        root = Path(temporary.name).resolve()
        self.assertTrue(root.is_relative_to(output.resolve()))
        self.addCleanup(temporary.cleanup)
        project = 'site-updater-review-' + uuid.uuid4().hex[:8]
        old_image, new_image = project + ':old', project + ':new'
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        health = 'http://127.0.0.1:' + str(port) + '/auth.html'
        updater = Updater({'project': str(root), 'control': str(root / 'control'), 'compose_project': project, 'health_url': health})
        def cleanup():
            subprocess.run(updater.compose + ['down', '--remove-orphans'], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        self.addCleanup(cleanup)
        source = root / 'source'; source.mkdir()
        (source / 'requirements.txt').write_text('# unchanged\n')
        (source / 'manage.py').write_text('pass\n')
        (source / 'server.py').write_text('''from http.server import BaseHTTPRequestHandler, HTTPServer
import os,sys
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write((os.environ['REVIEW_RUNTIME']+' '+sys.argv[1]).encode())
HTTPServer(('0.0.0.0',8000),Handler).serve_forever()
''')
        def build(marker, image):
            (source / 'Dockerfile').write_text('FROM python:3.12-slim\nWORKDIR /app\nCOPY . /app/\nENV REVIEW_RUNTIME=' + marker + '\nCMD ["python","/app/server.py","' + marker + '-startup"]\n')
            updater.build_release(source, image, 'a' * 40)
        before = hashlib.sha256((source / 'requirements.txt').read_bytes()).hexdigest()
        build('old', old_image)
        build('new', new_image)
        self.assertEqual(before, hashlib.sha256((source / 'requirements.txt').read_bytes()).hexdigest())
        info = json.loads(updater.run(['docker', 'image', 'inspect', new_image]))[0]['Config']
        self.assertIn('REVIEW_RUNTIME=new', info['Env'])
        self.assertEqual(info['Cmd'], ['python', '/app/server.py', 'new-startup'])
        proxy = root / 'nginx.conf'
        proxy.write_text('server { listen 80; location / { proxy_connect_timeout 1s; proxy_read_timeout 2s; proxy_pass http://web:8000; } }\n')
        def compose(image, address):
            value = {'services': {
                'web': {'image': image, 'networks': {'default': {'ipv4_address': address}},
                        'healthcheck': {'test': ['CMD', 'python', '-c', "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/auth.html')"], 'interval': '1s', 'timeout': '2s', 'retries': 20}},
                'nginx': {'image': 'nginx:1.27-alpine', 'ports': ['127.0.0.1:' + str(port) + ':80'],
                          'volumes': [proxy.as_posix() + ':/etc/nginx/conf.d/default.conf:ro'],
                          'depends_on': {'web': {'condition': 'service_healthy'}}}},
                'networks': {'default': {'ipam': {'config': [{'subnet': '172.30.77.0/24'}]}}}}
            (root / 'compose.yaml').write_text(json.dumps(value))
        (root / '.env').write_text('')
        compose(old_image, '172.30.77.10')
        updater.run(updater.compose + ['up', '-d', '--wait', '--wait-timeout', '90'], timeout=120)
        with urllib.request.urlopen(health, timeout=10) as response:
            self.assertEqual(response.read(), b'old old-startup')
        compose(new_image, '172.30.77.20')
        updater.run(updater.compose + ['up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '90', 'web'], timeout=120)
        # Reproduce the reported failure before exercising the repaired switch.
        with self.assertRaises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(health, timeout=10)
        self.assertIn(failure.exception.code, (502, 504))
        updater.start_web()
        with urllib.request.urlopen(health, timeout=10) as response:
            self.assertEqual(response.read(), b'new new-startup')
        compose(old_image, '172.30.77.10')
        updater.start_web()
        with urllib.request.urlopen(health, timeout=10) as response:
            self.assertEqual(response.read(), b'old old-startup')
