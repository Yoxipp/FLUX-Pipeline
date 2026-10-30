# notify.py - phone notification settings (ADR 0062). Secrets come out masked;
# the ntfy topic is shown in full to its owner only (QR code).

from __future__ import annotations

import asyncio
import time

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
            "project_has_bot": bool(cfg.get("discord_bot")), "discord_linked": store.is_linked(prefs),
            "has_channel": store.has_channel(prefs, cfg), **dispatch.quota_status()}


class LinkRequest(BaseModel):
    code: str


@router.post("/me/discord_link")
async def link_discord(req: LinkRequest, project: str) -> dict:
    """A /link code from the project's bot proves the Discord id (ADR 0073)."""
    user = _user()
    _ensure_project(project)
    try:
        prefs = await _io(lambda: store.link_discord(project, user, req.code, time.time()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    log.info("discord account linked for %s", user)
    cfg = await _io(lambda: store.read_project(project))
    return {"prefs": store.public_user(prefs, cfg["ntfy_server"]), "has_channel": store.has_channel(prefs, cfg)}


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
            "can_edit": project_roles.can(project, "project_settings"),
            "bot": await _io(lambda: _bot_status(project, cfg))}


def _bot_status(project: str, cfg: dict) -> dict:
    from features.notify import discord_bot
    info = cfg.get("discord_bot") or {}
    if not info:
        return {"configured": False}
    return {"configured": True, "name": info.get("name", ""), "host": info.get("host", ""),
            "hosted_here": bool(discord_bot.hosted_token(project)),
            "online": store.bot_alive(project, time.time()),
            "invite_url": discord_bot.invite_url(info.get("app_id", ""))}


class BotRequest(BaseModel):
    token: str


@router.put("/project/{project}/bot")
async def put_bot(project: str, req: BotRequest) -> dict:
    """Host the project's bot on THIS PC: the token stays here, encrypted (ADR 0073)."""
    _ensure_project(project)
    _require_role(project)
    user = _user()
    from features.notify import bot_secret, discord_bot
    token = req.token.strip()
    try:
        info = await _io(lambda: discord_bot.check_token(token))
        await _io(lambda: bot_secret.save_token(project, token))
    except (ValueError, bot_secret.SecretError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    discord_bot.stop(project)
    cfg = await _io(lambda: store.set_bot(project, {**info, "host": discord_bot.host_name()}, user))
    discord_bot.start(project)
    log.info("discord bot of %s hosted here, set by %s", project, user)
    return {"bot": await _io(lambda: _bot_status(project, cfg))}


@router.delete("/project/{project}/bot")
async def delete_bot(project: str) -> dict:
    _ensure_project(project)
    _require_role(project)
    user = _user()
    from features.notify import bot_secret, discord_bot
    discord_bot.stop(project)
    await _io(lambda: bot_secret.delete_token(project))
    cfg = await _io(lambda: store.set_bot(project, None, user))
    log.info("discord bot of %s removed by %s", project, user)
    return {"bot": _bot_status(project, cfg)}


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
