# routers/activity.py — activity feed + team chat endpoints.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.logger import get_logger
from features.activity.activity_reader import (
    get_all_events, get_unread_count, mark_all_as_read, mark_as_read,
)
from features.activity.chat_manager import get_messages, get_user_list, send_message

log = get_logger(__name__)
router = APIRouter()


class ChatMessage(BaseModel):
    user: str | None = None
    message: str


class MarkReadRequest(BaseModel):
    event_id: str


@router.get("")
async def get_activity(
    limit: int = 50,
    user: str | None = None,
    action: str | None = None,
    project: str | None = None,
) -> dict:
    """Return activity events with optional filters."""
    loop = asyncio.get_event_loop()
    events = await loop.run_in_executor(
        None, lambda: get_all_events(limit=limit, user=user, action=action, project=project)
    )
    unread = await loop.run_in_executor(None, get_unread_count)
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
async def get_chat(limit: int = 100) -> dict:
    """Return the last *limit* chat messages."""
    loop = asyncio.get_event_loop()
    messages = await loop.run_in_executor(None, lambda: get_messages(limit=limit))
    users = await loop.run_in_executor(None, get_user_list)
    return {"messages": messages, "users": users}


@router.post("/chat")
async def post_chat(req: ChatMessage) -> dict:
    """Send a chat message."""
    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: send_message(user, req.message))
    if not ok:
        raise HTTPException(status_code=500, detail="Impossible d'envoyer le message")
    return {"success": True}
