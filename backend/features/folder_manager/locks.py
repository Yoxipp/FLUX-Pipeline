# locks.py — per-project folder lock registry.
#
# A locked folder cannot be cut, moved, or deleted. Locks are independent:
# locking a child never blocks an operation on its (unlocked) parent — callers
# check only the item they act on.
#
# Storage: <project_root>/locks.json  → {"locked": ["assets/chara/HERO/rig", ...]}
# It sits next to tokens.json and is excluded from browsing (.json are hidden).

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
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
    data = get_repository().get(_COLLECTION, str(project_path))
    if isinstance(data, dict):
        locked = data.get("locked", [])
        if isinstance(locked, list):
            return sorted(_norm(str(p)) for p in locked)
    return []


def is_locked(project_path: Path, rel_path: str) -> bool:
    """Return True if *rel_path* (relative to project root) is locked."""
    return _norm(rel_path) in set(load_locks(project_path))


def set_lock(project_path: Path, rel_path: str, locked: bool) -> list[str]:
    """Add or remove a lock for *rel_path*. Returns the updated locked list."""
    rel = _norm(rel_path)
    current = set(load_locks(project_path))
    if locked:
        current.add(rel)
    else:
        current.discard(rel)
    ordered = sorted(current)
    if not get_repository().set(_COLLECTION, str(project_path), {"locked": ordered}):
        log.warning("Could not write locks.json for %s", project_path)
    return ordered
