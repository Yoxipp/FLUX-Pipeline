# client.py — backend-side client for the FLUX Substance Painter bridge.
#
# Painter's `substance_painter` module runs ONLY inside Painter, so FLUX talks to an
# in-app plugin over a local socket (newline-JSON), like Nuke/ZBrush.

from __future__ import annotations

from typing import Any

from core.constants import DCC_PORTS
from dcc.json_bridge import send_json_line

SUBSTANCE_BRIDGE_HOST = "127.0.0.1"
# Canonical Painter port: the base of its assigned range in DCC_PORT_RANGES, so
# the status scan (scan_instances) and this ping hit the same port.
SUBSTANCE_BRIDGE_PORT = DCC_PORTS.get("SubstanceP", 7030)


def _send(payload: dict, timeout: float = 120.0, port: int | None = None) -> dict:
    return send_json_line(SUBSTANCE_BRIDGE_HOST, port or SUBSTANCE_BRIDGE_PORT, payload, timeout)


class SubstancePainterClient:
    """*port* = one instance of the range (Flows session, P6b); None = the base port."""

    def __init__(self, port: int | None = None) -> None:
        self.port = port
        self._at = {"port": port} if port else {}   # without a port: the exact calls of before

    def ping(self) -> dict:
        return _send({"action": "ping"}, timeout=2.0, **self._at)

    def info(self) -> dict:
        """Texture sets of the open Painter project: {ok, project, texture_sets}."""
        return _send({"action": "info"}, timeout=20.0, **self._at)

    def export(self, config: dict[str, Any]) -> dict:
        """Ask Painter to export project textures with *config*; returns {ok, files}."""
        return _send({"action": "export", "config": config}, **self._at)

    def verb(self, payload: dict, timeout: float = 600.0) -> dict:
        """Flows "bridge+" verbs (open, save, save_as, import, run; P6b step 9). The bridge
        answers "unknown action" until it is reinstalled."""
        return _send(dict(payload), timeout=timeout, **self._at)

    # Flows verbs (P6b step 9): the bridge answers "unknown action" until it is reinstalled.
    def open_project(self, path: str = "", mesh: str = "", discard: bool = False) -> dict:
        """Open a .spp, or create a project from *mesh*."""
        return _send({"action": "open", "path": path, "mesh": mesh, "discard": discard}, timeout=900.0, **self._at)

    def save(self) -> dict:
        return _send({"action": "save"}, timeout=600.0, **self._at)

    def save_as(self, path: str, copy: bool = False) -> dict:
        return _send({"action": "save_as", "path": path, "copy": copy}, timeout=600.0, **self._at)

    def import_file(self, path: str, kind: str = "resource", usage: str = "texture") -> dict:
        """kind mesh = reload the project mesh; resource = add to the project shelf."""
        return _send({"action": "import", "kind": kind, "path": path, "usage": usage}, timeout=900.0, **self._at)

    def run(self, code: str, timeout: float = 600.0) -> dict:
        """Free Python in Painter, gated by the machine secret (dcc/bridge_secret.py)."""
        from dcc.bridge_secret import get_secret

        return _send({"action": "run", "code": code, "secret": get_secret(), "timeout": timeout},
                     timeout=timeout + 10.0, **self._at)


substance_client = SubstancePainterClient()
