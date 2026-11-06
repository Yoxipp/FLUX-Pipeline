# board_mentions.py — @name in a new board comment -> phone notification (ADR 0075 n°3).
# Same resolution as the team chat (real artists, aliases, never oneself), through the
# public hook of features.notify; a notification never fails the write.

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.logger import get_logger

log = get_logger(__name__)


def mention_targets(text: str, author: str) -> List[str]:
    from features.accounts.aliases import load_aliases, same_user
    from features.activity.chat_manager import get_user_list, parse_pings

    raw = parse_pings(text or "")
    if not raw:
        return []
    table = load_aliases()
    users = {u.lower(): u for u in get_user_list()}
    for old, new in table.items():          # @OLDNAME reaches the artist's current name
        current = users.get(new.lower())
        if current:
            users.setdefault(old.lower(), current)
    out: List[str] = []
    for name in raw:
        real = users.get(name.lower())
        if real and not same_user(real, author, table) and real not in out:
            out.append(real)
    return out


def notify_comments(ops: List[Dict[str, Any]], author: str, project: Optional[str], page_label: str) -> int:
    """Notify the artists named in the NEW comments of *ops* (put without rid): count of notified comments."""
    if not project:
        return 0
    sent = 0
    for op in ops:
        fields = op.get("fields") or {}
        if op.get("op") != "put" or op.get("rid") or fields.get("type") != "comment":
            continue
        try:
            targets = mention_targets(str(fields.get("text") or ""), author)
            if not targets:
                continue
            from features.notify import hooks as notify_hooks

            notify_hooks.on_mentions(author, targets, project, "mention", page_label, "board", str(fields.get("text") or ""))
            sent += 1
        except Exception as exc:  # noqa: BLE001 - a phone notification never fails a board write
            log.warning("Notify for board comment skipped: %s", exc)
    return sent
