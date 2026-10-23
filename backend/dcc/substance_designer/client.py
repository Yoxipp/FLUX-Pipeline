# client.py — backend-side client for the FLUX Substance Designer bridge.
#
# Designer's `sd` module runs ONLY inside Designer, so FLUX talks to an in-app plugin
# over a local socket (newline-JSON), like Painter / Mari.

from __future__ import annotations

from typing import Any

from core.constants import DCC_PORTS
from dcc.json_bridge import send_json_line

DESIGNER_BRIDGE_HOST = "127.0.0.1"
# Base of Designer's range in DCC_PORT_RANGES: the status scan and this ping agree.
DESIGNER_BRIDGE_PORT = DCC_PORTS.get("SubstanceD", 7040)


def _send(payload: dict, timeout: float = 600.0, port: int | None = None) -> dict:
    return send_json_line(DESIGNER_BRIDGE_HOST, port or DESIGNER_BRIDGE_PORT, payload, timeout)


class SubstanceDesignerClient:
    """*port* = one instance of the range (Flows session, P6b); None = the base port."""

    def __init__(self, port: int | None = None) -> None:
        self.port = port

    def ping(self) -> dict:
        return _send({"action": "ping"}, timeout=2.0, port=self.port)

    def info(self) -> dict:
        """Open packages / graphs / outputs: {ok, packages, current}."""
        return _send({"action": "info"}, timeout=20.0, port=self.port)

    def export(self, config: dict[str, Any]) -> dict:
        """Ask Designer to export maps / .sbsar / .sbs with *config*; returns {ok, files}."""
        return _send({"action": "export", "config": config}, port=self.port)


designer_client = SubstanceDesignerClient()
