# _fake_bridges.py — fake DCC bridges on free local ports (P6a tests): they speak the
# protocols of the real ones, NOT the software. A test never validates a DCC.
#
#   FakeTcpJson   one JSON line in, one JSON line out (Nuke / Mari / Painter / ZBrush)
#   FakeHttp      Houdini style: GET /ping, GET /state, POST /run {"code"}
#   FakeCommandPort  Maya style: one line of Python in, a text answer out

from __future__ import annotations

import json
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Server:
    server: Any

    def start(self) -> "_Server":
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()


class FakeTcpJson(_Server):
    def __init__(self, handler: Callable[[Dict[str, Any]], Any]) -> None:
        self.requests: List[Dict[str, Any]] = []
        outer = self

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                line = self.rfile.readline()
                req = json.loads(line.decode("utf-8"))
                outer.requests.append(req)
                resp = handler(req)
                if resp is None:       # never answer (timeout tests)
                    return
                self.wfile.write((resp if isinstance(resp, str) else json.dumps(resp)).encode("utf-8") + b"\n")

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True


class FakeCommandPort(_Server):
    def __init__(self, handler: Callable[[str], str]) -> None:
        self.commands: List[str] = []
        outer = self

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                cmd = self.rfile.readline().decode("utf-8").rstrip("\n")
                outer.commands.append(cmd)
                self.wfile.write((handler(cmd) or "").encode("utf-8") + b"\x00")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True


class FakeHttp(_Server):
    """Houdini style bridge: ``run_handler(code) -> result`` (an exception = ok False)."""

    def __init__(self, run_handler: Callable[[str], Any] = lambda code: None, *, version: str = "20.5.410",
                 state: Dict[str, Any] = None) -> None:
        self.codes: List[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, data):
                body = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/ping":
                    self._send({"ok": True, "version": version, "flux": True})
                elif self.path == "/state":
                    self._send(state or {"hip_file": "/p/a.hip", "selected_nodes": []})
                else:
                    self._send({"ok": False, "error": "unknown"})

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                code = data.get("code", "")
                outer.codes.append(code)
                try:
                    self._send({"ok": True, "result": run_handler(code)})
                except Exception as exc:  # noqa: BLE001
                    self._send({"ok": False, "error": str(exc)})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
