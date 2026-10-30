# aliases.py - old artist name -> current name, so a rename keeps the history.
#
# Chat, mentions and activity are append-only logs, publish metadata is spread over the
# project folders and production.json / calendar.json are written whole by clients:
# nothing is rewritten on rename (2026-10-24, aliases only). Readers map every
# stored name through resolve_user() before showing or comparing it.
#
# Table: FLUX_ROOT/CONFIG/user_aliases.json {"aliases": {"OLD": "NEW"}}. It is kept
# flat (A -> B then B -> C is stored as A -> C, B -> C), so a lookup is one get().
# A retired name is never given to another artist: its history would follow.

from __future__ import annotations

from pathlib import Path

from core import paths
from core.json_manager import append_lock, cached_read_json, invalidate_cache, read_json, write_json
from core.logger import get_logger

log = get_logger(__name__)

ALIASES_FILENAME = "user_aliases.json"


def aliases_path() -> Path:
    # Same root as USER/ (= get_config_dir()), derived from the users dir so a test or
    # tool that points USER/ elsewhere never touches the real workspace's table.
    return paths.get_users_dir().parent / "CONFIG" / ALIASES_FILENAME


def _clean(raw: object) -> dict[str, str]:
    table = raw.get("aliases") if isinstance(raw, dict) else None
    if not isinstance(table, dict):
        return {}
    clean: dict[str, str] = {}
    for old, new in table.items():
        old_u, new_u = str(old or "").strip().upper(), str(new or "").strip().upper()
        if old_u and new_u and old_u != new_u:
            clean[old_u] = new_u
    return clean


def load_aliases() -> dict[str, str]:
    """Return {OLD: CURRENT} (empty when FLUX_ROOT is unset or the file is absent)."""
    try:
        path = aliases_path()
    except RuntimeError:
        return {}
    return _clean(cached_read_json(path))


def resolve_user(name, aliases: dict[str, str] | None = None):
    """Current name of *name*; unchanged (same object) when it was never renamed.

    Pass *aliases* (from load_aliases) when resolving many names in a loop.
    """
    if not name or not isinstance(name, str):
        return name
    table = load_aliases() if aliases is None else aliases
    return table.get(name.strip().upper(), name)


def same_user(a, b, aliases: dict[str, str] | None = None) -> bool:
    """True if *a* and *b* are the same artist (case-insensitive, aliases resolved)."""
    if not a or not b:
        return False
    table = load_aliases() if aliases is None else aliases
    return (str(resolve_user(a, table)).strip().upper()
            == str(resolve_user(b, table)).strip().upper())


def is_retired_name(name: str, aliases: dict[str, str] | None = None) -> bool:
    """True if *name* belonged to an artist who was renamed since."""
    table = load_aliases() if aliases is None else aliases
    return str(name or "").strip().upper() in table


def can_take_name(old: str, new: str, aliases: dict[str, str] | None = None) -> bool:
    """True if artist *old* may be renamed *new*: free name, or *new* was *old*'s own."""
    table = load_aliases() if aliases is None else aliases
    new_u, old_u = str(new or "").strip().upper(), str(old or "").strip().upper()
    return new_u not in table or table[new_u] == old_u


def record_rename(old: str, new: str) -> dict[str, str]:
    """Add OLD -> NEW to the table (flattened). Returns the new table."""
    old_u, new_u = old.strip().upper(), new.strip().upper()
    path = aliases_path()
    with append_lock(path):
        table = _clean(read_json(path))
        table.pop(new_u, None)            # NEW is a live name again (rename back)
        for key, value in list(table.items()):
            if value == old_u:
                table[key] = new_u
        table[old_u] = new_u
        table = {k: v for k, v in table.items() if k != v}
        if not write_json(path, {"aliases": dict(sorted(table.items()))}):
            raise OSError("user_aliases.json : ecriture impossible")
    invalidate_cache(path)
    log.info("Alias recorded '%s' -> '%s'", old_u, new_u)
    return table
