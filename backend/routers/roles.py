# roles.py - artists' roles on a project (ADR 0064): read, change, claim when none.
#
# The acting user is always the one of the local config, never the request body.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from features.roles import project_roles
from utils import project_utils, user_utils

router = APIRouter()


def _ensure_project(project: str) -> None:
    if not project_utils.project_exists(project):
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")


class RoleChange(BaseModel):
    user: str
    role: str


@router.get("/{project}")
async def get_roles(project: str) -> dict:
    _ensure_project(project)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: project_roles.summary(project, user_utils.list_users()))


@router.put("/{project}")
async def put_role(project: str, body: RoleChange) -> dict:
    _ensure_project(project)
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: project_roles.set_role(project, body.user, body.role))
    except project_roles.RoleError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return await loop.run_in_executor(None, lambda: project_roles.summary(project, user_utils.list_users()))


@router.post("/{project}/claim")
async def claim(project: str) -> dict:
    _ensure_project(project)
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: project_roles.claim_supervisor(project))
    except project_roles.RoleError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return await loop.run_in_executor(None, lambda: project_roles.summary(project, user_utils.list_users()))
