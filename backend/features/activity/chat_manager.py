# chat_manager.py — read/write teamChat.json.

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from core.json_manager import read_json, write_json
from core.logger import get_logger
from core.paths import get_chat_path, get_users_dir

log = get_logger(__name__)

_PING_RE = re.compile(r"@(\w+)")


def _now() -> tuple[str, str]:
    dt = datetime.now()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _make_id(user: str) -> str:
    return f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{user}_{uuid.uuid4().hex[:6]}"


def send_message(user: str, message: str, path: Path | None = None) -> bool:
    """Append a chat message to teamChat.json. Returns True on success."""
    date, time = _now()
    entry = {
        "id":      _make_id(user),
        "user":    user,
        "message": message.strip(),
        "date":    date,
        "time":    time,
    }
    chat_path = path or get_chat_path()
    messages = read_json(chat_path)
    if not isinstance(messages, list):
        messages = []
    messages.append(entry)
    ok = write_json(chat_path, messages)
    if not ok:
        log.error("Failed to write teamChat.json at %s", chat_path)
    return ok


def get_messages(limit: int = 100, path: Path | None = None) -> list[dict]:
    """Return up to *limit* messages in chronological order (oldest first)."""
    data = read_json(path or get_chat_path())
    messages = data if isinstance(data, list) else []
    messages.sort(key=lambda m: (m.get("date", ""), m.get("time", "")))
    return messages[-limit:]


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
