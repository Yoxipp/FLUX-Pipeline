# chat_manager.py — read/write the per-project team chat (DOSSIER_PROJETS/<project>/teamChat.json).

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from core.constants import ARCHIVE_STEM_MENTIONS
from core.logger import get_logger
from core.paths import (
    get_mentions_path, get_mentions_read_path, get_project_chat_path, get_users_dir,
)
from core.repository_factory import get_repository
from features.accounts.aliases import load_aliases, resolve_user, same_user
from features.activity.history import append_events
from features.activity.read_state import is_read, load_read_ids, mark_read

log = get_logger(__name__)

# Metadata frontier (V5): the two feeds go through the repository, addressed by
# their own path (transitional doc_id), so callers keep passing the path they
# already compute (default or test-injected).
_CHAT_COLLECTION = "chat_log"
_MENTIONS_COLLECTION = "mentions_log"

_PING_RE = re.compile(r"@(\w+)")


def _now() -> tuple[str, str]:
    dt = datetime.now()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _make_id(user: str) -> str:
    return f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{user}_{uuid.uuid4().hex[:6]}"


def resolve_chat_path(project: str | None) -> Path:
    """Return the team chat file of *project*.

    Raises ValueError for an empty or unsafe name (path separators, ".."), and
    FileNotFoundError when the project folder does not exist, so a request can never
    write a chat file outside DOSSIER_PROJETS/<project>/.
    """
    name = (project or "").strip()
    if not name or name in (".", "..") or any(c in name for c in "/\\:"):
        raise ValueError(f"invalid project name: {project!r}")
    path = get_project_chat_path(name)
    if not path.parent.is_dir():
        raise FileNotFoundError(f"project not found: {name}")
    return path


