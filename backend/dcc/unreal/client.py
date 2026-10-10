# client.py — backend-side client for the FLUX Unreal bridge (socket, newline-JSON).
#
# The `unreal` module runs only inside the editor, so FLUX talks to the bridge plugin of
# the host project (dcc/unreal/unreal_bridge.py), like Mari / Painter / Nuke.

from __future__ import annotations

from core.constants import DCC_PORTS
from dcc.json_bridge import send_json_line

UNREAL_BRIDGE_HOST = "127.0.0.1"
# Canonical Unreal port: the base of its range in DCC_PORT_RANGES (status scan + ping).
UNREAL_BRIDGE_PORT = DCC_PORTS.get("Unreal", 7080)


def _send(payload: dict, timeout: float, port: int | None = None) -> dict:
    return send_json_line(UNREAL_BRIDGE_HOST, port or UNREAL_BRIDGE_PORT, payload, timeout)


class UnrealClient:
    def ping(self, port: int | None = None) -> dict:
        return _send({"action": "ping"}, timeout=2.0, port=port)

    def info(self, port: int | None = None) -> dict:
        return _send({"action": "info"}, timeout=10.0, port=port)

    def open_stage(self, path: str, purpose: str = "proxy", port: int | None = None) -> dict:
        """Point the FLUX stage actor at *path* (a shot stage); the editor freezes while it loads."""
        return _send({"action": "open_stage", "path": path, "purpose": purpose}, timeout=600.0, port=port)

    def reload(self, port: int | None = None) -> dict:
        """Re-read the stage layers changed on disk (after a Houdini save / publish)."""
        return _send({"action": "reload"}, timeout=600.0, port=port)

    def live(self, path: str, port: int | None = None) -> dict:
        """Houdini live push: open *path* the first time, then reload what changed."""
        return _send({"action": "live", "path": path}, timeout=600.0, port=port)


unreal_client = UnrealClient()
