# activity_reader.py — query and update-read-status for activite.json.

from __future__ import annotations

from pathlib import Path

from core.json_manager import cached_read_json, read_json, write_json
from core.logger import get_logger
from core.paths import get_activity_path

log = get_logger(__name__)


def _load(path: Path | None = None, sig: tuple[int, int] | None = None) -> list[dict]:
    # Read-only query path → goes through the short-lived cache. Writers below
    # use write_json (uncached + cache-invalidating), so they still read fresh.
    data = cached_read_json(path or get_activity_path(), sig=sig)
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


def get_events_and_unread(
    limit: int = 50,
    user: str | None = None,
    action: str | None = None,
    project: str | None = None,
    path: Path | None = None,
    sig: tuple[int, int] | None = None,
) -> tuple[list[dict], int]:
    """Return (filtered+sorted events[:limit], total unread count) in ONE read.

    Single-pass equivalent of ``get_all_events`` + ``get_unread_count`` — avoids
    reading the shared activite.json twice per poll (see Phase 1 of the
    server-load optimisation). The unread count reflects the whole file, not the
    filtered view, matching the previous unfiltered ``get_unread_count`` call.

    *sig* (mtime_ns, size) may be passed by the router so the cache reuses the
    stat already taken for the ETag rather than issuing a second one (Phase 4).
    """
    events = _load(path, sig=sig)
    unread = sum(1 for e in events if not e.get("read", False))

    if user:
        events = [e for e in events if e.get("user") == user]
    if action:
        events = [e for e in events if e.get("action") == action]
    if project:
        events = [e for e in events if e.get("project") == project]

    events.sort(key=lambda e: (e.get("date", ""), e.get("time", "")), reverse=True)
    return events[:limit], unread


# ── mark read ─────────────────────────────────────────────────────────────────

def _load_fresh(path: Path | None = None) -> list[dict]:
    """Uncached read for read-modify-write callers (mark_*), which must not see
    a cached snapshot and must own the objects they mutate."""
    data = read_json(path or get_activity_path())
    return data if isinstance(data, list) else []


def mark_as_read(event_id: str, path: Path | None = None) -> bool:
    """Set read=True for the event with *event_id*. Returns True if found."""
    events = _load_fresh(path)
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
    events = _load_fresh(path)
    for e in events:
        e["read"] = True
    return _save(events, path)

