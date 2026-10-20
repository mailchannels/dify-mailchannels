"""Real loopback inactivity checks, isolated from Dify's gevent monkeypatches."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


URL = "https://api.mailchannels.net/tx/v1/send"
KEY = "synthetic-timeout-key"
CONTENT = "synthetic-private-timeout-content"
INACTIVITY_SECONDS = 1.0


@pytest.mark.parametrize("mode", ["dry_run", "send"])
@pytest.mark.parametrize("scenario", ["headers", "body", "trickle"])
def test_real_response_inactivity(scenario, mode):
    # A fresh interpreter keeps the watchdog independent of Dify's patched threading.
    runtime = Path.cwd().resolve()
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), scenario, mode],
        env={**os.environ, "MAILCHANNELS_TEST_RUNTIME": str(runtime)},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout.strip())


def check_response(scenario, mode):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import socket
    import threading
    import time
    from unittest.mock import patch
    from urllib.parse import parse_qs, urlsplit

    runtime = Path(os.environ["MAILCHANNELS_TEST_RUNTIME"]).resolve()
    sys.path.insert(0, str(runtime))
    import mail_service
    import requests

    source = Path(mail_service.__file__).resolve()
    assert source == runtime / "mail_service.py"
    release = threading.Event()
    received = threading.Event()
    watchdog_fired = threading.Event()
    connections, posts, sessions, responses, errors = [], [], [], [], []
    body = json.dumps(
        {"data": [CONTENT]} if mode == "dry_run" else {
            "request_id": "local-request", "results": [{
                "index": 0, "status": "sent", "message_id": "local-message", "reason": KEY,
            }],
        }
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            connections.append(self.connection)
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            posts.append((self.path, self.headers["X-Api-Key"], payload))
            received.set()
            try:
                if scenario == "headers":
                    assert release.wait(10)
                    return
                self.send_response(200 if mode == "dry_run" else 202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if scenario == "body":
                    self.wfile.write(body[:1])
                    self.wfile.flush()
                    assert release.wait(10)
                    return
                chunks = [body[i * len(body) // 25:(i + 1) * len(body) // 25] for i in range(25)]
                for chunk in chunks:
                    if release.wait(0.1):
                        return
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                # The watchdog may interrupt the handler while demonstrating a regression.
                if not release.is_set():
                    raise

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    local_url = f"http://127.0.0.1:{server.server_port}/tx/v1/send"
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    worker.start()

    def close_connections():
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def interrupt():
        watchdog_fired.set()
        release.set()
        close_connections()

    watchdog = threading.Timer(8, interrupt)
    watchdog.start()
    session_type = mail_service.NoRedirectSession
    transport_type = mail_service.FixedEndpointTransport

    class LocalSession(session_type):
        def __init__(self):
            super().__init__()
            self.trust_env = False
            self.closed = False
            sessions.append(self)

        def request(self, method, url, **kwargs):
            assert method.upper() == "POST" and url == URL
            assert kwargs["timeout"] == INACTIVITY_SECONDS
            assert kwargs["stream"] is True and kwargs["allow_redirects"] is False
            try:
                response = super().request(method, local_url, **kwargs)
            except requests.RequestException as error:
                errors.append(type(error).__name__)
                raise
            responses.append(response)
            original_close = response.close
            original_iter = response.iter_content
            response.closed_by_transport = False

            def close():
                response.closed_by_transport = True
                original_close()

            response.close = close

            def iter_content(*args, **kwargs):
                try:
                    yield from original_iter(*args, **kwargs)
                except requests.RequestException as error:
                    errors.append(type(error).__name__)
                    raise

            response.iter_content = iter_content
            return response

        def close(self):
            self.closed = True
            super().close()

    def transport_factory(*, timeout):
        assert timeout == 30
        return transport_type(timeout=INACTIVITY_SECONDS)

    try:
        with patch.object(mail_service, "NoRedirectSession", LocalSession):
            with transport_type() as guarded:
                for method, url in [("GET", URL), ("POST", "https://untrusted.example/send")]:
                    with pytest.raises(ValueError):
                        guarded.request(method, url, headers={"X-Api-Key": KEY})
            assert not posts
            settings = mail_service.settings_from({
                "api_key": KEY, "sender": "sender@example.com",
                "allowed_recipients": "recipient@example.net", "mode": mode,
            })
            message = mail_service.Message(
                to="recipient@example.net", subject="Local inactivity check", text=CONTENT,
            )
            started = time.monotonic()
            with patch.object(mail_service, "FixedEndpointTransport", transport_factory):
                outcome = mail_service.send(settings, message)
            elapsed = time.monotonic() - started
        assert received.is_set() and len(posts) == 1
        path, key, payload = posts[0]
        assert path.split("?")[0] == "/tx/v1/send" and key == KEY
        assert parse_qs(urlsplit(path).query) == (
            {"dry-run": ["true"]} if mode == "dry_run" else {}
        )
        assert payload["content"] == [{"type": "text/plain", "value": CONTENT}]
        assert KEY not in json.dumps(outcome) and CONTENT not in json.dumps(outcome)
        assert outcome["dry_run"] is (mode == "dry_run")
        assert not watchdog_fired.is_set(), "watchdog fired: inactivity timeout did not finish"
        assert elapsed >= INACTIVITY_SECONDS
        if scenario == "trickle":
            assert outcome["status"] == ("validated" if mode == "dry_run" else "accepted")
            if mode == "send":
                assert outcome["delivery_confirmed"] is False
            else:
                assert outcome["sent"] is False
        else:
            assert outcome["status"] == "unknown" and outcome["retry_safe"] is False
        assert len(responses) == (0 if scenario == "headers" else 1)
        assert errors if scenario != "trickle" else not errors
        assert all(response.closed_by_transport and response.raw.closed for response in responses)
        assert len(sessions) == 2 and all(session.closed for session in sessions)
    finally:
        release.set()
        watchdog.cancel()
        close_connections()
        server.shutdown()
        server.server_close()
        worker.join(2)
        watchdog.join(2)
        for session in sessions:
            session.close()
        assert not worker.is_alive() and not watchdog.is_alive()
        assert server.socket.fileno() == -1
        assert all(connection.fileno() == -1 for connection in connections)
        if watchdog_fired.is_set():
            print("Watchdog regression cleanup: workers joined; sockets and sessions closed")
    print(json.dumps({
        "scenario": scenario, "mode": mode, "status": outcome["status"],
        "elapsed_seconds": round(elapsed, 3), "request_exceptions": errors,
        "post_count": len(posts), "responses_closed": len(responses),
        "sessions_closed": len(sessions), "workers_joined": True, "sockets_closed": True,
        "runtime": str(source),
    }))


if __name__ == "__main__":
    check_response(*sys.argv[1:])
