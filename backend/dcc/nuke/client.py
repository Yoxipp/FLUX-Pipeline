# client.py — backend-side client for the FLUX Nuke bridge (socket, line-JSON).

from __future__ import annotations

from core.constants import DCC_PORTS, SOCKET_TIMEOUT_S
from core.logger import get_logger
from dcc.json_bridge import send_json_line

log = get_logger(__name__)

_PORT = DCC_PORTS.get("Nuke", 7003)


def _send(payload: dict, timeout: float = SOCKET_TIMEOUT_S, port: int | None = None) -> dict:
    return send_json_line("127.0.0.1", port or _PORT, payload, timeout, status_to_ok=False)


class NukeClient:
    """Talks to the FLUX bridge running inside Nuke. *port* = one instance of the range
    (Flows session, P6b); None = the base port DCC_PORTS['Nuke'] (every existing caller)."""

    def __init__(self, port: int | None = None) -> None:
        self.port = port
        self._at = {"port": port} if port else {}   # without a port: the exact calls of before

    def ping(self) -> dict:
        return _send({"cmd": "ping"}, **self._at)

    def run(self, code: str, timeout: float = SOCKET_TIMEOUT_S) -> dict:
        return _send({"cmd": "run", "code": code}, timeout, **self._at)


nuke_client = NukeClient()
