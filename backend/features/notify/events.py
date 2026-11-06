# events.py - a notify event and its minimal text. Pure functions, no I/O.
#
# Stable format (the future Flows event.notify node plugs here, ADR 0062):
#   {"type": mention | task | retake | calendar | publish, "project": str,
#    "author": str, "entity": str, "detail": str, "recipients": [str], "at": float,
#    "text": str}
# entity = "SEQ/SHOT", "CLASS/NAME", "chat" or a date span; detail = task name,
# calendar answer... text = the chat message or the calendar title, shown only when
# the project allows it (include_text, ADR 0072). Never a path.

from __future__ import annotations

import time

EVENT_TYPES = ("mention", "task", "retake", "calendar", "publish")
IMMEDIATE = frozenset({"mention", "task", "retake"})    # 2026-10-30, the rest is grouped
TEXT_MAX = 300      # one event's text in a notification (a digest holds up to 15)

_CALENDAR_WORDS = {"proposal": "te propose un creneau", "accept": "a accepte ton creneau",
                   "postpone": "a decale ton creneau", "decline": "a refuse ton creneau"}


def make_event(type_: str, project: str, author: str, entity: str = "", detail: str = "",
               recipients: list[str] | tuple[str, ...] = (), at: float | None = None,
               text: str = "") -> dict:
    if type_ not in EVENT_TYPES:
        raise ValueError(f"unknown notify event type: {type_}")
    return {"type": type_, "project": project or "", "author": (author or "").upper(),
            "entity": entity or "", "detail": detail or "", "recipients": list(recipients),
            "at": time.time() if at is None else at, "text": _clip(text)}


def _clip(text: str) -> str:
    text = " ".join(str(text or "").split())     # one line: a digest stays readable
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 3] + "..."


def format_text(event: dict, include_project: bool = False, include_text: bool = False) -> str:
    """One line: type + entity + author, plus the message / calendar title when
    *include_text*. Example: 'Retake SQ010/SH010 ANIM par TOM'."""
    kind, who = event.get("type"), event.get("author") or "?"
    entity, detail = event.get("entity", ""), event.get("detail", "")
    body = event.get("text", "") if include_text else ""
    if kind == "mention":
        text = f"{who} dans le chat : {body}" if body else f"Mention par {who} dans le chat"
    elif kind == "retake":
        text = f"Retake {entity} {detail} par {who}".replace("  ", " ")
    elif kind == "task":
        text = f"Tache {entity} {detail} assignee par {who}".replace("  ", " ")
    elif kind == "calendar":
        text = f"{who} {_CALENDAR_WORDS.get(detail, 'calendrier')}"
        if body:
            text += f" : {body}"
        if entity:
            text += f" ({entity})"
    elif kind == "publish":
        text = f"Publish {entity} {detail} par {who}".replace("  ", " ")
    else:
        text = f"{kind} par {who}"
    if include_project and event.get("project"):
        text = f"[{event['project']}] {text}"
    return text


def format_digest(events: list[dict], include_project: bool = False, max_lines: int = 15,
                  include_text: bool = False) -> str:
    """Several events for one person in one message; the overflow is counted."""
    if len(events) == 1:
        return format_text(events[0], include_project, include_text)
    lines = [f"{len(events)} notifications FLUX"]
    lines += [f"- {format_text(e, include_project, include_text)}" for e in events[:max_lines]]
    if len(events) > max_lines:
        lines.append(f"- et {len(events) - max_lines} autres")
    return "\n".join(lines)


# ── production diff (task / retake events) ────────────────────────────────────
# The front saves the whole production.json (PUT /production): an assignment or a new
# retake is only visible as a difference between the stored and the saved document.

def _entities(production: dict) -> dict[str, tuple[str, dict]]:
    """{entity id: (label, entity)}: label "SEQ/SHOT" or "CLASS/NAME"."""
    seqs = {s.get("id"): str(s.get("name", "")).upper() for s in production.get("sequences") or []}
    out: dict[str, tuple[str, dict]] = {}
    for shot in production.get("shots") or []:
        if shot.get("id"):
            out[shot["id"]] = (f"{seqs.get(shot.get('seq_id'), '')}/{str(shot.get('name', '')).upper()}", shot)
    for asset in production.get("assets") or []:
        if asset.get("id"):
            out[asset["id"]] = (f"{str(asset.get('class', '')).upper()}/{str(asset.get('name', '')).upper()}", asset)
    return out


def _assignees(detail: dict) -> list[str]:
    return [a.strip().upper() for a in str(detail.get("assignee") or "").split(",") if a.strip()]


def production_changes(previous: dict, new: dict, *, project: str, author: str) -> list[dict]:
    """task events (new assignee on a task) and retake events (new retake id, sent to the
    task's assignees). Recipients are raw names; the dispatcher resolves aliases and
    drops the author."""
    before = _entities(previous or {})
    events: list[dict] = []
    for ent_id, (label, entity) in _entities(new or {}).items():
        old_details = (before.get(ent_id, ("", {}))[1].get("task_details") or {})
        for task, detail in (entity.get("task_details") or {}).items():
            if not isinstance(detail, dict):
                continue
            old = old_details.get(task) if isinstance(old_details.get(task), dict) else {}
            added = [a for a in _assignees(detail) if a not in _assignees(old)]
            if added:
                events.append(make_event("task", project, author, label, str(task).upper(), added))
            old_ids = {r.get("id") for r in old.get("retakes") or [] if isinstance(r, dict)}
            fresh = [r for r in detail.get("retakes") or []
                     if isinstance(r, dict) and r.get("id") and r["id"] not in old_ids]
            if fresh and _assignees(detail):
                events.append(make_event("retake", project, author, label, str(task).upper(),
                                         _assignees(detail)))
    return events
