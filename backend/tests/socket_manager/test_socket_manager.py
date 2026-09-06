# test_socket_manager.py — instance-aware (port-keyed) socket manager (cluster C, phase 2).
#
# Pins two things: the new port-keyed API talks to a real listener and round-trips
# a command, and the legacy DCC-name API still works by resolving to the DCC's base
# port. A tiny threaded echo server stands in for a DCC command server so the tests
# are deterministic and need no real DCC.

from __future__ import annotations

import socket
import threading
import unittest
from unittest import mock

from core.socket_manager import SocketManager


class _EchoServer:
    """Accept connections on an OS-chosen free port; echo one line per connection."""

    def __init__(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(5)
        self.port: int = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return   # server closed
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            data = conn.recv(4096)
            if data:
                conn.sendall(b"echo:" + data)   # client strips the trailing newline

    def close(self) -> None:
        self._srv.close()


class PortKeyedApi(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = SocketManager()
        self.server = _EchoServer()
        self.addCleanup(self.server.close)

    def test_connect_send_disconnect_roundtrip(self):
        port = self.server.port
        self.assertTrue(self.mgr.connect_port(port))
        self.assertTrue(self.mgr.is_port_connected(port))
        self.assertEqual(self.mgr.send_command_port(port, "hello"), "echo:hello")
        self.mgr.disconnect_port(port)
        self.assertFalse(self.mgr.is_port_connected(port))

    def test_connect_refused_on_closed_port(self):
        self.server.close()
        # A brief wait-free retry: the port is closed, connect must report failure.
        self.assertFalse(self.mgr.connect_port(self.server.port))
        self.assertFalse(self.mgr.is_port_connected(self.server.port))

    def test_send_safe_reconnects_known_port(self):
        port = self.server.port
        self.assertTrue(self.mgr.connect_port(port))     # marks the port "known"
        self.mgr.disconnect_port(port)                   # drop the live socket
        # safe variant must transparently reconnect a known port and still deliver.
        self.assertEqual(self.mgr.send_command_port_safe(port, "again"), "echo:again")

    def test_distinct_ports_are_independent(self):
        server2 = _EchoServer()
        self.addCleanup(server2.close)
        self.assertTrue(self.mgr.connect_port(self.server.port))
        self.assertTrue(self.mgr.connect_port(server2.port))
        self.mgr.disconnect_port(self.server.port)
        # Closing one instance must not disturb the other.
        self.assertFalse(self.mgr.is_port_connected(self.server.port))
        self.assertTrue(self.mgr.is_port_connected(server2.port))


class LegacyDccNameApi(unittest.TestCase):
    """DCC-name methods resolve to the base port and keep working unchanged."""

    def setUp(self) -> None:
        self.mgr = SocketManager()
        self.server = _EchoServer()
        self.addCleanup(self.server.close)

    def test_name_api_resolves_to_base_port(self):
        # Map a fake DCC to the echo server's port (patched in the module namespace
        # the manager actually reads) and drive it through the DCC-name API.
        with mock.patch.dict("core.socket_manager.DCC_PORTS", {"Maya": self.server.port}, clear=False):
            self.assertTrue(self.mgr.connect("Maya"))
            self.assertTrue(self.mgr.is_connected("Maya"))
            self.assertEqual(self.mgr.send_command_safe("Maya", "x"), "echo:x")
            self.mgr.disconnect("Maya")
            self.assertFalse(self.mgr.is_connected("Maya"))

    def test_unknown_dcc_name_is_safe(self):
        self.assertFalse(self.mgr.connect("Blender"))
        self.assertFalse(self.mgr.is_connected("Blender"))
        self.assertIsNone(self.mgr.send_command_safe("Blender", "x"))

    def test_known_dccs_reverse_maps_ports(self):
        port = self.server.port
        with mock.patch("core.socket_manager.dcc_for_port", side_effect=lambda p: "Maya" if p == port else None):
            self.mgr.connect_port(port)
            self.assertEqual(self.mgr.known_dccs(), {"Maya"})


if __name__ == "__main__":
    unittest.main()
