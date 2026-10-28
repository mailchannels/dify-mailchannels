"""Synthetic HTTPS endpoint; retain fixture identities and hashes only."""
import hashlib
import json
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'fixture TLS ready')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        fixtures = json.loads(Path('/secrets/mock-fixtures.json').read_text())
        key_hash = hashlib.sha256(self.headers.get('X-Api-Key', '').encode()).hexdigest()
        label = fixtures.get(key_hash)
        dry = parse_qs(urlparse(self.path).query).get('dry-run') == ['true']
        status = (200 if dry else 202) if label else 401
        record = {'credential': label or 'unrecognized', 'dry_run': dry, 'status': status,
                  'routing_sha256': digest({'from': body.get('from'),
                                            'personalizations': body.get('personalizations')}),
                  'payload_sha256': digest(body), 'path': self.path}
        with Path('/records/calls.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        data = {'data': ['Synthetic MIME']} if dry else {
            'request_id': 'fixture-request',
            'results': [{'index': 0, 'message_id': 'fixture-message', 'status': 'sent'}]}
        if not label:
            data = {'message': 'Unrecognized synthetic fixture'}
        encoded = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', 443), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain('/secrets/server.crt', '/secrets/server.key')
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
