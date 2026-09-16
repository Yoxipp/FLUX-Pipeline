"""
FLUX — ZBrush TCP socket client.
Communicates with the FLUX bridge plugin running inside ZBrush (port 9876).

Protocol: newline-delimited JSON over TCP.
  send: {"action": "ping", ...}  + newline
  recv: {"status": "ok", ...}    + newline

Usage:
    from dcc.zbrush.client import zbrush_client
    if zbrush_client.ping().get("ok"):
        zbrush_client.export_obj("C:/out/mesh.obj", {})
"""

from __future__ import annotations

import json
import socket
from typing import Any

from core.constants import CONNECT_TIMEOUT_S

ZBRUSH_BRIDGE_PORT = 9876
ZBRUSH_BRIDGE_HOST = "127.0.0.1"


class ZBrushClient:
    """Sync TCP socket client for the FLUX ZBrush bridge plugin."""

    def __init__(self, host: str = ZBRUSH_BRIDGE_HOST, port: int = ZBRUSH_BRIDGE_PORT) -> None:
        self.host = host
        self.port = port

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def ping(self) -> dict:
        """Alive check. Returns {"ok": True, "version": "ZBrush 2026"} or {"error": ...}."""
        return self._send({"action": "ping"}, timeout=2.0)

    def is_connected(self) -> bool:
        return self.ping().get("ok", False) is True

    # ------------------------------------------------------------------
    # Mesh info
    # ------------------------------------------------------------------

    def get_mesh_info(self) -> dict:
        """Return basic mesh metadata (point/poly count) from the active tool."""
        return self._send({"action": "get_mesh_info"})

    # ------------------------------------------------------------------
    # Export actions
    # ------------------------------------------------------------------

    def export_ztl(self, path: str) -> dict:
        """Save active tool as ZTL to *path*."""
        return self._send({"action": "export_ztl", "path": path})

    def export_obj(self, path: str, options: dict[str, Any] | None = None) -> dict:
        """Export active tool as OBJ to *path* with optional export options."""
        return self._send({"action": "export_obj", "path": path, "options": options or {}})

    def export_fbx(self, path: str, options: dict[str, Any] | None = None) -> dict:
        """Export active tool as FBX to *path* with optional export options."""
        return self._send({"action": "export_fbx", "path": path, "options": options or {}})

    def stop(self) -> dict:
        """Send stop command to release ZBrush from the freeze loop."""
        return self._send({"action": "stop"})

    def cancel(self) -> dict:
        """Send cancel command — same effect as stop but with a shorter timeout.
        Used for user-initiated cancels so the UI doesn't hang if ZBrush isn't frozen."""
        return self._send({"action": "cancel"}, timeout=3.0)

    def release(self, timeout: float = 3.0) -> dict:
        """Force-release ZBrush from the freeze loop by sending 'stop'.

        Used by the user-initiated cancel and by the app-close release hook. Sends
        'stop' (breaks the freeze immediately) with a short timeout so the caller
        never hangs when ZBrush is closed or not frozen (the bridge acks stop when
        idle). Idempotent: safe to call repeatedly."""
        return self._send({"action": "stop"}, timeout=timeout)

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------

    def _send(self, payload: dict, timeout: float = 10.0) -> dict:
        """Send a JSON command and receive the JSON response (newline-framed)."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(min(timeout, CONNECT_TIMEOUT_S))
                s.connect((self.host, self.port))
                s.settimeout(timeout)
                s.sendall((json.dumps(payload) + "\n").encode("utf-8"))

                # Read until newline (response may be chunked)
                buf = b""
                while b"\n" not in buf:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk

                line = buf.split(b"\n")[0]
                result = json.loads(line.decode("utf-8"))

                # Normalise: bridge returns {"status": "ok"}, expose as {"ok": True}
                if "ok" not in result:
                    result["ok"] = result.get("status") == "ok"
                return result

        except (ConnectionRefusedError, socket.timeout, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        except (json.JSONDecodeError, Exception) as exc:
            return {"ok": False, "error": f"Protocol error: {exc}"}


# Module-level singleton
zbrush_client = ZBrushClient()
