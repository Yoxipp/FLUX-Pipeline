# activity_writer.py — append events to CONFIG/activite.json.

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from core.json_manager import read_json, write_json
from core.logger import get_logger
from core.paths import get_activity_path, get_flux_root

log = get_logger(__name__)

# Portable prefix stored instead of a machine-absolute path, so every teammate
# resolves the notification against THEIR own FLUX_ROOT (workspace).
_FLUX_PREFIX = "$FLUX"


def _portable_path(p: Path | str | None) -> str:
    """Return *p* relative to FLUX_ROOT as "$FLUX/<rel>", else its plain string.

    The publisher's absolute path is meaningless on another machine; storing it
    relative to the shared FLUX root lets each client expand it locally.
    """
    if not p:
        return ""
    path = Path(p)
    root = get_flux_root()
    if root:
        try:
            rel = path.resolve().relative_to(Path(root).resolve())
            return f"{_FLUX_PREFIX}/{rel.as_posix()}"
        except (ValueError, OSError):
            pass  # not under FLUX_ROOT — keep absolute as a fallback
    return str(path)


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
    dest_folder: Path | str | None = None,
) -> bool:
    """Append a single event entry to activite.json.

    *action*      : "publish" | "import" | "connect" | "update" | "error"
    *project*     : project name or DCC name for connect events
    *filename*    : optional asset filename involved
    *dest_folder* : optional publish destination directory (for folder-open UX)
    Returns True on success.
    """
    date, time = _now()
    entry = {
        "id":          _make_id(user),
        "user":        user,
        "action":      action,
        "project":     project,
        "file":        filename or "",
        "dest_folder": _portable_path(dest_folder),
        "date":        date,
        "time":        time,
        "read":        False,
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

def log_publish(user: str, filename: str, project: str, dest_folder: Path | str | None = None) -> bool:
    return log_event(user, "publish", project, filename, dest_folder=dest_folder)


def log_import(user: str, filename: str, project: str, dest_folder: Path | str | None = None) -> bool:
    # dest_folder = the imported file's source folder, so the notification can offer
    # "copy path / open folder / open in Folder Manager" like a publish event.
    return log_event(user, "import", project, filename, dest_folder=dest_folder)


def log_connect(user: str, dcc_name: str) -> bool:
    return log_event(user, "connect", dcc_name)

