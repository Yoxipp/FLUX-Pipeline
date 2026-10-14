# locks.py — per-project folder lock registry.
#
# A locked folder cannot be cut, moved, or deleted. Locks are independent:
# locking a child never blocks an operation on its (unlocked) parent — callers
# check only the item they act on.
#
# Storage: <project_root>/_flux_setup/locks.json  → {"locked": ["assets/chara/HERO/rig", ...]}
# It sits next to tokens.json. The setup folder itself (and everything in it) is
# always locked (is_locked) and can never be unlocked; the router adds it to the list
# it sends to the UI (with_setup) so the lock badge shows.

from __future__ import annotations

from pathlib import Path

from core.constants import SETUP_DIR
from core.logger import get_logger
from core.project_setup import is_setup_rel
from core.repository_factory import get_repository

log = get_logger(__name__)

# Metadata frontier (V5): locks.json goes through the repository. The document is
# a dict {"locked": [...]}, addressed by its project folder (the resolver appends
# the file name), exactly like tokens.json.
_COLLECTION = "locks"


def _norm(rel_path: str) -> str:
    return rel_path.replace("\\", "/").strip("/")


def load_locks(project_path: Path) -> list[str]:
    """Return the sorted list of locked relative paths for a project."""
    return sorted(_stored_locks(project_path))


def with_setup(locked: list[str]) -> list[str]:
    """*locked* plus the setup folder, always locked (what the Folder Manager shows)."""
    return sorted({SETUP_DIR, *locked})


def _stored_locks(project_path: Path) -> set[str]:
    data = get_repository().get(_COLLECTION, str(project_path))
    if isinstance(data, dict):
        locked = data.get("locked", [])
        if isinstance(locked, list):
            return {_norm(str(p)) for p in locked}
    return set()


def is_locked(project_path: Path, rel_path: str) -> bool:
    """Return True if *rel_path* (relative to project root) is locked."""
    rel = _norm(rel_path)
    return is_setup_rel(rel) or rel in _stored_locks(project_path)


def set_lock(project_path: Path, rel_path: str, locked: bool) -> list[str]:
    """Add or remove a lock for *rel_path*. Returns the updated locked list."""
    rel = _norm(rel_path)
    current = _stored_locks(project_path)
    if locked:
        current.add(rel)
    else:
        current.discard(rel)
    ordered = sorted(p for p in current if not is_setup_rel(p))
    if not get_repository().set(_COLLECTION, str(project_path), {"locked": ordered}):
        log.warning("Could not write locks.json for %s", project_path)
    return ordered
