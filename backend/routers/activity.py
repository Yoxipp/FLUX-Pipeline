# routers/activity.py — activity feed + team chat endpoints.

from __future__ import annotations

import asyncio
import hashlib

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from core import config
from core.json_manager import file_validator
from core.logger import get_logger
from core.paths import get_activity_path, get_chat_path, get_mentions_path, get_users_dir
from features.activity.activity_reader import (
    get_events_and_unread, mark_all_as_read, mark_as_read,
)
from features.activity.chat_manager import (
    get_mentions_and_unread, get_messages, get_user_list,
    mark_mentions_read, send_message,
)

log = get_logger(__name__)
router = APIRouter()


# ── conditional-GET helpers (Phase 2: mtime/size ETag → 304) ────────────────────

def _etag(validator: str, view: str) -> str:
    """Weak ETag from a file *validator* (stat token) + a per-*view* key.

    The validator reflects the source file; *view* folds in the query params
    (limit/user/…) so two differently-filtered views of the same file never
    collide, while an unchanged file+view still short-circuits to 304.
    """
    digest = hashlib.sha1(f"{validator}|{view}".encode()).hexdigest()[:16]
    return f'W/"{digest}"'


def _strip_weak(tag: str) -> str:
    tag = tag.strip()
    if tag.startswith(("W/", "w/")):
        tag = tag[2:]
    return tag.strip()


def _not_modified(request: Request, etag: str) -> bool:
    """True if the request's If-None-Match matches *etag* (weak comparison)."""
    inm = request.headers.get("if-none-match")
    if not inm:
        return False
    if inm.strip() == "*":
        return True
    target = _strip_weak(etag)
    return any(_strip_weak(t) == target for t in inm.split(","))


class ChatMessage(BaseModel):
    user: str | None = None
    message: str


class MarkReadRequest(BaseModel):
    event_id: str


class MentionsReadRequest(BaseModel):
    user: str | None = None


@router.get("")
async def get_activity(
    request: Request,
    response: Response,
    limit: int = 50,
    user: str | None = None,
    action: str | None = None,
    project: str | None = None,
) -> dict:
    """Return activity events with optional filters.

    Returns empty results (not 500) when FLUX_ROOT is not yet set (first-launch state).

    Conditional GET: an ETag derived from the file's stat + the query params lets
    an unchanged poll short-circuit to 304 without reading or serialising the
    file. The unread count depends only on file content, so it is covered too.
    """
    try:
        path = get_activity_path()
    except RuntimeError:
        return {"events": [], "unread_count": 0}

    validator = file_validator(path)
    etag = _etag(validator, f"a:{limit}:{user}:{action}:{project}") if validator else None
    if etag and _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})

    loop = asyncio.get_event_loop()
    events, unread = await loop.run_in_executor(
        None,
        lambda: get_events_and_unread(limit=limit, user=user, action=action, project=project, path=path),
    )
    if etag:
        response.headers["ETag"] = etag
    return {"events": events, "unread_count": unread}


@router.post("/read")
async def mark_read(req: MarkReadRequest) -> dict:
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: mark_as_read(req.event_id))
    if not ok:
        raise HTTPException(status_code=404, detail="Événement introuvable")
    return {"success": True}


@router.post("/read-all")
async def mark_all_read() -> dict:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, mark_all_as_read)
    return {"success": True}


@router.get("/chat")
async def get_chat(request: Request, response: Response, limit: int = 100) -> dict:
    """Return the last *limit* chat messages.

    Returns empty results (not 500) when FLUX_ROOT is not yet set.

    Conditional GET: the ETag reflects teamChat.json *and* the USER directory's
    stat — the latter because the response also carries the @-autocomplete user
    list, so adding/removing a user must invalidate the cached view too.
    """
    try:
        chat_path = get_chat_path()
        users_validator = file_validator(get_users_dir())
    except RuntimeError:
        return {"messages": [], "users": []}

    validator = file_validator(chat_path)
    etag = _etag(validator, f"c:{limit}:{users_validator}") if validator else None
    if etag and _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})

    loop = asyncio.get_event_loop()
    messages = await loop.run_in_executor(None, lambda: get_messages(limit=limit, path=chat_path))
    users = await loop.run_in_executor(None, get_user_list)
    if etag:
        response.headers["ETag"] = etag
    return {"messages": messages, "users": users}


@router.post("/chat")
async def post_chat(req: ChatMessage) -> dict:
    """Send a chat message (records @mentions for notified users)."""
    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: send_message(user, req.message))
    if not ok:
        raise HTTPException(status_code=500, detail="Impossible d'envoyer le message")
    return {"success": True}


@router.get("/chat/mentions")
async def get_chat_mentions(
    request: Request,
    response: Response,
    user: str | None = None,
    unread_only: bool = False,
) -> dict:
    """Return @mentions addressed to *user* (defaults to the current user).

    Conditional GET: ETag from chatMentions.json's stat + the (user, unread_only)
    view. The unread count is over the whole file for *user*, so it is covered by
    the file validator regardless of unread_only.
    """
    who = user or config.get_current_user() or "unknown"
    try:
        path = get_mentions_path()
    except RuntimeError:
        return {"mentions": [], "unread_count": 0}

    validator = file_validator(path)
    etag = _etag(validator, f"m:{who}:{unread_only}") if validator else None
    if etag and _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})

    loop = asyncio.get_event_loop()
    mentions, unread = await loop.run_in_executor(
        None, lambda: get_mentions_and_unread(who, unread_only, path=path),
    )
    if etag:
        response.headers["ETag"] = etag
    return {"mentions": mentions, "unread_count": unread}


@router.post("/chat/mentions/read")
async def read_chat_mentions(req: MentionsReadRequest) -> dict:
    """Mark every mention addressed to the current user as read."""
    who = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: mark_mentions_read(who))
    return {"success": True}
