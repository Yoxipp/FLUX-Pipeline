# client.py — backend-side client for the FLUX Mari bridge (socket, newline-JSON).
#
# Mari's `mari` module runs only inside Mari, so FLUX talks to an in-app plugin over
# a local socket, like Substance Painter / Nuke / ZBrush.

from __future__ import annotations

from typing import Any

from core.constants import DCC_PORTS
from dcc.json_bridge import send_json_line

MARI_BRIDGE_HOST = "127.0.0.1"
# Canonical Mari port: the base of its assigned range in DCC_PORT_RANGES, so the
# status scan (scan_instances) and this ping hit the same port.
MARI_BRIDGE_PORT = DCC_PORTS.get("Mari", 7070)


def _send(payload: dict, timeout: float = 120.0) -> dict:
    return send_json_line(MARI_BRIDGE_HOST, MARI_BRIDGE_PORT, payload, timeout)


# A big UDIM export freezes Mari for minutes (2026-09-26): its bridge cannot answer
# the status ping meanwhile. While FLUX waits on an export, Mari is reported busy, not
# gone, and the export itself waits long (the old 120 s gave up while Mari still wrote).
EXPORT_TIMEOUT_S = 4 * 3600.0
_busy_since: float | None = None


def _last_channel_done() -> str:
    """Last channel the bridge finished during this export (its log, %TEMP%)."""
    import tempfile
    import time
    from pathlib import Path

    log_path = Path(tempfile.gettempdir()) / "flux_mari_bridge.log"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
    except OSError:
        return ""
    started = time.time() - (time.monotonic() - (_busy_since or time.monotonic()))
    for line in reversed(lines):
        if "Mari channel " not in line:
            continue
        try:
            stamp = time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if stamp + 1 < started:
            return ""
        return line[20:].replace("Mari channel ", "")
    return ""


def busy_since() -> float | None:
    """time.monotonic() at which the running export started, None when idle."""
    return _busy_since


class MariClient:
    def ping(self) -> dict:
        if _busy_since is not None:
            import time
            mins = int((time.monotonic() - _busy_since) // 60)
            last = _last_channel_done()
            return {"ok": True, "busy": True,
                    "version": f"export en cours ({mins} min)" + (f", fait : {last}" if last else "")}
        return _send({"action": "ping"}, timeout=2.0)

    def info(self) -> dict:
        """Channels of Mari's current geo: {ok, geo, channels}."""
        if _busy_since is not None:
            return {"ok": False, "error": "Mari exporte en ce moment : attends la fin de l'export"}
        return _send({"action": "info"}, timeout=20.0)

    def export(self, export_path: str, file_format: str = "tif",
               channels: list[str] | None = None) -> dict:
        """Ask Mari to export the current geo's channels (all, or *channels*); {ok, files}."""
        global _busy_since
        import time
        if _busy_since is not None:
            return {"ok": False, "error": "un export Mari est deja en cours"}
        _busy_since = time.monotonic()
        try:
            return _send({"action": "export", "export_path": export_path, "file_format": file_format,
                          "channels": channels or []}, timeout=EXPORT_TIMEOUT_S)
        finally:
            _busy_since = None


mari_client = MariClient()
