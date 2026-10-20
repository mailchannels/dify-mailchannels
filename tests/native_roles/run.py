"""Opt-in native CE role acceptance. Never imported by default pytest."""
import argparse
import base64
import datetime
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import selectors
import shutil
import socket
import subprocess
import tempfile
import time
import traceback

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

PROJECT = 'visibility-dify-native-roles-01a122b4'
ARCHIVE_SHA = '276ba4fe72c81df1f3d68c79b6b79ffec7f4430c5df93cc2a255053373ab9f8d'
IMAGES = {
    'api': ('langgenius/dify-api@'
            'sha256:53fb08964da7a19d9b9f230a3b2945b6de55dc7b2ec570418e467defa809d82f'),
    'daemon': ('langgenius/dify-plugin-daemon@'
               'sha256:b9d28613f0b4593a6211049251a0d34c5edbb9c1001136a4b24c1e463fd7215c'),
    'postgres': 'postgres@sha256:21f6013073bc6b92830a2129570e2f5ec42a6c734b5a985a41e83aa58f54c3c1',
    'redis': 'redis@sha256:3811787313eba226a2ef38658c6ccb91cd5e110edc89c37767de373120a0e5a0',
    'mock': 'python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1',
}
PROVIDER = 'mailchannels/mailchannels/mailchannels'
PREFIX = '/workspaces/current/tool-provider/builtin/' + PROVIDER
ROLES = ['owner', 'admin', 'editor', 'normal', 'dataset_operator']
HERE = Path(__file__).resolve().parent


def sha(value):
    return hashlib.sha256(value).hexdigest()


