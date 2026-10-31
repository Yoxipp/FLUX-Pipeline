# team.py — routes of the Team page (ADR 0077), around the team chat of routers/activity.py:
#   GET  /team/{project}/meta            channels, reactions, pins (per author journals, etag)
#   POST /team/{project}/meta            put / del ops (channels and pins: leads; a reaction: its author)
#   POST /team/{project}/files           copy a local file to attach it to a message (ADR 0005)
#   GET  /team/{project}/files/{name}    show / download an attachment
#   GET  /team/presence                  everyone's presence; POST: this artist's own file
#   GET  /team/{project}/discord         live Discord bridge (ADR 0084): link + voice members per channel
#   GET  /team/{project}/mutes           this artist's muted channels / groups; PUT: replace them (P5)

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core import config
from features.team import files, mutes, presence, team_meta
from flux_flows.store import FlowStoreError

router = APIRouter()


def _project_ok(project: str) -> None:
    from features.activity.chat_manager import resolve_chat_path

    try:
        resolve_chat_path(project)
    except ValueError:
        raise HTTPException(status_code=400, detail="Nom de projet invalide")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")
    except RuntimeError:
        raise HTTPException(status_code=409, detail="Workspace FLUX non configure")


def _store_error(exc: FlowStoreError) -> HTTPException:
    return HTTPException(status_code=getattr(exc, "status", 422), detail=str(exc))


@router.get("/presence")
async def get_presence() -> dict[str, Any]:
    try:
        return {"people": await asyncio.to_thread(presence.read_all)}
    except RuntimeError:          # FLUX_ROOT not set yet
        return {"people": []}


class PresenceBody(BaseModel):
    status: str
    text: str = Field(default="", max_length=presence.MAX_TEXT)


@router.post("/presence")
async def post_presence(body: PresenceBody) -> dict[str, Any]:
    user = config.get_current_user() or ""
    try:
        return await asyncio.to_thread(presence.write, user, body.status, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RuntimeError:
        raise HTTPException(status_code=409, detail="Workspace FLUX non configure")


@router.get("/{project}/discord")
async def get_discord(project: str) -> dict[str, Any]:
    """Discord side of the Team channels, from _flux_setup/discord_map.json (written by the bot
    host). Keys are channel rids (or "general"); hidden channels are left out like in /meta."""
    _project_ok(project)
    from features.notify import discord_map, store
    from features.roles import project_roles

    def work() -> dict[str, Any]:
        on = bool(store.read_project(project).get("discord_sync"))
        if not on:
            return {"on": False, "guild": "", "links": {}, "voice": {}, "status": {}}
        data = discord_map.public(project)
        if not project_roles.can(project, "team_channels"):
            records = team_meta.read(project)["records"]
            hidden = team_meta.hidden_channels(project, config.get_current_user() or "", records)
            gone = {r["rid"] for r in records if r.get("kind") == "channel" and r.get("name") in hidden}
            data = {**data, "links": {k: v for k, v in data["links"].items() if k not in gone},
                    "voice": {k: v for k, v in data["voice"].items() if k not in gone}}
        return {"on": True, **data}

    return await asyncio.to_thread(work)


@router.get("/{project}/meta")
async def get_meta(project: str, etag: Optional[str] = None) -> dict[str, Any]:
    _project_ok(project)
    from features.roles import project_roles

    result = await asyncio.to_thread(team_meta.read, project, etag)
    lead = await asyncio.to_thread(project_roles.can, project, "team_channels")
    if result.get("records") is not None and not lead:
        # Channels this artist does not see are left out (their messages too, GET /activity/chat).
        user = config.get_current_user() or ""
        hidden = await asyncio.to_thread(team_meta.hidden_channels, project, user, result["records"])
        if hidden:
            result = {**result, "records": [r for r in result["records"]
                                            if not (r.get("kind") == "channel" and r.get("name") in hidden)]}
    return {**result, "lead": lead, "files_dir": str(files.files_dir(project))}


class MutesBody(BaseModel):
    channels: list[str] = Field(default_factory=list, max_length=mutes.MAX_ITEMS)
    groups: list[str] = Field(default_factory=list, max_length=mutes.MAX_ITEMS)


@router.get("/{project}/mutes")
async def get_mutes(project: str) -> dict[str, Any]:
    _project_ok(project)
    return await asyncio.to_thread(mutes.read, config.get_current_user() or "", project)


@router.put("/{project}/mutes")
async def put_mutes(project: str, body: MutesBody) -> dict[str, Any]:
    _project_ok(project)
    try:
        return await asyncio.to_thread(mutes.write, config.get_current_user() or "", project, body.channels, body.groups)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


class MetaBody(BaseModel):
    ops: list[dict[str, Any]]


@router.post("/{project}/meta")
async def post_meta(project: str, body: MetaBody) -> dict[str, Any]:
    _project_ok(project)
    from features.roles import project_roles

    user = config.get_current_user() or ""

    def work() -> dict[str, Any]:
        return team_meta.write(project, body.ops, user=user, is_lead=project_roles.can(project, "team_channels"))

    try:
        return await asyncio.to_thread(work)
    except FlowStoreError as exc:
        raise _store_error(exc)


class AttachBody(BaseModel):
    path: str            # a local file the artist picked or dropped (copied, never uploaded: ADR 0005)


@router.post("/{project}/files")
async def post_file(project: str, body: AttachBody) -> dict[str, Any]:
    _project_ok(project)
    try:
        return await asyncio.to_thread(files.attach, files.files_dir(project), body.path)
    except files.AttachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/{project}/files/{name}")
async def get_file(project: str, name: str) -> FileResponse:
    _project_ok(project)
    try:
        path = await asyncio.to_thread(files.file_path, files.files_dir(project), name)
    except files.AttachError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return FileResponse(path)
