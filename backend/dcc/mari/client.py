# client.py — backend-side client for the FLUX Mari bridge (socket, newline-JSON).
#
# Mari's `mari` module runs only inside Mari, so FLUX talks to an in-app plugin over
# a local socket, like Substance Painter / Nuke / ZBrush.

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

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
# gone. The export is waited for as long as Mari makes progress (a tile written, a
# channel started / done in the bridge log); after STALL_S without any, FLUX stops
# waiting and says where Mari is stuck (2026-09-26: "Mari charge a l'infini").
EXPORT_TIMEOUT_S = 4 * 3600.0
STALL_S = float(os.environ.get("FLUX_MARI_STALL_MIN", "20")) * 60.0
_POLL_S = 2.0
_busy_since: float | None = None
_export_dir: str | None = None


def _log_path() -> Path:
    return Path(tempfile.gettempdir()) / "flux_mari_bridge.log"


def _log_lines_since(started_wall: float) -> list[str]:
    """Bridge log lines written since *started_wall* (time.time())."""
    try:
        lines = _log_path().read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            stamp = time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if stamp + 1 >= started_wall:
            out.append(line[20:])
    return out


def _progress() -> str:
    """"BCOL : 3 tuile(s), fait : AO" for the running export (export dir + bridge log)."""
    if _busy_since is None:
        return ""
    started_wall = time.time() - (time.monotonic() - _busy_since)
    lines = _log_lines_since(started_wall)
    current = done = ""
    for line in lines:
        if line.startswith("Mari channel start "):
            current = line[len("Mari channel start "):].split(" (")[0]
        elif line.startswith("Mari channel ") and " s (" in line:
            done = line[len("Mari channel "):].split(":")[0]
            current = ""
    tiles = _count_files(_export_dir, current) if current else 0
    parts = []
    if current:
        parts.append(f"en cours : {current}" + (f" ({tiles} tuile(s))" if tiles else ""))
    if done:
        parts.append(f"fait : {done}")
    return ", ".join(parts)


def _count_files(folder: str | None, stem: str = "") -> int:
    if not folder:
        return 0
    try:
        return sum(1 for f in Path(folder).iterdir() if f.is_file() and (not stem or f.name.startswith(stem + ".")))
    except OSError:
        return 0


def busy_since() -> float | None:
    """time.monotonic() at which the running export started, None when idle."""
    return _busy_since


class MariClient:
    def ping(self) -> dict:
        if _busy_since is not None:
            mins = int((time.monotonic() - _busy_since) // 60)
            prog = _progress()
            return {"ok": True, "busy": True,
                    "version": f"export en cours ({mins} min)" + (f", {prog}" if prog else "")}
        return _send({"action": "ping"}, timeout=2.0)

    def info(self) -> dict:
        """Channels of Mari's current geo: {ok, geo, channels}."""
        if _busy_since is not None:
            return {"ok": False, "error": "Mari exporte en ce moment : attends la fin de l'export"}
        return _send({"action": "info"}, timeout=20.0)

    def export(self, export_path: str, file_format: str = "tif",
               channels: list[str] | None = None, formats: dict[str, str] | None = None,
               sizes: dict[str, int] | None = None) -> dict:
        """Ask Mari to export the current geo's channels (all, or *channels*); {ok, files}.
        With FLUX Export nodes in the geo, *channels* names those nodes (their map) and
        *sizes* is asked to Mari's Export Manager (FLUX resizes after anyway)."""
        global _busy_since, _export_dir
        if _busy_since is not None:
            return {"ok": False, "error": "un export Mari est deja en cours"}
        _busy_since, _export_dir = time.monotonic(), export_path
        box: dict = {}

        def run() -> None:
            box["result"] = _send({"action": "export", "export_path": export_path, "file_format": file_format,
                                   "channels": channels or [], "formats": formats or {},
                                   "sizes": sizes or {}},
                                  timeout=EXPORT_TIMEOUT_S)

        worker = threading.Thread(target=run, daemon=True)
        try:
            worker.start()
            last_mark, last_change = None, time.monotonic()
            while True:
                worker.join(_POLL_S)
                if not worker.is_alive():
                    return box.get("result") or {"ok": False, "error": "export Mari sans reponse"}
                started_wall = time.time() - (time.monotonic() - _busy_since)
                mark = (_count_files(export_path), len(_log_lines_since(started_wall)))
                if mark != last_mark:
                    last_mark, last_change = mark, time.monotonic()
                elif time.monotonic() - last_change > STALL_S:
                    prog = _progress() or "aucun channel commence"
                    return {"ok": False, "error": (
                        f"Mari n'avance plus depuis {int(STALL_S // 60)} min ({prog}) : FLUX arrete d'attendre. "
                        f"Regarde si Mari affiche une fenetre, et envoie le log {_log_path()}")}
        finally:
            _busy_since, _export_dir = None, None


mari_client = MariClient()
