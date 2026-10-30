# team_calendar.py - team calendar routes (2026-09-30): commitments and proposals.
#
# A proposal to someone else pings them (their @mentions, same badge as the chat);
# their answer (accept / postpone / decline) pings the author back.

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.logger import get_logger
from features.accounts.aliases import same_user
from features.accounts.alias_views import resolve_calendar_items
from features.calendar import calendar_store as store
from utils import project_utils

log = get_logger(__name__)
router = APIRouter()


def _ensure_project(project: str) -> None:
    if not project_utils.project_exists(project):
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")


def _user() -> str:
    return config.get_current_user() or "unknown"


def _ping(project: str, from_user: str, to_user: str, text: str) -> None:
    """Best-effort @mention so the person sees it in their mentions (never fails a save)."""
    try:
        from features.activity.chat_manager import _now, _record_mentions
        d, t = _now()
        _record_mentions(from_user, f"cal_{uuid.uuid4().hex[:8]}", f"@{to_user} {text}", d, t, project)
    except Exception as exc:  # noqa: BLE001
        log.warning("Calendar ping to %s failed: %s", to_user, exc)


def _span(item: dict) -> str:
    return item["start"] if item["start"] == item["end"] else f"{item['start']} > {item['end']}"


async def _mutate(project: str, fn):
    """Load, apply *fn(data)* and save in the executor; maps store errors to HTTP."""
    _ensure_project(project)
    loop = asyncio.get_running_loop()

    def _do():
        data = store.load(project)
        result = fn(data)
        store.save(project, data)
        return result

    try:
        return await loop.run_in_executor(None, _do)
    except store.CalendarForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except store.CalendarError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("calendar update failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project}/publishes")
async def get_publishes(project: str, start: str, end: str) -> dict:
    """Publishes of the project between two dates (activity log, archives included)."""
    from features.calendar.publishes import publishes_between

    _ensure_project(project)
    loop = asyncio.get_running_loop()
    try:
        items = await loop.run_in_executor(None, lambda: publishes_between(project, start, end))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"publishes": items}


@router.get("/{project}")
async def get_calendar(project: str) -> dict:
    _ensure_project(project)
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, lambda: store.load(project))
    return {"items": resolve_calendar_items(data["items"]), "me": _user()}


class CreateRequest(BaseModel):
    title: str
    owner: str = ""        # empty = me; someone else = a proposal that pings them
    start: str
    end:   str = ""
    note:  str = ""
    link:  str = ""


@router.post("/{project}/items")
async def create_item(project: str, req: CreateRequest) -> dict:
    by = _user()
    item = await _mutate(project, lambda d: store.create_item(
        d, by, req.title, req.owner or by, req.start, req.end or None, req.note, req.link))
    if item["status"] == "proposed":
        _ping(project, by, item["owner"], f"te propose : {item['title']} ({_span(item)}), a valider dans le Calendrier")
    return {"item": item}


class RespondRequest(BaseModel):
    action: str            # accept | postpone | decline
    start:  str = ""
    end:    str = ""


@router.post("/{project}/items/{item_id}/respond")
async def respond(project: str, item_id: str, req: RespondRequest) -> dict:
    by = _user()
    item = await _mutate(project, lambda d: store.respond(
        d, item_id, by, req.action, req.start or None, req.end or None))
    words = {"accept": "a accepte", "postpone": "a decale puis accepte", "decline": "a refuse"}
    if item.get("created_by") and not same_user(item["created_by"], by):
        _ping(project, by, item["created_by"], f"{words.get(req.action, req.action)} : {item['title']} ({_span(item)})")
    return {"item": item}


class UpdateRequest(BaseModel):
    title:  str | None = None
    note:   str | None = None
    link:   str | None = None
    start:  str | None = None
    end:    str | None = None
    status: str | None = None   # accepted (not started) | in_progress | done


@router.patch("/{project}/items/{item_id}")
async def update_item(project: str, item_id: str, req: UpdateRequest) -> dict:
    by = _user()
    item = await _mutate(project, lambda d: store.update_item(d, item_id, by, **req.model_dump()))
    return {"item": item}


@router.delete("/{project}/items/{item_id}")
async def delete_item(project: str, item_id: str) -> dict:
    by = _user()
    item = await _mutate(project, lambda d: store.delete_item(d, item_id, by))
    return {"ok": True, "id": item["id"]}
