# socket_manager.py — singleton managing all DCC TCP connections.
#
# Each DCC listens on a local port (constants.DCC_PORTS). We maintain one
# persistent socket per DCC and expose send_command() for any module that
# needs to talk to a DCC (publisher, importer, DCC bridges).

from __future__ import annotations

import socket
import threading

from core.constants import DCC_PORTS, SOCKET_TIMEOUT_S
from core.logger import get_logger

log = get_logger(__name__)

_BUFFER_SIZE = 4096


class SocketManager:
    """Singleton — use the module-level `socket_manager` instance."""

    def __init__(self) -> None:
        self._socks: dict[str, socket.socket | None] = {}
        self._connected: dict[str, bool] = {}
        self._known: set[str] = set()  # DCCs explicitly connected at least once
        self._lock = threading.Lock()

    # ── public ────────────────────────────────────────────────────────────────

    def connect(self, dcc_name: str) -> bool:
        """Open a TCP connection to *dcc_name*. Returns True on success."""
        port = DCC_PORTS.get(dcc_name)
        if port is None:
            log.warning("connect: unknown DCC '%s'", dcc_name)
            return False

        with self._lock:
            self._close_socket(dcc_name)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(SOCKET_TIMEOUT_S)
                sock.connect(("127.0.0.1", port))
                self._socks[dcc_name] = sock
                self._known.add(dcc_name)
                self._connected[dcc_name] = True
            except OSError:
                self._socks[dcc_name] = None
                self._connected[dcc_name] = False
                log.debug("Cannot connect to %s (port %d)", dcc_name, port)

        return self._connected[dcc_name]

    def disconnect(self, dcc_name: str) -> None:
        """Close the connection to *dcc_name*."""
        with self._lock:
            self._close_socket(dcc_name)
            self._connected[dcc_name] = False

    def is_connected(self, dcc_name: str) -> bool:
        """Return cached connection state (no I/O)."""
        return self._connected.get(dcc_name, False)

    def probe(self, dcc_name: str) -> bool:
        """Verify reachability via a quick TCP handshake (does not touch open socket)."""
        port = DCC_PORTS.get(dcc_name)
        if port is None:
            return False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(SOCKET_TIMEOUT_S)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            return False

    def probe_port(self, port: int, timeout: float = 0.5) -> bool:
        """Probe a raw port number (used by FastAPI DCC router)."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            return False

    def known_dccs(self) -> set[str]:
        """Return the set of DCCs that have been explicitly connected at least once."""
        return set(self._known)

    def send_command(self, dcc_name: str, command: str) -> str | None:
        """Send *command* to *dcc_name* and return the response string, or None on error."""
        with self._lock:
            sock = self._socks.get(dcc_name)
            if sock is None:
                return None
            try:
                sock.sendall((command + "\n").encode("utf-8"))
                response = sock.recv(_BUFFER_SIZE).decode("utf-8", errors="replace").strip()
                return response
            except OSError as e:
                log.warning("send_command failed for %s: %s", dcc_name, e)
                self._socks[dcc_name] = None
                self._connected[dcc_name] = False
                return None

    def send_command_safe(self, dcc_name: str, command: str) -> str | None:
        """Send command with one automatic reconnect on failure."""
        result = self.send_command(dcc_name, command)
        if result is None and dcc_name in self._known:
            log.debug("send_command_safe: retrying connection to %s", dcc_name)
            if self.connect(dcc_name):
                result = self.send_command(dcc_name, command)
        return result

    # ── private ───────────────────────────────────────────────────────────────

    def _close_socket(self, dcc_name: str) -> None:
        sock = self._socks.pop(dcc_name, None)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


# Module-level singleton — import and use directly
socket_manager = SocketManager()
