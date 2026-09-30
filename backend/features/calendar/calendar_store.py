# calendar_store.py - team calendar of a project: who commits to produce what, and when.
#
# 2026-09-30: an artist puts his own commitments on the calendar (title, dates,
# optional link to an asset / shot / task), or proposes one to someone else by pinging
# them. The person pinged accepts, or pushes the dates later and accepts, or declines.
# Everyone sees everyone's commitments: you commit in front of the team.
#
# One calendar.json per project (collection "calendar", keyed by project name, like
# production.json). Items:
#   {id, title, note, link, owner, created_by, start, end (YYYY-MM-DD),
#    status: proposed | accepted (not started) | in_progress | done | declined,
#    created_at, updated_at,
#    history: [{at, by, action, start?, end?}]}

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from core.logger import get_logger
from core.repository_factory import get_repository

log = get_logger(__name__)

_COLLECTION = "calendar"
SCHEMA_VERSION = 1
STATUSES = ("proposed", "accepted", "in_progress", "done", "declined")
# Progress the owner sets (2026-09-30): not started (red), in progress (orange), done (green).
PROGRESS = ("accepted", "in_progress", "done")
_PROGRESS_ACTION = {"accepted": "reopen", "in_progress": "start", "done": "done"}
MAX_TITLE = 200
MAX_NOTE = 4000
MAX_HISTORY = 50


class CalendarError(ValueError):
    """Invalid request (bad dates, unknown item...)."""


class CalendarForbidden(PermissionError):
    """The user may not do this on this item."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _day(value: str, field: str) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise CalendarError(f"{field} invalide : {value!r} (attendu AAAA-MM-JJ)") from exc


def _dates(start: str, end: str | None) -> tuple[str, str]:
    s = _day(start, "debut")
    e = _day(end or start, "fin")
    if e < s:
        raise CalendarError("La fin est avant le debut")
    return s, e


def _same(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


# ── document ─────────────────────────────────────────────────────────────────

def load(project: str) -> dict:
    data = get_repository().get(_COLLECTION, project)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", [])
    data["version"] = SCHEMA_VERSION
    return data


def save(project: str, data: dict) -> None:
    if not get_repository().set(_COLLECTION, project, data):
        raise RuntimeError("Ecriture calendar.json echouee")


def _find(data: dict, item_id: str) -> dict:
    for it in data["items"]:
        if it.get("id") == item_id:
            return it
    raise CalendarError(f"Engagement introuvable : {item_id}")


def _log(item: dict, by: str, action: str, **extra) -> None:
    item.setdefault("history", []).append({"at": _now(), "by": by, "action": action, **extra})
    item["history"] = item["history"][-MAX_HISTORY:]
    item["updated_at"] = _now()


# ── pure operations (mutate *data*, return the item) ─────────────────────────

def create_item(data: dict, by: str, title: str, owner: str, start: str, end: str | None = None,
                note: str = "", link: str = "") -> dict:
    """A commitment for yourself (accepted) or a proposal to someone else (proposed)."""
    title = (title or "").strip()[:MAX_TITLE]
    if not title:
        raise CalendarError("Titre obligatoire")
    owner = (owner or by).strip() or by
    s, e = _dates(start, end)
    item = {
        "id": f"cal_{uuid.uuid4().hex[:10]}",
        "title": title,
        "note": (note or "")[:MAX_NOTE],
        "link": (link or "").strip()[:MAX_TITLE],
        "owner": owner,
        "created_by": by,
        "start": s,
        "end": e,
        "status": "accepted" if _same(owner, by) else "proposed",
        "created_at": _now(),
    }
    _log(item, by, "create" if item["status"] == "accepted" else "propose", start=s, end=e)
    data["items"].append(item)
    return item


def respond(data: dict, item_id: str, by: str, action: str, start: str | None = None,
            end: str | None = None) -> dict:
    """The person pinged answers a proposal: accept, postpone (new dates, then accepted)
    or decline. Only the owner answers."""
    item = _find(data, item_id)
    if not _same(item.get("owner", ""), by):
        raise CalendarForbidden("Seule la personne concernee repond a une proposition")
    if action == "accept":
        item["status"] = "accepted"
        _log(item, by, "accept")
    elif action == "postpone":
        s, e = _dates(start or item["start"], end or item["end"])
        if s < item["start"]:
            raise CalendarError("Decaler = repousser : la nouvelle date doit etre apres l'actuelle")
        item["start"], item["end"], item["status"] = s, e, "accepted"
        _log(item, by, "postpone", start=s, end=e)
    elif action == "decline":
        item["status"] = "declined"
        _log(item, by, "decline")
    else:
        raise CalendarError(f"Reponse inconnue : {action!r}")
    return item


def update_item(data: dict, item_id: str, by: str, **changes) -> dict:
    """Edit title / note / link / dates / status (done, reopen). The owner edits anything;
    the author of a proposal edits it until it is answered."""
    item = _find(data, item_id)
    is_owner = _same(item.get("owner", ""), by)
    is_author = _same(item.get("created_by", ""), by)
    if not is_owner and not (is_author and item.get("status") == "proposed"):
        raise CalendarForbidden("Seule la personne engagee modifie cet engagement")
    if "title" in changes and changes["title"] is not None:
        title = str(changes["title"]).strip()[:MAX_TITLE]
        if not title:
            raise CalendarError("Titre obligatoire")
        item["title"] = title
    if changes.get("note") is not None:
        item["note"] = str(changes["note"])[:MAX_NOTE]
    if changes.get("link") is not None:
        item["link"] = str(changes["link"]).strip()[:MAX_TITLE]
    if changes.get("start") is not None or changes.get("end") is not None:
        s, e = _dates(changes.get("start") or item["start"], changes.get("end") or item["end"])
        if (s, e) != (item["start"], item["end"]):
            item["start"], item["end"] = s, e
            _log(item, by, "move", start=s, end=e)
    status = changes.get("status")
    if status is not None:
        if not is_owner:
            raise CalendarForbidden("Seule la personne engagee change le statut")
        if status not in PROGRESS or item.get("status") not in PROGRESS:
            raise CalendarError(f"Statut refuse : {status!r}")
        if status != item.get("status"):
            item["status"] = status
            _log(item, by, _PROGRESS_ACTION[status])
    item["updated_at"] = _now()
    return item


def delete_item(data: dict, item_id: str, by: str) -> dict:
    item = _find(data, item_id)
    if not (_same(item.get("owner", ""), by) or _same(item.get("created_by", ""), by)):
        raise CalendarForbidden("Seuls l'auteur et la personne engagee suppriment")
    data["items"] = [it for it in data["items"] if it.get("id") != item_id]
    return item
