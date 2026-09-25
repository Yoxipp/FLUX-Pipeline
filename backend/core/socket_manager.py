# socket_manager.py — singleton managing all DCC TCP connections.
#
# Multi-instance model (cluster C): connections are keyed by PORT, not by DCC
# name, so several instances of the same DCC (each on its own port in the DCC's
# range) can be held at once. The legacy DCC-name API (connect("Maya"), ...) is
# kept as thin wrappers that resolve a DCC to its BASE port — i.e. the historical
# single-instance behaviour — while the instance-aware callers pass an explicit
# port (connect_port(7002), send_command_port(7002, cmd), ...).

from __future__ import annotations

import socket
import threading

from core.constants import DCC_PORTS, SOCKET_TIMEOUT_S, dcc_for_port
from core.logger import get_logger

log = get_logger(__name__)

_BUFFER_SIZE = 4096


class SocketManager:
    """Singleton — use the module-level `socket_manager` instance."""

    def __init__(self) -> None:
        # Keyed by port so distinct instances of one DCC never share a slot.
        self._socks: dict[int, socket.socket | None] = {}
        self._connected: dict[int, bool] = {}
        self._known: set[int] = set()  # ports explicitly connected at least once
        self._lock = threading.Lock()

    # ── DCC-name API (back-compat: resolves to the DCC's base port) ─────────────

    def connect(self, dcc_name: str) -> bool:
        """Open a connection to *dcc_name*'s base (legacy single-instance) port."""
        port = DCC_PORTS.get(dcc_name)
        if port is None:
            log.warning("connect: unknown DCC '%s'", dcc_name)
            return False
        return self.connect_port(port)

    def disconnect(self, dcc_name: str) -> None:
        port = DCC_PORTS.get(dcc_name)
        if port is not None:
            self.disconnect_port(port)

    def is_connected(self, dcc_name: str) -> bool:
        """Cached connection state for the DCC's base port (no I/O)."""
        port = DCC_PORTS.get(dcc_name)
        return self.is_port_connected(port) if port is not None else False

    def probe(self, dcc_name: str) -> bool:
        """Reachability handshake against the DCC's base port."""
        port = DCC_PORTS.get(dcc_name)
        return self.probe_port(port) if port is not None else False

    def send_command(self, dcc_name: str, command: str) -> str | None:
        port = DCC_PORTS.get(dcc_name)
        return self.send_command_port(port, command) if port is not None else None

    def send_command_safe(self, dcc_name: str, command: str) -> str | None:
        port = DCC_PORTS.get(dcc_name)
        return self.send_command_port_safe(port, command) if port is not None else None

    def known_dccs(self) -> set[str]:
        """DCC names with at least one known (ever-connected) instance port."""
        return {dcc for port in self._known if (dcc := dcc_for_port(port)) is not None}

    # ── Instance-aware API (keyed by port) ──────────────────────────────────────

    def connect_port(self, port: int) -> bool:
        """Open a TCP connection to a specific instance *port*. True on success."""
        with self._lock:
            self._close_socket(port)
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(SOCKET_TIMEOUT_S)
                sock.connect(("127.0.0.1", port))
                self._socks[port] = sock
                self._known.add(port)
                self._connected[port] = True
            except OSError:
                # Close the half-open socket so a failed connect never leaks an fd.
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                self._socks[port] = None
                self._connected[port] = False
                log.debug("Cannot connect to port %d", port)

        return self._connected[port]

    def disconnect_port(self, port: int) -> None:
        """Close the connection to a specific instance *port*."""
        with self._lock:
            self._close_socket(port)
            self._connected[port] = False

    def is_port_connected(self, port: int) -> bool:
        """Return cached connection state for *port* (no I/O)."""
        return self._connected.get(port, False)

    def probe_port(self, port: int, timeout: float = 0.5) -> bool:
        """Probe a raw port number via a quick TCP handshake (no state touched)."""
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass

    def send_command_port(self, port: int, command: str) -> str | None:
        """Send *command* to the instance on *port*; return the response or None."""
        with self._lock:
            sock = self._socks.get(port)
            if sock is None:
                return None
            try:
                sock.sendall((command + "\n").encode("utf-8"))
                return _recv_response(sock).decode("utf-8", errors="replace").strip()
            except OSError as e:
                log.warning("send_command failed for port %d: %s", port, e)
                self._socks[port] = None
                self._connected[port] = False
                return None

    def send_command_port_safe(self, port: int, command: str) -> str | None:
        """Send with one automatic reconnect on failure (only for known ports)."""
        result = self.send_command_port(port, command)
        if result is None and port in self._known:
            log.debug("send_command_safe: retrying connection to port %d", port)
            if self.connect_port(port):
                result = self.send_command_port(port, command)
        return result

    # ── private ───────────────────────────────────────────────────────────────

    def _close_socket(self, port: int) -> None:
        sock = self._socks.pop(port, None)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


_IDLE_S = 0.3   # silence that ends a response with no delimiter
_DELIMITERS = (b"\n", b"\x00")   # FLUX bridges end a reply with a newline, Maya with a NUL


def _recv_response(sock: socket.socket) -> bytes:
    """One whole response: read until it ends with a delimiter, the DCC goes quiet
    (_IDLE_S) or closes. A single recv(4096) used to cut long or split answers."""
    chunks = [sock.recv(_BUFFER_SIZE)]
    if not chunks[0] or chunks[0].endswith(_DELIMITERS):
        return chunks[0]
    previous = sock.gettimeout()
    sock.settimeout(_IDLE_S)
    try:
        while True:
            try:
                more = sock.recv(_BUFFER_SIZE)
            except socket.timeout:
                break
            if not more:
                break
            chunks.append(more)
            if more.endswith(_DELIMITERS):
                break
    finally:
        sock.settimeout(previous)
    return b"".join(chunks)


# Module-level singleton — import and use directly
socket_manager = SocketManager()
