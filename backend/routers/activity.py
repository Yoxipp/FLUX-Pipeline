# routers/activity.py — activity feed + team chat endpoints.

from __future__ import annotations

import asyncio
import hashlib

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from core import config
from core.constants import ARCHIVE_STEM_ACTIVITY, ARCHIVE_STEM_MENTIONS
from core.json_manager import file_validator, stat_sig
from core.logger import get_logger
from core.paths import (
    get_activity_path, get_activity_read_path,
    get_mentions_path, get_mentions_read_path, get_users_dir,
)
from core.repository_factory import get_repository
from features.activity.activity_reader import (
    get_events_and_unread, mark_all_as_read, mark_as_read,
)
from features.activity.history import read_archive_events
from features.activity.chat_manager import (
    get_mentions_and_unread, get_messages, get_user_list,
    mark_mentions_read, resolve_chat_path, send_message,
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
    project: str


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

    sig = stat_sig(path)
    # ETag validators come from the repository, not a raw file stat: under the
    # SQLite backend the log and the read-status live in the base, not on disk, so
    # activite.json's mtime is frozen while the data changes — a stat-based ETag
    # would then 304 forever (mark-read looked dead, new events never surfaced).
    # version_token tracks the data on every backend (== the old stat token for
    # JSON). Read-status is folded in so marking-read invalidates the cached 304
    # even though the event log itself is unchanged.
    repo = get_repository()
    log_tok = repo.version_token("activity_log", str(path))
    read_tok = repo.version_token("read_state", str(get_activity_read_path()))
    # "0" == nothing stored yet → no ETag, always fetch (matches the pre-frontier
    # "missing file → no validator" behaviour, now backend-agnostic).
    etag = (
        _etag(log_tok, f"a:{limit}:{user}:{action}:{project}:{read_tok}")
        if log_tok != "0" else None
    )
    if etag and _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})

    loop = asyncio.get_running_loop()
    events, unread = await loop.run_in_executor(
        None,
        lambda: get_events_and_unread(
            limit=limit, user=user, action=action, project=project, path=path, sig=sig,
        ),
    )
    if etag:
        response.headers["ETag"] = etag
    return {"events": events, "unread_count": unread}


@router.get("/history")
async def get_activity_history(limit: int = 200, offset: int = 0, kind: str = "activity") -> dict:
    """Return older, rotated events from the cold archives — on demand only.

    This never runs on the polling path; the Activity page calls it when the
    user asks to load history beyond the bounded hot file. *kind* selects the
    feed ("activity" or "mentions").
    """
    stem = ARCHIVE_STEM_MENTIONS if kind == "mentions" else ARCHIVE_STEM_ACTIVITY
    loop = asyncio.get_running_loop()
    try:
        events, has_more = await loop.run_in_executor(
            None, lambda: read_archive_events(stem, limit, offset),
        )
    except RuntimeError:
        return {"events": [], "has_more": False}
    return {"events": events, "has_more": has_more}


@router.post("/read")
async def mark_read(req: MarkReadRequest) -> dict:
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, lambda: mark_as_read(req.event_id))
    if not ok:
        raise HTTPException(status_code=404, detail="Événement introuvable")
    return {"success": True}


@router.post("/read-all")
async def mark_all_read() -> dict:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, mark_all_as_read)
    return {"success": True}


@router.get("/chat")
async def get_chat(
    request: Request, response: Response, limit: int = 100, project: str | None = None,
) -> dict:
    """Return the last *limit* messages of *project*'s team chat.

    Each project has its own chat (DOSSIER_PROJETS/<project>/teamChat.json).
    Returns empty messages (not 500) when FLUX_ROOT is not yet set, no project is
    given or the project does not exist; the user list is still returned.

    Conditional GET: the ETag reflects teamChat.json *and* the USER directory's
    stat — the latter because the response also carries the @-autocomplete user
    list, so adding/removing a user must invalidate the cached view too.
    """
    try:
        users_validator = file_validator(get_users_dir())
    except RuntimeError:
        return {"messages": [], "users": []}
    try:
        chat_path = resolve_chat_path(project)
    except (ValueError, FileNotFoundError, RuntimeError):
        loop = asyncio.get_running_loop()
        return {"messages": [], "users": await loop.run_in_executor(None, get_user_list)}

    # Chat log validator via the repository (SQLite-safe: teamChat.json's mtime is
    # frozen under the DB backend, so a raw file stat would 304 forever and new
    # messages would never appear). The USER dir stat stays a real filesystem
    # validator — the @-autocomplete list is folders on disk, not a repo doc.
    validator = get_repository().version_token("chat_log", str(chat_path))
    etag = _etag(validator, f"c:{project}:{limit}:{users_validator}") if validator != "0" else None
    if etag and _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})

    loop = asyncio.get_running_loop()
    # get_messages caches internally (burst window); the stat above is the ETag's.
    messages = await loop.run_in_executor(None, lambda: get_messages(limit=limit, path=chat_path))
    users = await loop.run_in_executor(None, get_user_list)
    if etag:
        response.headers["ETag"] = etag
    return {"messages": messages, "users": users}


@router.post("/chat")
async def post_chat(req: ChatMessage) -> dict:
    """Send a message to *project*'s team chat (records @mentions for notified users)."""
    user = req.user or config.get_current_user() or "unknown"
    try:
        resolve_chat_path(req.project)
    except ValueError:
        raise HTTPException(status_code=400, detail="Nom de projet invalide")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")
    except RuntimeError:
        raise HTTPException(status_code=409, detail="Workspace FLUX non configure")
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(
        None, lambda: send_message(user, req.message, project=req.project),
    )
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

    sig = stat_sig(path)
    # Repository-derived validators (SQLite-safe, like /activity above): the log
    # token + the read-status token, so a mark-read invalidates the cached 304.
    repo = get_repository()
    log_tok = repo.version_token("mentions_log", str(path))
    read_tok = repo.version_token("read_state", str(get_mentions_read_path()))
    etag = _etag(log_tok, f"m:{who}:{unread_only}:{read_tok}") if log_tok != "0" else None
    if etag and _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})

    loop = asyncio.get_running_loop()
    mentions, unread = await loop.run_in_executor(
        None, lambda: get_mentions_and_unread(who, unread_only, path=path, sig=sig),
    )
    if etag:
        response.headers["ETag"] = etag
    return {"mentions": mentions, "unread_count": unread}


@router.post("/chat/mentions/read")
async def read_chat_mentions(req: MentionsReadRequest) -> dict:
    """Mark every mention addressed to the current user as read."""
    who = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: mark_mentions_read(who))
    return {"success": True}
