"""Exercise the archive through Dify's serverless HTTP protocol, offline."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

import requests

package = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='dify-runtime-') as directory:
    with zipfile.ZipFile(package) as archive:
        for name in archive.namelist():
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('Unsafe archive path')
        archive.extractall(directory)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'INSTALL_METHOD': 'serverless', 'SERVERLESS_HOST': '127.0.0.1',
           'SERVERLESS_PORT': str(port), 'PYTHONUNBUFFERED': '1'}
    with tempfile.TemporaryFile(mode='w+') as log:
        server = subprocess.Popen([sys.executable, str(Path(__file__).with_name('runtime_server.py'))],
                                  cwd=directory, env=env, stdout=log, stderr=log)
        http = requests.Session()
        http.trust_env = False
        url = f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                if server.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                try:
                    if http.get(url+'/health', timeout=0.3).status_code == 200:
                        break
                except requests.RequestException:
                    time.sleep(0.1)
            else:
                raise RuntimeError('Runtime did not become healthy')
            credentials = {'api_key': 'dummy-key', 'sender': 'sender@example.com',
                           'allowed_recipients': 'recipient@example.net', 'mode': 'dry_run'}
            parameters = {'to': 'recipient@example.net', 'subject': 'Runtime test', 'text': 'Synthetic'}
            def invoke(action='invoke_tool', creds=None, params=None):
                data = {'type': 'tool', 'action': action, 'user_id': 'runtime-user',
                        'provider': 'mailchannels', 'tool': 'send_email',
                        'credentials': credentials if creds is None else creds,
                        'tool_parameters': parameters if params is None else params}
                response = http.post(url+'/invoke', json={'event': 'request',
                                     'session_id': str(uuid.uuid4()), 'data': data}, timeout=10)
                response.raise_for_status()
                events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
                assert events[-1]['data']['type'] == 'end'
                streams = [event['data']['data'] for event in events if event['data']['type'] == 'stream']
                errors = [event['data'] for event in events if event['data']['type'] == 'error']
                return {'streams': streams, 'errors': errors}
            def status(output):
                assert not output['errors']
                assert len(output['streams']) == 1
                return output['streams'][0]['message']['json_object']['status']
            output = invoke()
            assert status(output) == 'validated'
            assert 'synthetic MIME' not in json.dumps(output) and 'dummy-key' not in json.dumps(output)
            output = invoke(creds={**credentials, 'mode': 'send'})
            assert status(output) == 'accepted'
            assert output['streams'][0]['message']['json_object']['request_id'] == 'runtime-request'
            assert status(invoke(params={**parameters, 'to':'other@example.net'})) == 'rejected'
            assert status(invoke(params={**parameters, 'mode':'send'})) == 'rejected'
            output = invoke(params={**parameters, 'subject':'simulate timeout'})
            assert status(output) == 'unknown' and 'dummy-key' not in json.dumps(output)
            output = invoke('validate_tool_credentials', creds={**credentials, 'mode':'send'})
            assert output == {'streams': [{'result': True}], 'errors': []}
            output = invoke('validate_tool_credentials', creds={**credentials, 'api_key':'invalid-test-key'})
            assert output['errors'] and 'validation failed' in json.dumps(output).lower()
            assert 'invalid-test-key' not in json.dumps(output)
            print('Packaged serverless runtime: 7 invocation/credential scenarios passed')
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            http.close()
