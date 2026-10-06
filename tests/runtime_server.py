"""Test-only bootstrap: real Dify runtime, intercepted MailChannels HTTP."""
import dify_plugin  # Initialize gevent before importing HTTP libraries.
import json
import os
import runpy
import sys
from urllib.parse import parse_qs, urlparse

import responses

sys.path.insert(0, os.getcwd())

def mock_send(request):
    payload = json.loads(request.body)
    if request.headers.get('X-Api-Key') == 'invalid-test-key':
        return 401, {}, json.dumps({'message': 'invalid-test-key must not leak'})
    if payload['subject'] == 'simulate timeout':
        import requests
        raise requests.Timeout('dummy-key must not leak')
    if parse_qs(urlparse(request.url).query).get('dry-run') == ['true']:
        result = {'data': ['synthetic MIME must not appear in output']}
        status = 200
    else:
        result = {'request_id': 'runtime-request', 'results': [
            {'index': 0, 'message_id': 'runtime-message', 'status': 'sent'}]}
        status = 202
    return status, {'Content-Type': 'application/json'}, json.dumps(result)

mock = responses.RequestsMock(assert_all_requests_are_fired=False)
mock.add_callback(responses.POST, 'https://api.mailchannels.net/tx/v1/send', callback=mock_send)
mock.start()
runpy.run_module('main', run_name='__main__')
