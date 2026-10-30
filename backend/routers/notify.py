# notify.py - phone notification settings (ADR 0062). Secrets come out masked;
# the ntfy topic is shown in full to its owner only (QR code).

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.logger import get_logger
from features.notify import dispatch, outbox, store
from utils import project_utils

log = get_logger(__name__)
router = APIRouter()


def _user() -> str:
    user = config.get_current_user()
    if not user:
        raise HTTPException(status_code=401, detail="Aucun utilisateur connecte")
    return user


def _ensure_project(project: str) -> None:
    if not project_utils.project_exists(project):
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")


def _require_role(project: str) -> None:
    from features.roles import project_roles
    try:
        project_roles.require(project, "project_settings")
    except project_roles.RoleError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


async def _io(fn):
    return await asyncio.get_running_loop().run_in_executor(None, fn)


# ── person ────────────────────────────────────────────────────────────────────

class UserPatch(BaseModel):
    channel: str | None = None
    discord_id: str | None = None
    regenerate_topic: bool = False


@router.get("/me")
async def get_me(project: str = "") -> dict:
    user = _user()
    cfg = await _io(lambda: store.read_project(project)) if project else dict(store.PROJECT_DEFAULTS)
    prefs = await _io(lambda: store.read_user(user))
    return {"user": user, "prefs": store.public_user(prefs, cfg["ntfy_server"]),
            "project_has_webhook": bool(cfg.get("discord_webhook")),
            "has_channel": store.has_channel(prefs, cfg), **dispatch.quota_status()}


@router.put("/me")
async def put_me(patch: UserPatch, project: str = "") -> dict:
    user = _user()
    try:
        prefs = await _io(lambda: store.write_user(user, patch.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    cfg = await _io(lambda: store.read_project(project)) if project else dict(store.PROJECT_DEFAULTS)
    return {"prefs": store.public_user(prefs, cfg["ntfy_server"]), "has_channel": store.has_channel(prefs, cfg)}


@router.post("/me/test")
async def test_me(project: str = "") -> dict:
    user = _user()
    if project:
        _ensure_project(project)
    return await _io(lambda: dispatch.send_test(project, user))


# ── project ───────────────────────────────────────────────────────────────────

class ProjectPatch(BaseModel):
    discord_webhook: str | None = None
    ntfy_server: str | None = None
    digest_minutes: int | None = None
    include_project: bool | None = None
    include_text: bool | None = None


def _without_channel(cfg: dict) -> list[str]:
    from utils.user_utils import list_users
    return [name for name in list_users() if not store.has_channel(store.read_user(name), cfg)]


@router.get("/project/{project}")
async def get_project(project: str) -> dict:
    _ensure_project(project)
    from features.roles import project_roles
    cfg = await _io(lambda: store.read_project(project))
    missing = await _io(lambda: _without_channel(cfg))
    return {"settings": store.public_project(cfg), "without_channel": missing,
            "can_edit": project_roles.can(project, "project_settings")}


@router.put("/project/{project}")
async def put_project(project: str, patch: ProjectPatch) -> dict:
    _ensure_project(project)
    _require_role(project)
    user = _user()
    try:
        cfg = await _io(lambda: store.write_project(project, patch.model_dump(), user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    log.info("notify settings of %s changed by %s", project, user)
    return {"settings": store.public_project(cfg)}


@router.get("/status")
async def status() -> dict:
    items = await _io(outbox.load)
    return {"queued": len(items), "enabled": dispatch.enabled(), **dispatch.quota_status()}
