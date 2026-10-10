"""Real localhost API transport for Docker Desktop internal networks."""
import base64
import json
import sys
from urllib.parse import urlsplit

import requests

sessions = {}
for line in sys.stdin:
    try:
        item = json.loads(line)
        role = item['role']
        if role not in sessions:
            sessions[role] = requests.Session()
            sessions[role].trust_env = False
        session = sessions[role]
        original = urlsplit(item['url'])
        headers = {**item.get('headers', {}), 'Host': original.netloc}
        files = {name: (value[0], base64.b64decode(value[1]), value[2])
                 for name, value in item.get('files', {}).items()}
        response = session.request(item['method'], 'http://127.0.0.1:5001' + original.path,
            headers=headers, params=item.get('params'), json=item.get('json'),
            files=files or None, timeout=item['timeout'])
        result = {'status': response.status_code, 'body': response.text,
                  'cookies': requests.utils.dict_from_cookiejar(session.cookies)}
    except Exception as error:
        # The host owns redaction and reports this bounded transport failure.
        result = {'error': type(error).__name__, 'detail': str(error)[:500]}
    print(json.dumps(result), flush=True)