def send_message(
    user: str, message: str, project: str | None = None, path: Path | None = None,
) -> bool:
    """Append a chat message to the team chat of *project*. Returns True on success.

    *path* (tests) overrides the project's chat file. Any @name that matches a known
    user (case-insensitive, never the author) is recorded as an unread mention so
    that user gets a red notification, tagged with the project it was said in.
    """
    date, time = _now()
    msg_id = _make_id(user)
    text = message.strip()
    entry = {
        "id":      msg_id,
        "user":    user,
        "message": text,
        "date":    date,
        "time":    time,
    }
    chat_path = path or resolve_chat_path(project)
    # Append-only JSONL: one atomic write, so concurrent senders never clobber
    # each other's message (was a read-modify-write of the whole array).
    ok = get_repository().append_log(_CHAT_COLLECTION, str(chat_path), [entry])
    if not ok:
        log.error("Failed to write team chat at %s", chat_path)
        return ok

    # Record mentions (best-effort — never fail the send if this part errors).
    try:
        _record_mentions(
            from_user=user, msg_id=msg_id, text=text, date=date, time=time, project=project,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to record chat mentions: %s", exc)
    return ok


def get_messages(
    limit: int = 100, project: str | None = None, path: Path | None = None,
) -> list[dict]:
    """Return up to *limit* messages of *project*'s chat, oldest first."""
    chat_path = path or resolve_chat_path(project)
    messages = get_repository().read_log(_CHAT_COLLECTION, str(chat_path))
    messages.sort(key=lambda m: (m.get("date", ""), m.get("time", "")))
    table = load_aliases()
    return [{**m, "user": resolve_user(m.get("user"), table)} if "user" in m else m
            for m in messages[-limit:]]


def get_user_list() -> list[str]:
    """Return sorted list of user names from FLUX_ROOT/USER/ (for @ping autocomplete)."""
    try:
        users_dir = get_users_dir()
        return sorted(p.name for p in users_dir.iterdir() if p.is_dir())
    except (OSError, RuntimeError):
        return []


def parse_pings(message: str) -> list[str]:
    """Return list of names mentioned as @name in *message*."""
    return _PING_RE.findall(message)


# ── @mentions ─────────────────────────────────────────────────────────────────

def _record_mentions(
    from_user: str, msg_id: str, text: str, date: str, time: str, project: str | None = None,
    *, notify_kind: str = "mention", notify_detail: str = "", notify_entity: str = "",
    notify_text: str | None = None,
) -> None:
    """Persist an unread mention entry for each valid @name in *text*.

    Resolves each @name against the real user list (case-insensitive) so a typo
    doesn't spam a phantom user, and skips self-mentions. The same targets get a
    phone notification (features.notify, *notify_kind* "calendar" for calendar pings)
    carrying *notify_text* (default: the message), shown only when the project allows
    it (include_text, ADR 0072).
    """
    raw = parse_pings(text)
    if not raw:
        return
    table = load_aliases()
    users = {u.lower(): u for u in get_user_list()}
    for old, new in table.items():          # @OLDNAME reaches the artist's current name
        current = users.get(new.lower())
        if current:
            users.setdefault(old.lower(), current)
    targets: list[str] = []
    for name in raw:
        real = users.get(name.lower())
        if real and not same_user(real, from_user, table) and real not in targets:
            targets.append(real)
    if not targets:
        return

    new_entries = [
        {
            "id":        f"{msg_id}_{to_user}",
            "message_id": msg_id,
            "to_user":   to_user,
            "from_user": from_user,
            "text":      text,
            "date":      date,
            "time":      time,
            "project":   project or "",
            "read":      False,
        }
        for to_user in targets
    ]
    mpath = get_mentions_path()
    # Append + rotate: bounds the hot file and archives the overflow (Phase 3).
    if not append_events(mpath, new_entries, ARCHIVE_STEM_MENTIONS, _MENTIONS_COLLECTION):
        log.error("Failed to write chatMentions.json at %s", mpath)
    try:
        from features.notify import hooks as notify_hooks
        notify_hooks.on_mentions(from_user, targets, project, notify_kind, notify_detail, notify_entity,
                                 text if notify_text is None else notify_text)
    except Exception as exc:  # noqa: BLE001 - a phone notification never fails a message
        log.warning("Notify for mentions skipped: %s", exc)


def _mentions_read_path(path: Path | None) -> Path:
    """Companion read-status file for the mentions log at *path* (or default)."""
    if path is None:
        return get_mentions_read_path()
    p = Path(path)
    return p.with_name(f"{p.stem}_read.json")


def _shown_mention(m: dict, read_ids, table: dict[str, str]) -> dict:
    """Copy of mention *m* with current names and the read flag overlaid."""
    return {**m, "read": is_read(m, read_ids),
            "to_user": resolve_user(m.get("to_user"), table),
            "from_user": resolve_user(m.get("from_user"), table)}


def get_mentions(user: str, unread_only: bool = False, path: Path | None = None) -> list[dict]:
    """Return mention entries addressed to *user*, newest first.

    Matching is case-insensitive so a name-case mismatch between the stored
    to_user and the current user never silently drops notifications. Read-status
    is overlaid from the companion set-file (Phase 5).
    """
    table = load_aliases()
    mentions = get_repository().read_log(_MENTIONS_COLLECTION, str(path or get_mentions_path()))
    read_ids = load_read_ids(_mentions_read_path(path))
    out = [
        _shown_mention(m, read_ids, table)
        for m in mentions
        if same_user(m.get("to_user"), user, table) and (not unread_only or not is_read(m, read_ids))
    ]
    out.sort(key=lambda m: (m.get("date", ""), m.get("time", "")), reverse=True)
    return out


def get_unread_mention_count(user: str, path: Path | None = None) -> int:
    """Return how many unread mentions *user* has."""
    return len(get_mentions(user, unread_only=True, path=path))


def get_mentions_and_unread(
    user: str, unread_only: bool = False, path: Path | None = None,
    sig: tuple[int, int] | None = None,
) -> tuple[list[dict], int]:
    """Return (mentions[, newest first], unread count) for *user* in ONE read.

    Single-pass equivalent of ``get_mentions`` + ``get_unread_mention_count`` —
    avoids reading the shared chatMentions.json twice per poll (Phase 1). The
    unread count always reflects every mention addressed to *user*, independent
    of *unread_only*. Read-status is overlaid from the companion set-file.

    *sig* (mtime_ns, size) may be passed by the router so the cache reuses the
    stat already taken for the ETag rather than issuing a second one (Phase 4).
    """
    table = load_aliases()
    mentions = get_repository().read_log(
        _MENTIONS_COLLECTION, str(path or get_mentions_path()), sig=sig,
    )
    read_ids = load_read_ids(_mentions_read_path(path))
    mine = [m for m in mentions if same_user(m.get("to_user"), user, table)]
    unread = sum(1 for m in mine if not is_read(m, read_ids))
    out = [
        _shown_mention(m, read_ids, table)
        for m in mine
        if (not unread_only or not is_read(m, read_ids))
    ]
    out.sort(key=lambda m: (m.get("date", ""), m.get("time", "")), reverse=True)
    return out, unread


def mark_mentions_read(user: str, path: Path | None = None) -> bool:
    """Mark every mention addressed to *user* as read (companion set-file only).

    The append-only mentions log is never rewritten.
    """
    table = load_aliases()
    mentions = get_repository().read_log(
        _MENTIONS_COLLECTION, str(path or get_mentions_path()), fresh=True,
    )   # fresh: live ids
    live_ids = {str(m.get("id", "")) for m in mentions}
    mine_ids = {str(m.get("id", "")) for m in mentions if same_user(m.get("to_user"), user, table)}
    return mark_read(_mentions_read_path(path), mine_ids, live_ids=live_ids)
