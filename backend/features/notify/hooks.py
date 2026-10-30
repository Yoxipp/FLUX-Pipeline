# hooks.py - the single entry points the rest of FLUX calls (one per event source).
#
#   on_mentions     chat_manager._record_mentions (chat @mention and calendar pings)
#   on_production   routers/production.put_production (task assigned, new retake)
#   on_publish      activity_writer.log_publish (followed / favorite / assigned publish)
#
# Each one returns at once: the work (reading accounts, the production document) runs
# in a daemon thread and never raises. Who receives a publish reuses the personal feed
# filter of ADR 0045 (features.activity.notifications.reason_for), aliases included.

from __future__ import annotations

import threading

from core.logger import get_logger
from features.notify import dispatch
from features.notify.events import make_event, production_changes

log = get_logger(__name__)


def _background(fn, *args) -> None:
    if not dispatch.enabled():
        return

    def run() -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 - a notification never fails an action
            log.warning("notify hook %s skipped: %s", getattr(fn, "__name__", "?"), exc)

    threading.Thread(target=run, name="flux-notify-hook", daemon=True).start()


# ── mentions / calendar ───────────────────────────────────────────────────────

def mention_event(from_user: str, targets: list[str], project: str, kind: str = "mention",
                  detail: str = "", entity: str = "") -> dict:
    return make_event(kind, project, from_user, entity or ("chat" if kind == "mention" else ""),
                      detail, targets)


def on_mentions(from_user: str, targets: list[str], project: str | None, kind: str = "mention",
                detail: str = "", entity: str = "") -> None:
    if not targets or not project:
        return
    _background(lambda: dispatch.enqueue(mention_event(from_user, list(targets), project, kind, detail, entity)))


# ── production (tasks / retakes) ──────────────────────────────────────────────

def on_production(project: str, previous: dict, new: dict, author: str) -> None:
    def run() -> None:
        for event in production_changes(previous, new, project=project, author=author):
            dispatch.enqueue(event)
    _background(run)


# ── publish ───────────────────────────────────────────────────────────────────

def publish_recipients(user: str, filename: str, project: str) -> tuple[dict, list[str]]:
    """(event, names) for one publish: every account whose personal feed would show it."""
    from features.activity.notifications import assignments, reason_for
    from features.production.production_store import load_production
    from features.production.reconcile import parse_publish_event
    from utils.user_utils import list_users, read_user_data

    activity = {"project": project, "file": filename, "action": "publish", "user": user}
    parsed = parse_publish_event(activity) or {}
    if parsed.get("is_shot"):
        entity = f"{parsed.get('SEQ', '')}/{parsed.get('SHOT', '')}"
    else:
        entity = f"{parsed.get('CLASS', '')}/{parsed.get('NAME', '')}"
    detail = str(parsed.get("TASK", "")).upper()
    try:
        production = load_production(project) or {}
    except Exception:  # noqa: BLE001 - no production = favorites only
        production = {}
    names: list[str] = []
    for name in list_users():
        prefs = read_user_data(name)
        if not isinstance((prefs.get("notify") or {}), dict) or (prefs.get("notify") or {}).get("channel") in (None, "", "none"):
            continue    # no phone channel: skip the costly filter
        favorites = [f for f in (prefs.get("production") or {}).get("favorites") or [] if isinstance(f, str)]
        if reason_for(activity, project=project, favorites=favorites,
                      assigned=assignments(production, name)):
            names.append(name)
    event = make_event("publish", project, user, entity.strip("/").upper() if parsed else "", detail, names)
    return event, names


def on_publish(user: str, filename: str, project: str) -> None:
    def run() -> None:
        event, names = publish_recipients(user, filename, project)
        if names:
            dispatch.enqueue(event)
    _background(run)
