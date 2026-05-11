# modif_log.py — read/write per-folder modif_logs.json.

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.constants import JSON_MODIF_LOG
from core.json_manager import read_json, write_json
from core.logger import get_logger

log = get_logger(__name__)


def _now() -> tuple[str, str]:
    dt = datetime.now()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _log_path(folder_path: Path) -> Path:
    return folder_path / JSON_MODIF_LOG


def append_log(
    folder_path: Path,
    name: str,
    version: str,
    modification: str,
    user: str,
) -> bool:
    """Append one entry to modif_logs.json in *folder_path*.

    Creates the file if absent.
    Returns True on success.
    """
    date, time = _now()
    entry = {
        "name":         name,
        "date":         date,
        "time":         time,
        "version":      version,
        "modification": modification,
        "user":         user,
    }
    path = _log_path(folder_path)
    logs = read_json(path)
    if not isinstance(logs, list):
        logs = []
    logs.append(entry)
    ok = write_json(path, logs)
    if not ok:
        log.error("Failed to write modif_logs.json at %s", path)
    return ok


def read_logs(folder_path: Path) -> list[dict]:
    """Return all log entries sorted by date/time descending."""
    raw = read_json(_log_path(folder_path))
    if not isinstance(raw, list):
        return []
    return sorted(raw, key=lambda e: (e.get("date", ""), e.get("time", "")), reverse=True)


def get_logs_for_file(folder_path: Path, base_name: str) -> list[dict]:
    """Return entries where 'name' starts with *base_name*, newest first."""
    return [e for e in read_logs(folder_path) if e.get("name", "").startswith(base_name)]

