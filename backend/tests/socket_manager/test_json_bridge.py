# The shared line-JSON client of the in-app bridges (Nuke, Mari, Painter, ZBrush).

from __future__ import annotations

import socket
import threading
import unittest

from dcc.json_bridge import send_json_line


def _server(answer: bytes) -> int:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def _serve() -> None:
        conn, _ = srv.accept()
        with conn:
            conn.recv(4096)
            for i in range(0, len(answer), 5):     # answer sent in small pieces
                conn.sendall(answer[i:i + 5])
        srv.close()

    threading.Thread(target=_serve, daemon=True).start()
    return srv.getsockname()[1]


class JsonBridge(unittest.TestCase):
    def test_status_ok_becomes_ok_true(self) -> None:
        port = _server(b'{"status": "ok", "files": ["a", "b"]}\n')
        self.assertEqual(send_json_line("127.0.0.1", port, {"action": "x"}, 5.0),
                         {"status": "ok", "files": ["a", "b"], "ok": True})

    def test_nuke_answers_are_kept_as_they_are(self) -> None:
        port = _server(b'{"result": 3}\n')
        self.assertEqual(send_json_line("127.0.0.1", port, {"cmd": "run"}, 5.0, status_to_ok=False),
                         {"result": 3})

    def test_errors(self) -> None:
        self.assertEqual(send_json_line("127.0.0.1", _server(b""), {}, 5.0),
                         {"ok": False, "error": "empty response"})
        bad = send_json_line("127.0.0.1", _server(b"nope\n"), {}, 5.0, protocol_error_prefix="Protocol error: ")
        self.assertTrue(bad["error"].startswith("Protocol error: "))
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        self.assertFalse(send_json_line("127.0.0.1", port, {}, 1.0)["ok"])


if __name__ == "__main__":
    unittest.main()
