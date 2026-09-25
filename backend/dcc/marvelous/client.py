# client.py — backend-side client for the FLUX Marvelous Designer bridge.
#
# Marvelous' Python API (export_api...) runs ONLY inside Marvelous, so FLUX talks to
# the bridge script over a local socket (newline-JSON), like Painter / Designer.

from __future__ import annotations

from typing import Any

from core.constants import DCC_PORTS
from dcc.json_bridge import send_json_line

MARVELOUS_BRIDGE_HOST = "127.0.0.1"
# Base of Marvelous' range in DCC_PORT_RANGES: the status scan and this ping agree.
MARVELOUS_BRIDGE_PORT = DCC_PORTS.get("Marvelous", 7050)


def _send(payload: dict, timeout: float = 900.0) -> dict:
    return send_json_line(MARVELOUS_BRIDGE_HOST, MARVELOUS_BRIDGE_PORT, payload, timeout)


class MarvelousClient:
    def ping(self) -> dict:
        return _send({"action": "ping"}, timeout=2.0)

    def info(self) -> dict:
        """Open project + formats this Marvelous can export: {ok, project, formats}."""
        return _send({"action": "info"}, timeout=20.0)

    def export(self, config: dict[str, Any]) -> dict:
        """Ask Marvelous to export with *config*; returns {ok, files, warnings}."""
        return _send({"action": "export", "config": config})


marvelous_client = MarvelousClient()
