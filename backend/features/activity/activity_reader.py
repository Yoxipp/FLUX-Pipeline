# activity_reader.py — query + read-status for the append-only activity log.
#
# activite.json is an append-only JSONL log (Phase 5). Read-status lives in a
# companion set-file (see read_state), so marking read never rewrites the log.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from core.paths import get_activity_path, get_activity_read_path
from core.repository_factory import get_repository
from features.activity.read_state import is_read, load_read_ids, mark_read

log = get_logger(__name__)

# Metadata frontier (V5): the activity log goes through the repository. Addressed
# by its own path (transitional doc_id) so callers keep passing the path they
# already compute (default or test-injected).
_COLLECTION = "activity_log"


def _load(path: Path | None = None, sig: tuple[int, int] | None = None) -> list[dict]:
    # Read-only query path → cached JSONL read (legacy array auto-detected).
    return get_repository().read_log(_COLLECTION, str(path or get_activity_path()), sig=sig)


def _read_path(path: Path | None) -> Path:
    """Companion read-status file for the log at *path* (or the default log)."""
    if path is None:
        return get_activity_read_path()
    p = Path(path)
    return p.with_name(f"{p.stem}_read.json")


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
    read_ids = load_read_ids(_read_path(path))
    return [e for e in events if not is_read(e, read_ids)]


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
    reading the shared activite.json twice per poll (Phase 1). The unread count
    reflects the whole file, not the filtered view. Read-status is overlaid from
    the companion set-file (Phase 5), so returned events carry the correct
    ``read`` value without mutating the cached objects.

    *sig* (mtime_ns, size) may be passed by the router so the cache reuses the
    stat already taken for the ETag rather than issuing a second one (Phase 4).
    """
    events = _load(path, sig=sig)
    read_ids = load_read_ids(_read_path(path))
    unread = sum(1 for e in events if not is_read(e, read_ids))

    if user:
        events = [e for e in events if e.get("user") == user]
    if action:
        events = [e for e in events if e.get("action") == action]
    if project:
        events = [e for e in events if e.get("project") == project]

    events.sort(key=lambda e: (e.get("date", ""), e.get("time", "")), reverse=True)
    out = [{**e, "read": is_read(e, read_ids)} for e in events[:limit]]
    return out, unread


# ── mark read ─────────────────────────────────────────────────────────────────

def mark_as_read(event_id: str, path: Path | None = None) -> bool:
    """Mark the event with *event_id* read. Returns True if it exists in the log.

    Only the tiny companion set-file is written — the append-only log is never
    rewritten.
    """
    events = get_repository().read_log(
        _COLLECTION, str(path or get_activity_path()), fresh=True,
    )   # fresh: existence + live ids
    live_ids = {str(e.get("id", "")) for e in events}
    if event_id not in live_ids:
        return False
    return mark_read(_read_path(path), {event_id}, live_ids=live_ids)


def mark_all_as_read(path: Path | None = None) -> bool:
    """Mark every event currently in the hot log read (companion set-file only)."""
    events = get_repository().read_log(
        _COLLECTION, str(path or get_activity_path()), fresh=True,
    )
    ids = {str(e.get("id", "")) for e in events}
    return mark_read(_read_path(path), ids, live_ids=ids)
