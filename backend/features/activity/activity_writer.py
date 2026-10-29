# activity_writer.py — append events to CONFIG/activite.json.

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from core.constants import ARCHIVE_STEM_ACTIVITY
from core.logger import get_logger
from core.paths import get_activity_path, get_flux_root
from features.activity.history import append_events

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
    # Append + rotate: bounds the hot file and archives the overflow (Phase 3).
    ok = append_events(act_path, [entry], ARCHIVE_STEM_ACTIVITY, "activity_log")
    if not ok:
        log.error("Failed to write activite.json at %s", act_path)
    return ok


# ── shortcuts ─────────────────────────────────────────────────────────────────

def log_publish(user: str, filename: str, project: str, dest_folder: Path | str | None = None,
                soft: str = "") -> bool:
    # soft: the software that published (maya, houdini...), for the Flows OnPublish soft
    # filter; empty = deduced from the extension there (R1 audit F6, 2026-10-25).
    ok = log_event(user, "publish", project, filename, dest_folder=dest_folder)
    # Flows event.on_publish (P5, 01 §9 A9): every soft reaches this point after a
    # successful publish. Non blocking, a no-op without an active OnPublish flow, cut by
    # FLUX_FLOWS_HOOKS=0; it never changes the publish or its result.
    try:
        from flux_flows.events import publish_done

        publish_done(user, filename, project, dest_folder, soft=soft)
    except Exception as exc:  # noqa: BLE001 - a flow hook never fails a publish
        log.warning("Flows on_publish skipped: %s", exc)
    return ok


def log_import(user: str, filename: str, project: str, dest_folder: Path | str | None = None) -> bool:
    # dest_folder = the imported file's source folder, so the notification can offer
    # "copy path / open folder / open in Folder Manager" like a publish event.
    return log_event(user, "import", project, filename, dest_folder=dest_folder)


def log_connect(user: str, dcc_name: str) -> bool:
    return log_event(user, "connect", dcc_name)

