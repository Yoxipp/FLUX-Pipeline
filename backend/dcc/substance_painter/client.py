# client.py — backend-side client for the FLUX Substance Painter bridge.
#
# Painter's `substance_painter` module runs ONLY inside Painter, so FLUX talks to an
# in-app plugin over a local socket (newline-JSON), like Nuke/ZBrush.

from __future__ import annotations

import json
import socket
from typing import Any

SUBSTANCE_BRIDGE_HOST = "127.0.0.1"
SUBSTANCE_BRIDGE_PORT = 9880


def _send(payload: dict, timeout: float = 120.0) -> dict:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((SUBSTANCE_BRIDGE_HOST, SUBSTANCE_BRIDGE_PORT))
            s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            line = buf.split(b"\n")[0].decode("utf-8", "replace").strip()
            result = json.loads(line) if line else {"ok": False, "error": "empty response"}
            if "ok" not in result:
                result["ok"] = result.get("status") == "ok"
            return result
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


class SubstancePainterClient:
    def ping(self) -> dict:
        return _send({"action": "ping"}, timeout=2.0)

    def export(self, config: dict[str, Any]) -> dict:
        """Ask Painter to export project textures with *config*; returns {ok, files}."""
        return _send({"action": "export", "config": config})


substance_client = SubstancePainterClient()
