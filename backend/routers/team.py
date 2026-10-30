# team.py — routes of the Team page (ADR 0077), around the team chat of routers/activity.py:
#   GET  /team/{project}/meta            channels, reactions, pins (per author journals, etag)
#   POST /team/{project}/meta            put / del ops (channels and pins: leads; a reaction: its author)
#   POST /team/{project}/files           copy a local file to attach it to a message (ADR 0005)
#   GET  /team/{project}/files/{name}    show / download an attachment
#   GET  /team/presence                  everyone's presence; POST: this artist's own file

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core import config
from features.team import files, presence, team_meta
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


@router.get("/{project}/meta")
async def get_meta(project: str, etag: Optional[str] = None) -> dict[str, Any]:
    _project_ok(project)
    from features.roles import project_roles

    result = await asyncio.to_thread(team_meta.read, project, etag)
    lead = await asyncio.to_thread(project_roles.can, project, "team_channels")
    return {**result, "lead": lead, "files_dir": str(files.files_dir(project))}


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
