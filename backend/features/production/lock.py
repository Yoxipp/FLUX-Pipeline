# lock.py - lock a sequence / shot of Production against edits and deletion.
#
# 2026-09-30: anyone can lock or unlock, a lock blocks modification and deletion,
# unlocking asks to type "Understand" (same gate as the advanced settings). A locked
# sequence protects its shots too. Tasks and comments of a locked shot stay editable
# (that is the production work itself); only the seq / shot records are frozen.
#
# The lock lives on the entity in production.json: "locked": {"by": user, "at": iso}.
# It is only changed through set_lock (POST /production/{p}/lock): a normal save can
# neither add nor remove it, and keep_locked restores any locked record a save changed.

from __future__ import annotations

import copy
from datetime import datetime, timezone

LOCK_KEY = "locked"
UNLOCK_PHRASE = "Understand"
# Fields of a locked record that stay editable: task progress (status, assignee,
# comments live in task_details), free notes and the display order (reordering the
# neighbours shifts it). Everything else is frozen.
EDITABLE_WHEN_LOCKED = ("task_details", "notes", "order")


class LockedError(Exception):
    """Raised when an action targets a locked sequence / shot."""


def _seq_by_name(production: dict, seq: str) -> dict | None:
    return next((s for s in production.get("sequences", []) if s.get("name") == seq), None)


def _shot_by_name(production: dict, seq: str, shot: str) -> dict | None:
    s = _seq_by_name(production, seq)
    if s is None:
        return None
    return next((sh for sh in production.get("shots", [])
                 if sh.get("seq_id") == s.get("id") and sh.get("name") == shot), None)


def lock_of(production: dict, kind: str, seq: str, shot: str = "") -> dict | None:
    """The lock that protects this entity (its own, or its sequence's for a shot)."""
    s = _seq_by_name(production, seq)
    if s is not None and s.get(LOCK_KEY):
        return s[LOCK_KEY]
    if kind == "shot":
        sh = _shot_by_name(production, seq, shot)
        if sh is not None and sh.get(LOCK_KEY):
            return sh[LOCK_KEY]
    return None


def ensure_unlocked(production: dict, kind: str, seq: str, shot: str = "") -> None:
    """Raise LockedError when the entity (or, for a sequence, one of its shots) is locked."""
    what = f"{seq} {shot}".strip()
    lock = lock_of(production, kind, seq, shot)
    if lock:
        raise LockedError(f"{what} est verrouille par {lock.get('by') or '?'}")
    if kind == "seq":
        s = _seq_by_name(production, seq)
        for sh in production.get("shots", []):
            if s is not None and sh.get("seq_id") == s.get("id") and sh.get(LOCK_KEY):
                raise LockedError(f"{seq} contient un shot verrouille ({sh.get('name')})")


def set_lock(production: dict, kind: str, seq: str, shot: str, locked: bool, user: str,
             phrase: str = "") -> dict:
    """Lock / unlock a sequence or shot (mutates *production*). Unlocking needs the phrase."""
    entity = _seq_by_name(production, seq) if kind == "seq" else _shot_by_name(production, seq, shot)
    if entity is None:
        raise ValueError(f"{kind} introuvable : {seq} {shot}".strip())
    if locked:
        entity[LOCK_KEY] = {"by": user, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    else:
        if phrase.strip() != UNLOCK_PHRASE:
            raise PermissionError(f"Tape {UNLOCK_PHRASE} pour deverrouiller")
        entity.pop(LOCK_KEY, None)
    return entity


def keep_locked(production: dict, previous: dict | None) -> list[str]:
    """Before a save: a locked record comes back exactly as it was (edited or removed by
    the client), and no lock is added or dropped outside set_lock. Returns the names of
    the records restored."""
    previous = previous or {}
    prev_seqs = {s.get("id"): s for s in previous.get("sequences", [])}
    locked_seq_ids = {i for i, s in prev_seqs.items() if s.get(LOCK_KEY)}
    restored: list[str] = []

    def _guard(key: str, is_locked) -> None:
        prev_items = {e.get("id"): e for e in previous.get(key, [])}
        items = production.setdefault(key, [])
        present = {e.get("id") for e in items}
        for idx, e in enumerate(items):
            old = prev_items.get(e.get("id"))
            if old is not None and is_locked(old):
                kept = copy.deepcopy(old)
                for k in EDITABLE_WHEN_LOCKED:
                    if k in e:
                        kept[k] = e[k]
                    else:
                        kept.pop(k, None)
                if e != kept:
                    items[idx] = kept
                    restored.append(old.get("name") or str(old.get("id")))
            else:
                # Lock state follows the stored one (none for a new or unlocked record).
                if old is not None and old.get(LOCK_KEY):
                    e[LOCK_KEY] = copy.deepcopy(old[LOCK_KEY])
                else:
                    e.pop(LOCK_KEY, None)
        for i, old in prev_items.items():
            if i not in present and is_locked(old):
                items.append(copy.deepcopy(old))
                restored.append(old.get("name") or str(i))

    _guard("sequences", lambda s: bool(s.get(LOCK_KEY)))
    _guard("shots", lambda sh: bool(sh.get(LOCK_KEY)) or sh.get("seq_id") in locked_seq_ids)
    return restored
