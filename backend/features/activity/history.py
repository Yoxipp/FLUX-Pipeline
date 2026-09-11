# history.py — hot-file rotation + cold-archive reads for the activity/mentions
# feeds (Phase 3 of the server-load optimisation).
#
# The polled files (activite.json, chatMentions.json) must stay bounded so their
# weight never drifts. On append, once a file exceeds MAX+SLACK entries we keep
# the newest MAX (dropping anything older than MAX_DAYS at the same time) and
# move the surplus into monthly archives under CONFIG/archive/, grouped by each
# event's own month. The polling feed never touches those archives; they are
# read only on demand via read_archive_events (the /activity/history endpoint).
#
# NOTE (concurrency): this still uses read-modify-write via write_json, so two
# instances rotating at the same instant can lose the loser's just-appended
# events — the pre-existing multi-writer hazard. Phase 5 replaces the append with
# an atomic O_APPEND JSONL write that removes it. Until then rotation is
# best-effort and logged; the archive write itself is independent and additive.

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from core.constants import (
    HOT_HISTORY_MAX_DAYS,
    HOT_HISTORY_MAX_EVENTS,
    HOT_HISTORY_ROTATE_SLACK,
)
from core.logger import get_logger
from core.paths import get_archive_dir, get_archive_path
from core.repository_factory import get_repository

log = get_logger(__name__)

# Cold archives are plain JSON-array documents, keyed by their own path (the
# monthly file under CONFIG/archive/). One collection for every feed's archives.
_ARCHIVE_COLLECTION = "feed_archive"


def _sort_key(e: dict) -> tuple[str, str]:
    return (e.get("date", ""), e.get("time", ""))


def append_events(
    path: Path,
    new_entries: list[dict],
    archive_stem: str,
    collection: str,
    *,
    max_events: int = HOT_HISTORY_MAX_EVENTS,
    max_days: int = HOT_HISTORY_MAX_DAYS,
    slack: int = HOT_HISTORY_ROTATE_SLACK,
) -> bool:
    """Append *new_entries* to the JSONL hot log, rotating if too big.

    *collection* is the feed's repository collection ("activity_log" /
    "mentions_log"); *path* is its log file (the transitional doc_id).

    The append itself is an atomic O_APPEND single write (race-free across
    instances). Only when the log then exceeds ``max_events + slack`` is a
    rotation done: the surplus (events beyond the newest ``max_events`` *or*
    older than ``max_days``) is moved into monthly archives and the hot file is
    rewritten with the trimmed tail. The rewrite is an occasional read-modify-
    write; a rotation racing a concurrent append can drop the just-appended
    event of the loser — rare, best-effort, logged. Returns the append result.
    """
    repo = get_repository()
    doc_id = str(path)
    if not repo.append_log(collection, doc_id, list(new_entries)):
        return False

    try:
        # Rotation reads + rewrites the hot log, so hold the log transaction to
        # stay atomic w.r.t. concurrent appends/rotations (no event dropped).
        with repo.log_transaction(collection, doc_id):
            events = repo.read_log(collection, doc_id, fresh=True)
            if len(events) > max_events + slack:
                hot, cold = _split(events, max_events, max_days)
                if cold:
                    _archive(archive_stem, cold)
                repo.replace_log(collection, doc_id, hot)
    except Exception as exc:  # never let a rotation hiccup surface as an append failure
        log.warning("History rotation for %s skipped: %s", archive_stem, exc)

    return True


def _split(events: list[dict], max_events: int, max_days: int) -> tuple[list[dict], list[dict]]:
    """Partition *events* into (hot, cold).

    hot  = the newest ``max_events`` that are also within ``max_days``.
    cold = everything else (older-than-window, or beyond the count cap).
    """
    events.sort(key=_sort_key)
    head, tail = events[:-max_events], events[-max_events:]   # head = beyond count cap
    cutoff = (datetime.now() - timedelta(days=max_days)).strftime("%Y-%m-%d")
    hot  = [e for e in tail if e.get("date", "") >= cutoff]
    aged = [e for e in tail if e.get("date", "") < cutoff]
    return hot, head + aged


def _archive(archive_stem: str, cold: list[dict]) -> None:
    """Append *cold* events to monthly archive files, grouped by event month."""
    get_archive_dir().mkdir(parents=True, exist_ok=True)
    by_month: dict[str, list[dict]] = {}
    for e in cold:
        # YYYY-MM from the event date; undated events land in an 'unknown' bucket.
        d = str(e.get("date", ""))
        yyyymm = d[:7].replace("-", "") if len(d) >= 7 else "000000"
        by_month.setdefault(yyyymm, []).append(e)

    repo = get_repository()
    for yyyymm, batch in by_month.items():
        apath = str(get_archive_path(archive_stem, yyyymm))
        existing = repo.get(_ARCHIVE_COLLECTION, apath)
        merged = (existing if isinstance(existing, list) else []) + batch
        if not repo.set(_ARCHIVE_COLLECTION, apath, merged):
            log.error("Failed to write archive %s (%d events may be unarchived)", apath, len(batch))


def read_archive_events(archive_stem: str, limit: int = 200, offset: int = 0) -> tuple[list[dict], bool]:
    """Return (events newest-first, has_more) from the cold archives on demand.

    Reads only as many newest-month archive files as needed to satisfy
    ``offset + limit`` — this is the ad-hoc "load older history" path, never the
    polling feed.
    """
    try:
        adir = get_archive_dir()
    except RuntimeError:
        return [], False
    if not adir.exists():
        return [], False

    files = sorted(adir.glob(f"{archive_stem}_*.json"), reverse=True)  # newest month first
    need = offset + limit
    repo = get_repository()
    collected: list[dict] = []
    for f in files:
        data = repo.get(_ARCHIVE_COLLECTION, str(f))
        evs = data if isinstance(data, list) else []
        evs.sort(key=_sort_key, reverse=True)
        collected.extend(evs)
        if len(collected) >= need + 1:   # +1 so we can report has_more
            break

    page = collected[offset:offset + limit]
    has_more = len(collected) > offset + limit
    return page, has_more