def stable(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def guarded(containers):
    for item in containers:
        assert item['Config']['Labels'].get('com.docker.compose.project') == PROJECT
        assert item['Config']['Labels'].get('native_roles_fixture') == PROJECT
    return containers


def sse(text):
    return [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith('data:')]


class NativeSession(requests.Session):
    def __init__(self, fixture, role):
        super().__init__()
        self.trust_env = False
        self.fixture = fixture
        self.role = role

    def request(self, method, url, **kwargs):
        files = {name: [value[0], base64.b64encode(value[1].read()).decode(), value[2]]
                 for name, value in kwargs.get('files', {}).items()}
        item = {'role': self.role, 'method': method, 'url': url,
                'headers': dict(self.headers), 'files': files,
                **{key: value for key, value in kwargs.items()
                   if key in ['params', 'json', 'timeout']}}
        process = self.fixture.broker
        process.stdin.write(json.dumps(item) + '\n')
        process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(kwargs.get('timeout', 45) + 5):
                raise requests.Timeout('Native HTTP broker deadline expired')
        line = process.stdout.readline()
        if not line:
            raise requests.ConnectionError('Native HTTP broker closed')
        data = json.loads(line)
        if 'error' in data:
            detail = self.fixture.redact(data.get('detail', ''))
            raise requests.ConnectionError('Native HTTP broker: ' + data['error'] + ': ' + detail)
        self.cookies.update(data['cookies'])
        response = requests.Response()
        response.status_code = data['status']
        response._content = data['body'].encode()
        response.encoding = 'utf-8'
        return response


class Fixture:
    def __init__(self, archive, controlled_failure=False):
        assert sha(archive.read_bytes()) == ARCHIVE_SHA, 'Saved archive hash differs'
        self.archive = archive
        self.controlled_failure = controlled_failure
        self.root = Path(tempfile.mkdtemp(prefix='dify-native-roles-01a122b4-'))
        self.secret_values = []
        self.source_hashes = {path.name: sha(path.read_bytes()) for path in HERE.glob('*.py')}
        self.report = {'status': 'running', 'archive_sha256': ARCHIVE_SHA, 'images': IMAGES,
                       'cases': [], 'cleanup': {}, 'limits': [
                           'CE backend APIs only; no browser, Cloud, '
                           'Enterprise RBAC or Agent checks',
                           'Pinned daemon binary has no source-revision label',
                           'No real delivery, final rebuilt archive or publisher acceptance']}
        self.sessions = {}
        self.credentials = {}
        self.apps = {}
        self.installed = set()
        self.seed = None
        self.broker = None
        self.created_project = False
        self.compose_path = self.root / 'compose.json'
        self.baseline = self.inventory()
        (self.root / 'baseline.json').write_text(stable(self.baseline))
        print('Fixture evidence: ' + str(self.root), flush=True)

    def command(self, args, *, data=None, timeout=180, check=True):
        result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=timeout)
        log = self.root / 'commands.log'
        with log.open('a') as stream:
            stream.write(stable({'argv': args, 'returncode': result.returncode}) + '\n')
            stream.write(self.redact(result.stdout + result.stderr) + '\n')
        log.chmod(0o600)
        if check and result.returncode:
            raise RuntimeError(f'Command failed ({result.returncode}): {args[:4]}: '
                               + self.redact((result.stdout + result.stderr)[-4000:]))
        return result.stdout

    def dc(self, *args, **kwargs):
        return self.command(['docker', 'compose', '-p', PROJECT, '-f', str(self.compose_path),
                             *args], **kwargs)

    def inventory(self):
        result = subprocess.run(['docker', 'ps', '-q', '--no-trunc'], text=True,
                                capture_output=True, check=True, timeout=30)
        ids = result.stdout.split()
        if not ids:
            return []
        data = json.loads(subprocess.run(['docker', 'inspect', *ids], text=True,
                                       capture_output=True, check=True, timeout=30).stdout)
        return [{'id': item['Id'], 'name': item['Name'], 'image': item['Image'],
                 'ports': item['HostConfig']['PortBindings'],
                 'networks': sorted(item['NetworkSettings']['Networks'])} for item in data]

    def redact(self, text):
        for secret in self.secret_values:
            if secret:
                text = text.replace(secret, '[REDACTED]')
        text = text.replace('Synthetic local fixture only', '[fixture-body]')
        text = text.replace('Native role fixture', '[fixture-subject-or-label]')
        return re.sub(r'[A-Za-z0-9_.+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}',
                      lambda match: '[email-sha256:' + sha(match[0].encode())[:12] + ']', text)

    def secret(self):
        value = secrets.token_urlsafe(32)
        self.secret_values.extend([value, base64.b64encode(value.encode()).decode()])
        return value

    def private_json(self, path, value):
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(json.dumps(value))
        temporary.chmod(0o600)
        temporary.replace(path)

    def generate(self):
        secret_dir = self.root / 'secrets'
        secret_dir.mkdir(mode=0o700)
        (self.root / 'records').mkdir()
        (self.root / 'wheelhouse').mkdir()
        self.password = 'Fixture9-' + self.secret()
        self.secret_values.append(self.password)
        self.emails = {role: f'fixture-{role}@example.com' for role in [*ROLES, 'owner_b']}
        now = datetime.datetime.now(datetime.timezone.utc)
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Native fixture CA')])
        ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
              .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - datetime.timedelta(minutes=5))
              .not_valid_after(now + datetime.timedelta(days=2))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .sign(ca_key, hashes.SHA256()))
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (x509.CertificateBuilder().subject_name(x509.Name([
                    x509.NameAttribute(NameOID.COMMON_NAME, 'api.mailchannels.net')]))
                .issuer_name(ca_name).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=5))
                .not_valid_after(now + datetime.timedelta(days=2))
                .add_extension(x509.SubjectAlternativeName([
                    x509.DNSName('api.mailchannels.net')]), critical=False)
                .sign(ca_key, hashes.SHA256()))
        for name, content in [('ca.crt', ca.public_bytes(serialization.Encoding.PEM)),
                              ('server.crt', cert.public_bytes(serialization.Encoding.PEM)),
                              ('server.key', key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))]:
            path = secret_dir / name
            path.write_bytes(content)
            path.chmod(0o600)
            if name.endswith('.key'):
                self.secret_values.append(content.decode())
        labels = ['shared', 'owner-private', 'admin-private', 'owner-disposable',
                  'admin-disposable', 'cross-private', 'workspace-b',
                  'forbidden-editor', 'forbidden-normal', 'forbidden-dataset_operator']
        self.credentials = {label: {'key': 'native-synthetic-' + self.secret()}
                            for label in labels}
        self.private_json(secret_dir / 'mock-fixtures.json', {
            sha(value['key'].encode()): label for label, value in self.credentials.items()})
        self.origin = 'http://127.0.0.1:5001'
        self.base = self.origin + '/console/api'
        pg_password, redis_password, daemon_key, inner_key = [self.secret() for _ in range(4)]
        common = {'DEPLOYMENT_EDITION': 'COMMUNITY', 'RBAC_ENABLED': 'false',
                  'SECRET_KEY': self.secret(), 'DB_TYPE': 'postgresql', 'DB_HOST': 'postgres',
                  'DB_PORT': '5432', 'DB_USERNAME': 'postgres', 'DB_PASSWORD': pg_password,
                  'DB_DATABASE': 'dify', 'REDIS_HOST': 'redis', 'REDIS_PORT': '6379',
                  'REDIS_PASSWORD': redis_password, 'REDIS_DB': '0',
                  'CELERY_BROKER_URL': f'redis://:{redis_password}@redis:6379/1',
                  'STORAGE_TYPE': 'opendal', 'OPENDAL_SCHEME': 'fs',
                  'OPENDAL_FS_ROOT': '/app/api/storage', 'ENABLE_EMAIL_PASSWORD_LOGIN': 'true',
                  'ALLOW_REGISTER': 'false', 'ALLOW_CREATE_WORKSPACE': 'false',
                  'MARKETPLACE_ENABLED': 'false', 'DISABLE_TELEMETRY': 'true',
                  'DO_NOT_TRACK': 'true', 'CI': 'true', 'CHECK_UPDATE_URL': 'http://mock/',
                  'ENABLE_COLLABORATION_MODE': 'false', 'PLUGIN_DAEMON_URL': 'http://daemon:5002',
                  'PLUGIN_DAEMON_KEY': daemon_key, 'INNER_API_KEY_FOR_PLUGIN': inner_key,
                  'CONSOLE_WEB_URL': self.origin, 'CONSOLE_API_URL': self.origin,
                  'LOG_LEVEL': 'WARNING', 'MIGRATION_ENABLED': 'false',
                  'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'ALL_PROXY': '',
                  'http_proxy': '', 'https_proxy': '', 'all_proxy': '',
                  'SSRF_PROXY_HTTP_URL': '', 'SSRF_PROXY_HTTPS_URL': '',
                  'NO_PROXY': '*', 'CELERY_WORKER_AMOUNT': '1',
                  'CELERY_QUEUES': ('workflow,workflow_storage,plugin,app_deletion,'
                                    'workflow_based_app_execution')}
        daemon = {'DB_TYPE': 'postgresql', 'DB_HOST': 'postgres', 'DB_PORT': '5432',
                  'DB_USERNAME': 'postgres', 'DB_PASSWORD': pg_password,
                  'DB_DATABASE': 'dify_plugin', 'DB_DEFAULT_DATABASE': 'postgres',
                  'DB_SSL_MODE': 'disable', 'REDIS_HOST': 'redis', 'REDIS_PORT': '6379',
                  'REDIS_PASSWORD': redis_password, 'SERVER_PORT': '5002',
                  'SERVER_KEY': daemon_key, 'PLUGIN_REMOTE_INSTALLING_HOST': '127.0.0.1',
                  'PLUGIN_REMOTE_INSTALLING_PORT': '5003', 'DIFY_INNER_API_URL': 'http://api:5001',
                  'DIFY_INNER_API_KEY': inner_key, 'FORCE_VERIFYING_SIGNATURE': 'false',
                  'PLUGIN_WORKING_PATH': '/app/storage/cwd', 'PLUGIN_STORAGE_TYPE': 'local',
                  'PLUGIN_STORAGE_LOCAL_ROOT': '/app/storage', 'PLUGIN_INSTALLED_PATH': 'plugin',
                  'PLUGIN_PACKAGE_CACHE_PATH': 'plugin_packages',
                  'PLUGIN_MEDIA_CACHE_PATH': 'assets',
                  'PIP_EXTRA_ARGS': '--no-index --find-links=/wheelhouse',
                  'PIP_MIRROR_AUTO_DETECT': 'false', 'PIP_MIRROR_URL': '',
                  'PYTHON_ENV_INIT_TIMEOUT': '120', 'PLUGIN_MAX_EXECUTION_TIMEOUT': '600',
                  'REQUESTS_CA_BUNDLE': '/fixture-ca.crt', 'SSL_CERT_FILE': '/fixture-ca.crt',
                  'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'ALL_PROXY': '',
                  'http_proxy': '', 'https_proxy': '', 'all_proxy': '', 'NO_PROXY': '*'}
        labels = {'native_roles_fixture': PROJECT}
        services = {}
        for name, image in IMAGES.items():
            services[name] = {'image': image, 'labels': labels, 'networks': ['isolated']}
        services['postgres'].update(environment={'POSTGRES_PASSWORD': pg_password,
            'POSTGRES_DB': 'dify'}, volumes=['postgres_data:/var/lib/postgresql/data'],
            healthcheck={'test': ['CMD-SHELL', 'pg_isready -U postgres -d dify'],
                         'interval': '2s', 'timeout': '3s', 'retries': 30})
        services['redis'].update(command=['redis-server', '--requirepass', redis_password])
        depends = {'postgres': {'condition': 'service_healthy'},
                   'redis': {'condition': 'service_started'}}
        services['api'].update(environment={**common, 'MODE': 'api', 'MIGRATION_ENABLED': 'true'},
            depends_on=depends,
            volumes=['api_storage:/app/api/storage', f'{HERE}:/fixture:ro'])
        services['worker'] = {**services['api'], 'environment': {**common, 'MODE': 'worker'},
                              'ports': []}
        services['daemon'].update(environment=daemon, depends_on=depends,
            volumes=['daemon_storage:/app/storage', f'{self.root}/wheelhouse:/wheelhouse:ro',
                     f'{secret_dir}/ca.crt:/fixture-ca.crt:ro'])
        services['mock'].update(command=['python', '/fixture/mock.py'],
            volumes=[f'{HERE}:/fixture:ro', f'{secret_dir}:/secrets:ro',
                     f'{self.root}/records:/records'],
            networks={'isolated': {'aliases': ['api.mailchannels.net']}})
        self.private_json(self.compose_path, {'services': services,
            'networks': {'isolated': {'internal': True, 'labels': labels}},
            'volumes': {name: {'labels': labels} for name in [
                'postgres_data', 'api_storage', 'daemon_storage']}})

    def prepare_wheels(self):
        # Dependency fetch is separate and finishes before native credentials exist.
        self.command(['docker', 'run', '--rm', '--name', PROJECT + '-wheels',
                      '--label', 'native_roles_fixture=' + PROJECT,
                      '-v', f'{self.root}/wheelhouse:/wheelhouse',
                      '-v', f'{HERE.parents[1]}/requirements.txt:/requirements.txt:ro',
                      IMAGES['mock'], 'python', '-m', 'pip', 'download', '--only-binary=:all:',
                      '-r', '/requirements.txt', '-d', '/wheelhouse'], timeout=300)
        self.report['wheelhouse'] = {path.name: sha(path.read_bytes()) for path in sorted(
            (self.root / 'wheelhouse').glob('*.whl'))}
        assert self.report['wheelhouse']

    def wait_ready(self):
        self.broker = subprocess.Popen(
            ['docker', 'compose', '-p', PROJECT, '-f', str(self.compose_path),
             'exec', '-T', 'api', '/app/api/.venv/bin/python', '/fixture/broker.py'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        session = NativeSession(self, 'readiness')
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                response = session.get(self.base + '/setup', timeout=3)
                if response.status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(1)
        raise RuntimeError('Native API readiness deadline expired')

    def prove_route(self):
        ids = self.dc('ps', '-q').split()
        items = guarded(json.loads(self.command(['docker', 'inspect', *ids])))
        network_name = PROJECT + '_isolated'
        assert {item['Config']['Labels']['com.docker.compose.service'] for item in items} == {
            'api', 'worker', 'daemon', 'postgres', 'redis', 'mock'}
        for item in items:
            assert set(item['NetworkSettings']['Networks']) == {network_name}
        network = json.loads(self.command(['docker', 'network', 'inspect', network_name]))[0]
        assert network['Internal'] is True
        mock = next(item for item in items if item['Config']['Labels'][
            'com.docker.compose.service'] == 'mock')
        mock_ip = mock['NetworkSettings']['Networks'][network_name]['IPAddress']
        code = """import json, socket, ssl, urllib.request
address = socket.gethostbyname('api.mailchannels.net')
ctx = ssl.create_default_context(cafile='/fixture-ca.crt')
assert urllib.request.urlopen('https://api.mailchannels.net/', context=ctx, timeout=5).status == 200
try:
    socket.create_connection(('1.1.1.1', 443), timeout=2)
except OSError:
    pass
else:
    raise AssertionError('External egress unexpectedly available')
print(json.dumps({'mock_ip':address,'tls_verified':True,'external_egress_blocked':True}))
"""
        output = self.dc('exec', '-T', 'daemon', 'python3', '-c', code)
        proof = json.loads(output)
        assert proof['mock_ip'] == mock_ip
        self.report['isolation'] = proof
        self.report['api_transport'] = (
            'real localhost HTTP through docker exec stdio; no host port')
        self.case('precredential_isolation', network='internal', tls_verified=True,
                  external_egress_blocked=True)

    def case(self, name, **data):
        self.report['cases'].append({'name': name, **data})
        print('PASS ' + name, flush=True)

    def call(self, role, method, path, expected=200, **kwargs):
        session = self.sessions[role]
        for cookie in session.cookies:
            if 'csrf' in cookie.name.lower():
                session.headers['X-CSRF-Token'] = cookie.value
        response = session.request(method, self.base + path, timeout=45, **kwargs)
        # Response bodies remain private and are redacted before any evidence is shared.
        for secret in self.secret_values:
            assert secret not in response.text, 'Secret leaked in native response'
        with (self.root / 'responses.jsonl').open('a') as stream:
            entry = {'role': role, 'method': method, 'path': path,
                     'status': response.status_code, 'body': self.redact(response.text)}
            stream.write(stable(entry) + '\n')
        assert response.status_code == expected, self.redact(
            f'{role} {method} {path}: expected {expected}, got {response.status_code}: '
            + response.text[:800])
        return response

    def setup(self):
        session = NativeSession(self, 'bootstrap')
        self.sessions['bootstrap'] = session
        # Setup legitimately echoes no password; login cookie values are private below.
        self.call('bootstrap', 'POST', '/setup', expected=201, json={
            'email': self.emails['owner'], 'name': 'Native fixture owner',
            'password': self.password, 'language': 'en-US'})
        output = self.dc('exec', '-T', 'api', '/app/api/.venv/bin/python', '/fixture/seed.py',
                         data=json.dumps({'owner_email': self.emails['owner'],
                                          'emails': self.emails, 'password': self.password}),
                         timeout=60)
        marker = next(line for line in output.splitlines() if line.startswith('FIXTURE_SEEDED '))
        self.seed = json.loads(marker[len('FIXTURE_SEEDED '):])
        self.report['seed'] = self.seed
        config = self.seed['config']
        assert config['DEPLOYMENT_EDITION'] == 'COMMUNITY'
        assert all(config[name] is False for name in [
            'RBAC_ENABLED', 'MARKETPLACE_ENABLED', 'ALLOW_REGISTER',
            'ALLOW_CREATE_WORKSPACE', 'ENABLE_COLLABORATION_MODE'])
        for role in [*ROLES, 'owner_b']:
            session = NativeSession(self, role)
            session.headers['Origin'] = self.origin
            response = session.post(self.base + '/login', json={'email': self.emails[role],
                'password': base64.b64encode(self.password.encode()).decode()}, timeout=15)
            assert response.status_code == 200, 'Native login failed for ' + role
            self.secret_values.extend(cookie.value for cookie in session.cookies)
            self.sessions[role] = session
            self.private_json(self.root / 'secrets' / (role + '-session.json'),
                              requests.utils.dict_from_cookiejar(session.cookies))
            summary = self.call(role, 'GET', '/workspaces/current/summary').json()
            workspace_id = self.seed['tenant_b' if role == 'owner_b' else 'tenant_a']
            workspaces = self.call(role, 'GET', '/workspaces').json()['workspaces']
            assert workspace_id in {row['id'] for row in workspaces}
            expected_role = 'owner' if role == 'owner_b' else role
            assert summary['role'] == expected_role, (
                f'{role} active workspace role: expected {expected_role}, got {summary["role"]}')
            assert summary['id'] == workspace_id, f'{role} has unexpected active workspace'
            self.case(role + '_native_membership', summary=summary)
        self.case('effective_ce_config', config=self.seed['config'])

    def install(self, role):
        with self.archive.open('rb') as stream:
            upload = self.call(role, 'POST', '/workspaces/current/plugin/upload/pkg',
                files={'pkg': (self.archive.name, stream, 'application/octet-stream')}).json()
        identifier = upload['unique_identifier']
        self.call(role, 'POST', '/workspaces/current/plugin/install/pkg',
                  json={'plugin_unique_identifiers': [identifier]})
        self.installed.add(role)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            data = self.call(role, 'GET', '/workspaces/current/plugin/list',
                             params={'page': 1, 'page_size': 100}).json()
            if data.get('plugins'):
                self.case(role + '_installed_archive', identifier=identifier, inventory=data)
                return
            time.sleep(1)
        raise RuntimeError('Native plugin installation deadline expired')

    def calls(self):
        path = self.root / 'records' / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def count(self):
        return len(self.calls())

    def listing(self, role, include=None):
        params = {'include_credential_ids': include} if include else {}
        data = self.call(role, 'GET', PREFIX + '/credentials', params=params).json()
        assert isinstance(data, list)
        return data

    def config(self, label, mode='send', alternate=False):
        assert label in self.credentials, 'Unknown credential fixture label: ' + label
        tag = label + ('-alternate' if alternate else '')
        return {'api_key': self.credentials[label]['key'], 'sender': f'{tag}@example.com',
                'allowed_recipients': f'{tag}@example.net', 'mode': mode}

    def assert_request(self, before, label=None, config=None, validation=False):
        added = self.calls()[before:]
        if label is None:
            assert added == [], 'Forbidden operation invoked provider'
            return
        assert len(added) == 1, added
        record = added[0]
        dry = validation or config['mode'] == 'dry_run'
        recipient = config['sender'] if validation else config['allowed_recipients']
        routing = {'from': {'email': config['sender']},
                   'personalizations': [{'to': [{'email': recipient}]}]}
        from mock import digest
        assert record['credential'] == label and record['dry_run'] == dry
        assert record['status'] == (200 if dry else 202)
        assert record['routing_sha256'] == digest(routing), record
        assert record['path'] == '/tx/v1/send' + ('?dry-run=true' if dry else '')

    def add(self, role, label, visibility=None, mode='send'):
        config = self.config(label, mode)
        before = self.count()
        payload = {'credentials': config, 'name': label, 'type': 'api-key'}
        if visibility:
            payload['visibility'] = visibility
        self.call(role, 'POST', PREFIX + '/add', json=payload)
        self.assert_request(before, label, config, validation=True)
        credential = next(row for row in self.listing(role) if row['name'] == label)
        self.credentials[label].update(id=credential['id'], role=role, config=config)
        self.case(role + '_add_' + label, credential_id=credential['id'],
                  visibility=credential.get('visibility'), mock_requests=1)
        return credential['id']

    def graph(self, credential, config):
        def node(identifier, data, x):
            return {'id': identifier, 'type': 'custom', 'data': data,
                    'position': {'x': x, 'y': 100}}
        tool = {'type': 'tool', 'title': 'MailChannels', 'provider_id': PROVIDER,
                'provider_type': 'builtin', 'provider_name': 'MailChannels',
                'tool_name': 'send_email', 'tool_label': 'Send email', 'tool_configurations': {},
                'tool_parameters': {key: {'type': 'mixed', 'value': value} for key, value in {
                    'to': config['allowed_recipients'], 'subject': 'Native role fixture',
                    'text': 'Synthetic local fixture only'}.items()}}
        if credential is not None:
            tool['credential_id'] = credential
        return {'nodes': [node('start', {'type': 'start', 'title': 'Start', 'variables': []}, 0),
                         node('mail', tool, 300), node('end', {'type': 'end', 'title': 'End',
                            'outputs': [{'value_selector': ['mail', 'json'], 'variable': 'result',
                                         'value_type': 'array[object]'}]}, 600)],
                'edges': [{'id': source + '-' + target, 'source': source, 'target': target,
                           'sourceHandle': 'source', 'targetHandle': 'target', 'type': 'custom'}
                          for source, target in [('start', 'mail'), ('mail', 'end')]]}

    def create_app(self, role, credential, config):
        app = self.call(role, 'POST', '/apps', expected=201, json={'name': 'Native role fixture',
            'mode': 'workflow', 'description': 'Synthetic local fixture only'}).json()
        self.apps[role] = app['id']
        self.call(role, 'GET', f'/apps/{app["id"]}/workflows/draft', expected=404)
        self.call(role, 'POST', f'/apps/{app["id"]}/workflows/draft', json={
            'graph': self.graph(credential, config), 'features': {},
            'conversation_variables': [], 'hash': None})
        assert self.draft(role, app['id'])['graph'] == self.graph(credential, config)
        return app['id']

    def draft(self, role, app):
        return self.call(role, 'GET', f'/apps/{app}/workflows/draft').json()

    def save(self, role, app, graph):
        current = self.draft(role, app)
        self.call(role, 'POST', f'/apps/{app}/workflows/draft', json={
            'graph': graph, 'features': {}, 'conversation_variables': [], 'hash': current['hash']})
        saved = self.draft(role, app)
        assert saved['graph'] == graph
        return saved

    def run_node(self, role, app, label, config, name):
        before = self.count()
        data = self.call(role, 'POST', f'/apps/{app}/workflows/draft/nodes/mail/run',
                         json={'inputs': {}}).json()
        assert data['status'] == 'succeeded', data
        output = data['outputs']['json'][0]
        assert output['status'] == ('validated' if config['mode'] == 'dry_run' else 'accepted')
        if config['mode'] == 'send':
            assert output['delivery_confirmed'] is False
        self.assert_request(before, label, config)
        self.case(name, node_status=data['status'], output=output, mock_requests=1)

    def full_run(self, role, app, label, config):
        before = self.count()
        events = sse(self.call(role, 'POST', f'/apps/{app}/workflows/draft/run',
                               json={'inputs': {}}).text)
        finished = [event for event in events if event.get('event') == 'workflow_finished']
        assert finished and finished[-1]['data']['status'] == 'succeeded', events
        output = finished[-1]['data']['outputs']['result'][0]
        assert output['status'] == 'accepted' and output['delivery_confirmed'] is False
        self.assert_request(before, label, config)
        self.case(role + '_full_workflow', output=output, mock_requests=1)

    def prove_plugin_route(self):
        probe = """import json, pathlib
paths = [str(path) for path in pathlib.Path('/app/storage/cwd').rglob('bin/python')]
print(json.dumps(paths))
"""
        interpreters = json.loads(self.dc('exec', '-T', 'daemon', 'python3', '-c', probe))
        assert interpreters, 'No native plugin interpreter found'
        code = """import json, os, requests, socket
assert not any(os.environ.get(name) for name in [
    'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'])
assert os.environ['REQUESTS_CA_BUNDLE'] == '/fixture-ca.crt'
session = requests.Session()
assert session.trust_env is True
assert session.get('https://api.mailchannels.net/', timeout=5).status_code == 200
print(json.dumps({'mock_ip': socket.gethostbyname('api.mailchannels.net'),
                  'requests_trust_env': session.trust_env, 'tls_verified': True}))
"""
        for interpreter in interpreters:
            result = json.loads(self.dc('exec', '-T', 'daemon', interpreter, '-c', code))
            assert result['mock_ip'] == self.report['isolation']['mock_ip']
        self.case('native_plugin_requests_dns_tls', interpreter_count=len(interpreters),
                  requests_trust_env=True, proxies_empty=True, tls_verified=True)

    def database_state(self):
        assert self.seed
        import uuid
        tenants = [str(uuid.UUID(self.seed[name])) for name in ['tenant_a', 'tenant_b']]
        sql = ("SELECT json_build_object('count',count(*),'rows_md5',"
               "md5(coalesce(string_agg(row_to_json(p)::text,'' ORDER BY id),''))) "
               "FROM tool_builtin_providers p WHERE tenant_id IN ('"
               + "','".join(tenants) + "') AND provider='" + PROVIDER + "';")
        return json.loads(self.dc('exec', '-T', 'postgres', 'psql', '-U', 'postgres',
                                 '-d', 'dify', '-At', '-c', sql).strip())

    def denied(self, role, method, path, payload=None, status=403):
        before_calls = self.count()
        state = self.database_state()
        expected_count = sum('id' in value for value in self.credentials.values())
        assert state['count'] == expected_count, 'Scoped database proof misses fixture rows'
        before_listing = self.listing('owner')
        response = self.call(role, method, path, expected=status,
                             **({'json': payload} if payload is not None else {}))
        self.assert_request(before_calls)
        assert self.database_state() == state, 'Denied mutation changed scoped credential rows'
        assert self.listing('owner') == before_listing
        error_code = response.json().get('code')
        expected_code = {400: 'invalid_param', 404: 'app_not_found'}.get(status, 'forbidden')
        if path == '/workspaces/switch':
            expected_code = 'account_not_link_tenant'
        assert error_code == expected_code, f'{role} denied error code: {error_code}'
        self.case(role + '_denied_' + path.rsplit('/', 1)[-1], http_status=status,
                  method=method, path=path,
                  database_state=state, mock_requests=0,
                  error_code=error_code)

    def matrix(self):
        for role in ['owner', 'owner_b']:
            self.install(role)
        self.prove_plugin_route()
        shared = self.add('owner', 'shared')
        owner_private = self.add('owner', 'owner-private', 'only_me')
        admin_private = self.add('admin', 'admin-private', 'only_me')
        for role in ROLES:
            rows = self.listing(role)
            expected_ids = {shared}
            if role == 'owner':
                expected_ids.add(owner_private)
            if role == 'admin':
                expected_ids.add(admin_private)
            assert {row['id'] for row in rows} == expected_ids
            shared_row = next(row for row in rows if row['id'] == shared)
            assert shared_row['visibility'] == 'all_team_members'
            info = self.call(role, 'GET', PREFIX + '/credential/info').json()
            assert info['credentials'] == rows
            for row in rows:
                assert row['credentials']['api_key'] != self.credentials[
                    row['name']]['key']
            self.case(role + '_masked_visibility', credential_ids=sorted(expected_ids),
                      info_schema_agrees=True, api_keys_masked=True)
        borrowed = self.listing('editor', [owner_private])
        private_row = next(row for row in borrowed if row['id'] == owner_private)
        assert private_row['from_other_member'] is True
        self.case('borrowed_private_metadata', credential_id=owner_private,
                  from_other_member=True, api_key_masked=True)

        # Positive mutation controls include configuration changes, not only names.
        for role in ['owner', 'admin']:
            label = role + '-disposable'
            disposable = self.add(role, label)
            updated = self.config(label, 'dry_run', alternate=True)
            before = self.count()
            self.call(role, 'POST', PREFIX + '/update', json={
                'credential_id': disposable, 'credentials': updated, 'name': label + '-updated'})
            self.assert_request(before, label, updated, validation=True)
            row = next(row for row in self.listing(role) if row['id'] == disposable)
            assert row['name'] == label + '-updated'
            fields = ['sender', 'allowed_recipients', 'mode']
            assert {key: row['credentials'][key] for key in fields} == {
                key: updated[key] for key in ['sender', 'allowed_recipients', 'mode']}
            before = self.count()
            self.call(role, 'POST', PREFIX + '/default-credential', json={'id': disposable})
            assert next(row for row in self.listing(role) if row['id'] == disposable)['is_default']
            self.call(role, 'POST', PREFIX + '/delete', json={'credential_id': disposable})
            assert disposable not in {row['id'] for row in self.listing(role)}
            self.assert_request(before)
            self.case(role + '_update_default_delete', updated_configuration=True,
                      dry_run_validation_requests=1, metadata_requests=0)
            del self.credentials[label]
        cross_private = self.add('owner', 'cross-private', 'only_me')
        before = self.count()
        self.call('admin', 'POST', PREFIX + '/update', json={
            'credential_id': cross_private, 'name': 'privileged rename'})
        assert next(row for row in self.listing('owner') if row['id'] == cross_private)[
            'name'] == 'privileged rename'
        self.call('admin', 'POST', PREFIX + '/delete', json={'credential_id': cross_private})
        assert cross_private not in {row['id'] for row in self.listing('owner')}
        self.assert_request(before)
        del self.credentials['cross-private']
        self.case('admin_mutates_other_creator_private', mock_requests=0)
        self.call('owner', 'POST', PREFIX + '/default-credential', json={'id': shared})

        for role in ['editor', 'normal', 'dataset_operator']:
            for action, payload in [
                ('add', {'credentials': self.config('forbidden-' + role),
                         'name': 'forbidden-' + role, 'type': 'api-key'}),
                ('update', {'credential_id': shared,
                            'credentials': self.config('shared', 'dry_run', alternate=True),
                            'name': 'forbidden change'}),
                ('delete', {'credential_id': shared}),
                ('default-credential', {'id': owner_private})]:
                self.denied(role, 'POST', PREFIX + '/' + action, payload)
        shared_config = self.credentials['shared']['config']
        app_a = self.create_app('owner', shared, shared_config)
        self.report['workflow_graph_sha256'] = sha(
            stable(self.graph(shared, shared_config)).encode())
        for role in ROLES:
            if role in ['owner', 'admin', 'editor']:
                self.save(role, app_a, self.graph(shared, shared_config))
                self.case(role + '_draft_read_save', persisted_graph=True)
                self.run_node(role, app_a, 'shared', shared_config, role + '_node_run')
                self.full_run(role, app_a, 'shared', shared_config)
            else:
                draft = self.draft('owner', app_a)
                changed = self.graph(shared, shared_config)
                changed['nodes'][1]['data']['title'] = 'Forbidden modification'
                for method, suffix, payload in [
                    ('GET', '', None),
                    ('POST', '', {'graph': changed, 'features': {},
                                  'conversation_variables': [], 'hash': draft['hash']}),
                    ('POST', '/nodes/mail/run', {'inputs': {}}),
                    ('POST', '/run', {'inputs': {}})]:
                    self.denied(role, method,
                                f'/apps/{app_a}/workflows/draft' + suffix, payload)
                    assert self.draft('owner', app_a) == draft, 'Denied operation changed draft'
                self.case(role + '_draft_unchanged',
                          graph_sha256=sha(stable(draft['graph']).encode()))
        private_config = self.credentials['owner-private']['config']
        self.save('editor', app_a, self.graph(owner_private, private_config))
        self.run_node('editor', app_a, 'owner-private', private_config,
                      'editor_uses_other_creator_private_id')
        self.call('owner', 'POST', PREFIX + '/default-credential', json={'id': owner_private})
        self.save('editor', app_a, self.graph(None, private_config))
        self.run_node('editor', app_a, 'owner-private', private_config,
                      'editor_uses_omitted_id_private_default')
        self.call('owner', 'POST', PREFIX + '/default-credential', json={'id': shared})
        self.save('owner', app_a, self.graph(shared, shared_config))

        b_id = self.add('owner_b', 'workspace-b')
        b_config = self.credentials['workspace-b']['config']
        app_b = self.create_app('owner_b', b_id, b_config)
        self.run_node('owner_b', app_b, 'workspace-b', b_config, 'workspace_b_positive')
        for method, suffix, payload in [('GET', '', None),
                                        ('POST', '/nodes/mail/run', {'inputs': {}}),
                                        ('POST', '/run', {'inputs': {}})]:
            self.denied('owner_b', method,
                        f'/apps/{app_a}/workflows/draft' + suffix, payload, 404)
        for action, payload in [
            ('update', {'credential_id': shared, 'name': 'Foreign mutation',
                        'credentials': b_config}),
            ('delete', {'credential_id': shared}), ('default-credential', {'id': shared})]:
            self.denied('owner_b', 'POST', PREFIX + '/' + action, payload, 400)
        rows_b = self.listing('owner_b', [shared, owner_private])
        assert {row['id'] for row in rows_b} == {b_id}
        self.case('foreign_credential_not_returned', included_foreign_ids=True, mock_requests=0)
        self.save('owner_b', app_b, self.graph(shared, b_config))
        before = self.count()
        data = self.call('owner_b', 'POST', f'/apps/{app_b}/workflows/draft/nodes/mail/run',
                         json={'inputs': {}}).json()
        assert data['status'] == 'failed', data
        self.assert_request(before)
        self.case('configured_workspace_b_foreign_uuid_failed', http_status=200,
                  node_status='failed', mock_requests=0)
        self.save('owner_b', app_b, self.graph(b_id, b_config))
        self.denied('owner', 'POST', PREFIX + '/delete', {'credential_id': b_id}, 400)

        workspaces = self.call('editor', 'GET', '/workspaces').json()['workspaces']
        assert {row['id'] for row in workspaces} == {
            self.seed['tenant_a'], self.seed['tenant_b']}
        self.call('editor', 'POST', '/workspaces/switch', json={'tenant_id': self.seed['tenant_b']})
        summary_b = self.call('editor', 'GET', '/workspaces/current/summary').json()
        assert summary_b['id'] == self.seed['tenant_b'] and summary_b['role'] == 'normal'
        self.denied('editor', 'GET', f'/apps/{app_b}/workflows/draft')
        self.denied('editor', 'POST',
                    f'/apps/{app_b}/workflows/draft/nodes/mail/run', {'inputs': {}})
        self.call('editor', 'POST', '/workspaces/switch', json={'tenant_id': self.seed['tenant_a']})
        summary_a = self.call('editor', 'GET', '/workspaces/current/summary').json()
        assert summary_a['id'] == self.seed['tenant_a'] and summary_a['role'] == 'editor'
        self.run_node('editor', app_a, 'shared', shared_config, 'editor_switch_back_positive')
        self.case('active_workspace_role_switch',
                  workspace_a_role='editor', workspace_b_role='normal')
        original = self.call('normal', 'GET', '/workspaces/current/summary').json()
        self.denied('normal', 'POST', '/workspaces/switch',
                    {'tenant_id': self.seed['tenant_b']}, 403)
        assert self.call('normal', 'GET', '/workspaces/current/summary').json() == original
        self.case('unjoined_workspace_switch_preserves_context', mock_requests=0)

    def native_cleanup(self):
        errors = []
        for role in ['owner', 'owner_b']:
            if role not in self.sessions:
                continue
            try:
                # include every known same-workspace private ID, including admin-created rows.
                included = [value['id'] for value in self.credentials.values()
                            if 'id' in value and
                            (value['role'] == 'owner_b') == (role == 'owner_b')]
                for row in self.listing(role, included):
                    self.call(role, 'POST', PREFIX + '/delete', json={'credential_id': row['id']})
                assert self.listing(role, included) == []
                if role in self.apps:
                    before = self.count()
                    path = f'/apps/{self.apps[role]}/workflows/draft/nodes/mail/run'
                    data = self.call(role, 'POST', path,
                                     json={'inputs': {}}).json()
                    assert data['status'] == 'failed', data
                    self.assert_request(before)
                    self.case(role + '_deleted_credential_blocks_old_workflow', mock_requests=0)
                if role in self.installed:
                    inventory = self.call(role, 'GET', '/workspaces/current/plugin/list',
                                          params={'page': 1, 'page_size': 100}).json()
                    for plugin in inventory['plugins']:
                        self.call(role, 'POST', '/workspaces/current/plugin/uninstall',
                                  json={'plugin_installation_id': plugin['id']})
                    assert self.call(role, 'GET', '/workspaces/current/plugin/list',
                        params={'page': 1, 'page_size': 100}).json()['plugins'] == []
                    self.case(role + '_native_uninstall', inventory_absent=True)
                if role in self.apps:
                    self.call(role, 'DELETE', '/apps/' + self.apps[role], expected=204)
            except Exception as error:
                errors.append(self.redact(str(error)))
        if self.seed:
            try:
                state = self.database_state()
                assert state['count'] == 0, state
                self.report['cleanup']['provider_database'] = state
            except Exception as error:
                errors.append(self.redact(str(error)))
        self.report['cleanup']['native_errors'] = errors
        if errors:
            self.report['status'] = 'failed'

    def teardown(self):
        if self.broker is not None:
            self.broker.terminate()
            self.broker.wait(timeout=10)
        wheels = self.command(['docker', 'ps', '-aq', '--filter',
                               'name=^/' + PROJECT + '-wheels$']).split()
        if wheels:
            wheel = json.loads(self.command(['docker', 'inspect', *wheels]))
            assert all(item['Name'] == '/' + PROJECT + '-wheels' and item['Config']['Labels'].get(
                'native_roles_fixture') == PROJECT for item in wheel)
            self.command(['docker', 'rm', '-f', *wheels])
        ids = self.command(['docker', 'ps', '-aq', '--filter',
                            'label=com.docker.compose.project=' + PROJECT]).split()
        if ids:
            guarded(json.loads(self.command(['docker', 'inspect', *ids])))
        if self.created_project:
            for kind in ['volume', 'network']:
                names = self.command(['docker', kind, 'ls', '-q', '--filter',
                                      'name=^' + PROJECT + '_']).split()
                if names:
                    resources = json.loads(self.command(['docker', kind, 'inspect', *names]))
                    assert all(item['Labels'].get('native_roles_fixture') == PROJECT and
                               item['Labels'].get('com.docker.compose.project') == PROJECT
                               for item in resources), 'Refusing unowned project storage/network'
            self.dc('logs', '--no-color', timeout=30, check=False)
            self.dc('down', '--volumes', '--remove-orphans', timeout=90)
        residual = self.command(['docker', 'ps', '-aq', '--filter',
                                 'label=com.docker.compose.project=' + PROJECT]).split()
        assert residual == [], 'Owned containers remain'
        for kind in ['volume', 'network']:
            assert not self.command(['docker', kind, 'ls', '-q', '--filter',
                                     'name=^' + PROJECT + '_']).split(), (
                'Owned ' + kind + ' remains')
        self.report['cleanup'].update(volumes_absent=True, networks_absent=True)
        current = self.inventory()
        current_by_id = {item['id']: item for item in current}
        self.report['cleanup']['containers_absent'] = True
        assert all(current_by_id.get(item['id']) == item for item in self.baseline), (
            'A prior unrelated running container changed')
        baseline_ids = {item['id'] for item in self.baseline}
        self.report['cleanup'].update(unrelated_baseline_preserved=True,
            unrelated_additions=[item for item in current if item['id'] not in baseline_ids])

    def execute(self):
        try:
            existing = self.command(['docker', 'ps', '-aq', '--filter',
                                     'label=com.docker.compose.project=' + PROJECT]).split()
            assert not existing, 'Refusing to reuse an existing fixture project'
            for kind in ['volume', 'network']:
                assert not self.command(['docker', kind, 'ls', '-q', '--filter',
                                         'name=^' + PROJECT + '_']).split(), (
                    'Refusing to reuse existing fixture ' + kind)
            self.generate()
            image_info = json.loads(self.command(['docker', 'image', 'inspect', *IMAGES.values()]))
            assert all(item['Architecture'] == 'arm64' for item in image_info)
            self.report['observed_images'] = [{
                'id': item['Id'], 'repo_digests': item['RepoDigests'],
                'architecture': item['Architecture'], 'labels': item['Config'].get('Labels')}
                for item in image_info]
            assert 'COMMIT_SHA=8387590ace4a094de812b7847fc6a4c3a27cd52b' in (
                image_info[0]['Config']['Env'])
            self.prepare_wheels()
            self.created_project = True
            self.dc('up', '-d', 'postgres', 'redis', 'mock', 'daemon', 'api', timeout=120)
            self.wait_ready()
            uid = int(self.dc('exec', '-T', 'api', 'id', '-u').strip())
            gid = int(self.dc('exec', '-T', 'api', 'id', '-g').strip())
            self.dc('exec', '-T', '-u', '0', 'api', 'chown', '-R',
                    f'{uid}:{gid}', '/app/api/storage')
            self.dc('up', '-d', 'worker', timeout=60)
            self.prove_route()
            if self.controlled_failure:
                raise RuntimeError('Controlled precredential failure')
            self.setup()
            self.matrix()
            self.report['status'] = 'passed'
        except (Exception, KeyboardInterrupt) as error:
            detail = str(error) or type(error).__name__
            self.report.update(status='failed', error=self.redact(detail),
                               traceback=self.redact(traceback.format_exc()))
            print('FAIL ' + self.redact(str(error)), flush=True)
        finally:
            try:
                if self.seed:
                    self.native_cleanup()
                self.teardown()
            except Exception as error:
                self.report['status'] = 'failed'
                self.report['cleanup']['error'] = self.redact(str(error))
            controlled = self.report.get('error') == 'Controlled precredential failure'
            if self.controlled_failure and controlled:
                assert self.report['cleanup'].get('containers_absent')
                assert self.report['cleanup'].get('unrelated_baseline_preserved')
                self.report['status'] = 'controlled_failure_cleaned'
            self.report['mock_requests'] = self.count()
            self.report['fixture_sources'] = self.source_hashes
            self.report = json.loads(self.redact(stable(self.report)))
            evidence = stable(self.report)
            for secret in self.secret_values:
                assert secret not in evidence, 'Secret in acceptance evidence'
            (self.root / 'acceptance.json').write_text(json.dumps(self.report, indent=2))
            log_paths = [self.root / 'commands.log', self.root / 'responses.jsonl',
                         self.root / 'records' / 'calls.jsonl']
            for path in log_paths:
                if path.exists():
                    text = path.read_text()
                    assert all(secret not in text for secret in self.secret_values)
            (self.root / 'log-hashes.json').write_text(json.dumps({
                str(path.relative_to(self.root)): sha(path.read_bytes())
                for path in log_paths if path.exists()}, indent=2))
            if self.report['cleanup'].get('containers_absent'):
                self.report['compose_sha256'] = sha(self.compose_path.read_bytes())
                self.compose_path.unlink()
                shutil.rmtree(self.root / 'secrets')
                shutil.rmtree(self.root / 'wheelhouse')
                self.report['cleanup']['generated_secrets_and_wheels_removed'] = True
                (self.root / 'acceptance.json').write_text(json.dumps(self.report, indent=2))
            print('Result: ' + self.report['status'], flush=True)
        return self.report['status']


def self_check():
    assert sse('event: message\ndata: {"event":"workflow_finished"}\n\n') == [
        {'event': 'workflow_finished'}]
    assert sse('noise\n') == []
    valid = {'Config': {'Labels': {'com.docker.compose.project': PROJECT,
                                  'native_roles_fixture': PROJECT}}}
    assert guarded([valid]) == [valid]
    try:
        guarded([{'Config': {'Labels': {'com.docker.compose.project': 'unrelated'}}}])
    except AssertionError:
        pass
    else:
        raise AssertionError('Ownership guard accepted unrelated resource')
    instance = object.__new__(Fixture)
    instance.secret_values = ['synthetic-secret', 'session-value']
    assert instance.redact('synthetic-secret/session-value') == '[REDACTED]/[REDACTED]'
    with tempfile.TemporaryDirectory(prefix='native-roles-self-check-') as name:
        path = Path(name) / 'private.json'
        instance.private_json(path, {'value': 'first'})
        instance.private_json(path, {'value': 'second'})
        assert json.loads(path.read_text()) == {'value': 'second'}
        assert path.stat().st_mode & 0o777 == 0o600
        assert not path.with_name('private.json.tmp').exists()
    assert 'sender@example.com' not in instance.redact('sender@example.com')
    assert 'Synthetic local fixture only' not in instance.redact('Synthetic local fixture only')
    package_script = (HERE.parents[1] / 'scripts' / 'package.py').read_text()
    assert "'tests'" not in package_script and 'native_roles' not in package_script
    print('Offline parser/redaction/ownership/package-exclusion checks passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--fail-before-credentials', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.self_check:
        self_check()
    else:
        if not args.archive:
            parser.error('--archive is required')
        status = Fixture(args.archive.resolve(), args.fail_before_credentials).execute()
        raise SystemExit(0 if status in ['passed', 'controlled_failure_cleaned'] else 1)
