# activity_reader.py — query and update-read-status for activite.json.

from __future__ import annotations

from pathlib import Path

from core.json_manager import read_json, write_json
from core.logger import get_logger
from core.paths import get_activity_path

log = get_logger(__name__)


def _load(path: Path | None = None) -> list[dict]:
    data = read_json(path or get_activity_path())
    return data if isinstance(data, list) else []


def _save(events: list[dict], path: Path | None = None) -> bool:
    ok = write_json(path or get_activity_path(), events)
    if not ok:
        log.error("Failed to write activite.json")
    return ok


# ── read ──────────────────────────────────────────────────────────────────────

def get_all_events(
    limit: int = 50,
    user: str | None = None,
    action: str | None = None,
    project: str | None = None,
    path: Path | None = None,
) -> list[dict]:
    """Return events sorted newest-first, with optional filters."""
    events = _load(path)

    if user:
        events = [e for e in events if e.get("user") == user]
    if action:
        events = [e for e in events if e.get("action") == action]
    if project:
        events = [e for e in events if e.get("project") == project]

    # sort newest first using date + time strings (lexicographic = correct for ISO format)
    events.sort(key=lambda e: (e.get("date", ""), e.get("time", "")), reverse=True)
    return events[:limit]


def get_unread_events(path: Path | None = None) -> list[dict]:
    events = _load(path)
    return [e for e in events if not e.get("read", False)]


def get_unread_count(path: Path | None = None) -> int:
    return len(get_unread_events(path))


# ── mark read ─────────────────────────────────────────────────────────────────

def mark_as_read(event_id: str, path: Path | None = None) -> bool:
    """Set read=True for the event with *event_id*. Returns True if found."""
    events = _load(path)
    found = False
    for e in events:
        if e.get("id") == event_id:
            e["read"] = True
            found = True
            break
    if found:
        return _save(events, path)
    return False


def mark_all_as_read(path: Path | None = None) -> bool:
    events = _load(path)
    for e in events:
        e["read"] = True
    return _save(events, path)

