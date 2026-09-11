# read_state.py — read/unread status for the append-only feeds (Phase 5).
#
# The activity/mentions logs are append-only JSONL, so a per-entry "read" flag
# can no longer be flipped in place without rewriting the whole file. Instead
# each feed has a small companion file holding the SET of read entry ids:
#
#     {"read_ids": ["<id>", ...]}
#
# An entry counts as read when its own inline `read` is true (covers pre-Phase-5
# events already marked in the legacy array) OR its id is in that set. Marking
# read only rewrites this tiny set-file, never the log. The set is pruned to the
# hot log's live ids on each mark, so it stays bounded by the rotation cap.
#
# Concurrency: the set-file is a small, rarely-written read-modify-write (a user
# clicking "mark read"), so a simultaneous double-mark could drop one add and
# leave an entry unread — harmless and re-markable, and unrelated to the
# high-frequency event log which is now race-free append-only.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from core.repository_factory import get_repository

log = get_logger(__name__)

# Metadata frontier (V5): read-status goes through the repository instead of
# json_manager directly. The companion set-file is addressed by its own path
# (transitional doc_id) so callers keep passing the path they already compute.
_COLLECTION = "read_state"


def load_read_ids(path: Path) -> set[str]:
    """Return the set of read entry ids from the companion file (cached)."""
    data = get_repository().get(_COLLECTION, str(path))
    if isinstance(data, dict):
        ids = data.get("read_ids", [])
        if isinstance(ids, list):
            return {str(i) for i in ids}
    return set()


def is_read(entry: dict, read_ids: set[str]) -> bool:
    """True if *entry* is read: inline flag (legacy) or id in the read set."""
    return bool(entry.get("read", False)) or str(entry.get("id", "")) in read_ids


def mark_read(path: Path, ids: set[str] | list[str], *, live_ids: set[str] | None = None) -> bool:
    """Add *ids* to the read set at *path*, pruned to *live_ids* if given.

    Returns True on success (or when there is nothing to change).
    """
    current = load_read_ids(path)
    updated = current | {str(i) for i in ids}
    if live_ids is not None:
        # Keep only ids that still exist in the hot log so the set stays bounded.
        updated &= {str(i) for i in live_ids}
    if updated == current:
        return True
    return get_repository().set(_COLLECTION, str(path), {"read_ids": sorted(updated)})
