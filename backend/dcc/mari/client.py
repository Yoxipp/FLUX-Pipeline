# client.py — backend-side client for the FLUX Mari bridge (socket, newline-JSON).
#
# Mari's `mari` module runs only inside Mari, so FLUX talks to an in-app plugin over
# a local socket, like Substance Painter / Nuke / ZBrush.

from __future__ import annotations

import json
import socket
from typing import Any

MARI_BRIDGE_HOST = "127.0.0.1"
MARI_BRIDGE_PORT = 9881


def _send(payload: dict, timeout: float = 120.0) -> dict:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((MARI_BRIDGE_HOST, MARI_BRIDGE_PORT))
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


class MariClient:
    def ping(self) -> dict:
        return _send({"action": "ping"}, timeout=2.0)

    def export(self, export_path: str, file_format: str = "tif") -> dict:
        """Ask Mari to export the current geo's channels; returns {ok, files}."""
        return _send({"action": "export", "export_path": export_path, "file_format": file_format})


mari_client = MariClient()
