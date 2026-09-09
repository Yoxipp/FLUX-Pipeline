# test_send_command_direct.py — Maya command transport targets the chosen port
# (multi-instance, cluster C phase 5). A threaded echo server stands in for a Maya
# commandPort so the test is deterministic and needs no running Maya.

from __future__ import annotations

import socket
import threading
import unittest

from dcc.maya import maya_connection


class _EchoPort:
    """Accept one line per connection and echo it back, tagged with the port."""

    def __init__(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(8)
        self.port: int = self._srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            data = conn.recv(4096)
            if data:
                conn.sendall(f"{self.port}:".encode() + data)

    def close(self) -> None:
        self._srv.close()


class SendCommandDirectPort(unittest.TestCase):
    def test_targets_the_given_port(self):
        srv = _EchoPort()
        self.addCleanup(srv.close)
        out = maya_connection.send_command_direct("hello", timeout=2.0, port=srv.port)
        self.assertEqual(out, f"{srv.port}:hello")

    def test_routes_to_the_selected_instance(self):
        a, b = _EchoPort(), _EchoPort()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        # Same command, two instances — the response tag proves which one answered.
        self.assertEqual(maya_connection.send_command_direct("x", timeout=2.0, port=a.port), f"{a.port}:x")
        self.assertEqual(maya_connection.send_command_direct("x", timeout=2.0, port=b.port), f"{b.port}:x")

    def test_closed_port_returns_none(self):
        srv = _EchoPort()
        port = srv.port
        srv.close()
        self.assertIsNone(maya_connection.send_command_direct("x", timeout=1.0, port=port))

    def test_default_port_is_base_commandport(self):
        # Sanity: the default keeps the historical single-instance behaviour.
        from core.constants import DCC_PORTS
        self.assertEqual(maya_connection.MAYA_PORT, DCC_PORTS["Maya"])


if __name__ == "__main__":
    unittest.main()
