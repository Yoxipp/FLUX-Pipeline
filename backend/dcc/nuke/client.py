# client.py — backend-side client for the FLUX Nuke bridge (socket, line-JSON).

from __future__ import annotations

import json
import socket

from core.constants import DCC_PORTS, SOCKET_TIMEOUT_S
from core.logger import get_logger

log = get_logger(__name__)

_PORT = DCC_PORTS.get("Nuke", 7003)


def _send(payload: dict, timeout: float = SOCKET_TIMEOUT_S) -> dict:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(("127.0.0.1", _PORT))
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n")[0].decode("utf-8", "replace").strip()
        return json.loads(line) if line else {"ok": False, "error": "empty response"}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            sock.close()
        except OSError:
            pass


class NukeClient:
    """Talks to the FLUX bridge running inside Nuke (port from DCC_PORTS['Nuke'])."""

    def ping(self) -> dict:
        return _send({"cmd": "ping"})

    def run(self, code: str) -> dict:
        return _send({"cmd": "run", "code": code})


nuke_client = NukeClient()
