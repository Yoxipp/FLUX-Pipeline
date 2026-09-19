# client.py — backend-side client for the FLUX Nuke bridge (socket, line-JSON).

from __future__ import annotations

from core.constants import DCC_PORTS, SOCKET_TIMEOUT_S
from core.logger import get_logger
from dcc.json_bridge import send_json_line

log = get_logger(__name__)

_PORT = DCC_PORTS.get("Nuke", 7003)


def _send(payload: dict, timeout: float = SOCKET_TIMEOUT_S) -> dict:
    return send_json_line("127.0.0.1", _PORT, payload, timeout, status_to_ok=False)


class NukeClient:
    """Talks to the FLUX bridge running inside Nuke (port from DCC_PORTS['Nuke'])."""

    def ping(self) -> dict:
        return _send({"cmd": "ping"})

    def run(self, code: str) -> dict:
        return _send({"cmd": "run", "code": code})


nuke_client = NukeClient()
