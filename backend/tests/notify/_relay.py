# _relay.py - a local HTTP server standing in for Discord / ntfy (no real network).

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeRelay:
    """Records every POST; answers *status* (and *headers*) set by the test."""

    def __init__(self):
        self.requests: list[dict] = []
        self.status = 204
        self.headers: dict[str, str] = {}
        self.body = b""
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw or b"{}")
                except ValueError:
                    payload = {}
                relay.requests.append({"path": self.path, "json": payload})
                self.send_response(relay.status)
                for k, v in relay.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(relay.body)))
                self.end_headers()
                self.wfile.write(relay.body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def dead_url() -> str:
    """A localhost URL where nothing listens (relay down)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    server.server_close()
    return f"http://127.0.0.1:{port}"
