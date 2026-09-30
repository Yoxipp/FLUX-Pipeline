# modif_log.py — read/write per-folder modif_logs.json.

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.logger import get_logger
from core.repository_factory import get_repository

log = get_logger(__name__)

# Metadata frontier (V5): the per-folder modif log goes through the repository
# instead of json_manager directly. The document is the JSON array itself,
# addressed by its folder (the resolver appends the file name).
_COLLECTION = "modif_log"


def _now() -> tuple[str, str]:
    dt = datetime.now()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


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
    doc_id = str(folder_path)
    logs = get_repository().get(_COLLECTION, doc_id)
    if not isinstance(logs, list):
        logs = []
    logs.append(entry)
    ok = get_repository().set(_COLLECTION, doc_id, logs)
    if not ok:
        log.error("Failed to write modif_logs.json for %s", folder_path)
    return ok


def read_logs(folder_path: Path) -> list[dict]:
    """Return all log entries sorted by date/time descending."""
    raw = get_repository().get(_COLLECTION, str(folder_path))
    if not isinstance(raw, list):
        return []
    return sorted(raw, key=lambda e: (e.get("date", ""), e.get("time", "")), reverse=True)


def get_logs_for_file(folder_path: Path, base_name: str) -> list[dict]:
    """Return entries where 'name' starts with *base_name*, newest first."""
    return [e for e in read_logs(folder_path) if e.get("name", "").startswith(base_name)]

