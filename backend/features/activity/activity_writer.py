# activity_writer.py — append events to CONFIG/activite.json.

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from core.json_manager import read_json, write_json
from core.logger import get_logger
from core.paths import get_activity_path

log = get_logger(__name__)


def _now() -> tuple[str, str]:
    """Return (date_str, time_str) for right now."""
    dt = datetime.now()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def _make_id(user: str) -> str:
    return f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{user}_{uuid.uuid4().hex[:6]}"


# ── public API ────────────────────────────────────────────────────────────────

def log_event(
    user: str,
    action: str,
    project: str,
    filename: str | None = None,
    path: Path | None = None,
) -> bool:
    """Append a single event entry to activite.json.

    *action*   : "publish" | "import" | "connect" | "update" | "error"
    *project*  : project name or DCC name for connect events
    *filename* : optional asset filename involved
    Returns True on success.
    """
    date, time = _now()
    entry = {
        "id":      _make_id(user),
        "user":    user,
        "action":  action,
        "project": project,
        "file":    filename or "",
        "date":    date,
        "time":    time,
        "read":    False,
    }

    act_path = path or get_activity_path()
    events = read_json(act_path)
    if not isinstance(events, list):
        events = []
    events.append(entry)

    ok = write_json(act_path, events)
    if not ok:
        log.error("Failed to write activite.json at %s", act_path)
    return ok


# ── shortcuts ─────────────────────────────────────────────────────────────────

def log_publish(user: str, filename: str, project: str) -> bool:
    return log_event(user, "publish", project, filename)


def log_import(user: str, filename: str, project: str) -> bool:
    return log_event(user, "import", project, filename)


def log_connect(user: str, dcc_name: str) -> bool:
    return log_event(user, "connect", dcc_name)

