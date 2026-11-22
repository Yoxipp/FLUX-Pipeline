# notify.py - notification settings (ADR 0062, Discord only since ADR 0091). The webhook
# comes out masked.

from __future__ import annotations

import asyncio
import subprocess
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
    muted: list[str] | None = None        # event types turned off (ADR 0091)


@router.get("/me")
async def get_me(project: str = "") -> dict:
    user = _user()
    cfg = await _io(lambda: store.read_project(project)) if project else dict(store.PROJECT_DEFAULTS)
    prefs = await _io(lambda: store.read_user(user))
    return {"user": user, "prefs": store.public_user(prefs),
            "project_has_webhook": bool(cfg.get("discord_webhook")),
            "project_has_bot": bool(cfg.get("discord_bot")), "discord_linked": store.is_linked(prefs),
            "has_channel": store.has_channel(prefs, cfg)}


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
    return {"prefs": store.public_user(prefs), "has_channel": store.has_channel(prefs, cfg)}


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
    return {"prefs": store.public_user(prefs), "has_channel": store.has_channel(prefs, cfg)}


@router.post("/me/test")
async def test_me(project: str = "") -> dict:
    user = _user()
    if project:
        _ensure_project(project)
    return await _io(lambda: dispatch.send_test(project, user))


# ── project ───────────────────────────────────────────────────────────────────

class ProjectPatch(BaseModel):
    discord_webhook: str | None = None
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
    from features.notify import bot_host, bot_secret, discord_bot
    info = cfg.get("discord_bot") or {}
    if not info:
        return {"configured": False}
    # hosted_here = the token is on this PC (the bot may run in this FLUX or headless, ADR 0076).
    # ADR 0082: several PCs may hold the token; host = the one answering now (else the first
    # that registered the bot), candidates = the others ready to take over.
    now = time.time()
    host_now = store.bot_host_now(project, now)
    return {"configured": True, "name": info.get("name", ""), "host": host_now or info.get("host", ""),
            "hosted_here": project in bot_secret.hosted_projects(),
            "online": bool(host_now),
            "is_host": discord_bot.is_host(project),
            "this_pc": discord_bot.host_name(),
            "candidates": [h for h in store.bot_candidates(project, now) if h != host_now],
            "invite_url": discord_bot.invite_url(info.get("app_id", "")),
            **bot_host.status()}


class BotRequest(BaseModel):
    token: str


@router.put("/project/{project}/bot")
async def put_bot(project: str, req: BotRequest) -> dict:
    """Host the project's bot on THIS PC: the token stays here, encrypted (ADR 0073). The bot
    already registered: this PC becomes a candidate that takes over when the host leaves (0082)."""
    _ensure_project(project)
    _require_role(project)
    user = _user()
    from features.notify import bot_secret, discord_bot
    token = req.token.strip()
    try:
        info = await _io(lambda: discord_bot.check_token(token))
        current = (await _io(lambda: store.read_project(project))).get("discord_bot") or {}
        if current and current.get("app_id") and current.get("app_id") != info.get("app_id"):
            raise HTTPException(status_code=409, detail=f"Ce jeton est celui d'un autre bot que {current.get('name') or 'celui du projet'} : "
                                                        "colle le jeton du meme bot, ou retire d'abord le bot du projet")
        await _io(lambda: bot_secret.save_token(project, token))
    except (ValueError, bot_secret.SecretError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    discord_bot.stop(project)
    if current:
        cfg = await _io(lambda: store.read_project(project))
    else:
        cfg = await _io(lambda: store.set_bot(project, {**info, "host": discord_bot.host_name()}, user))
    discord_bot.start(project)
    log.info("discord bot of %s %s, set by %s", project, "candidate here" if current else "hosted here", user)
    return {"bot": await _io(lambda: _bot_status(project, cfg))}


class BackgroundRequest(BaseModel):
    enabled: bool


@router.put("/project/{project}/bot/background")
async def put_bot_background(project: str, req: BackgroundRequest) -> dict:
    """Keep the bots of THIS PC online when FLUX is closed (ADR 0076): a shortcut in the
    user's Startup folder runs `--discord-bot`. Only on the PC that holds the token."""
    _ensure_project(project)
    from features.notify import bot_host, bot_secret, discord_bot
    if project not in bot_secret.hosted_projects():
        raise HTTPException(status_code=400, detail="Le bot de ce projet n'est pas heberge sur ce PC")
    try:
        if req.enabled:
            await _io(bot_host.install_startup)
            discord_bot.stop_all()              # hand over to the headless process
            await _io(bot_host.spawn)
        else:
            await _io(bot_host.remove_startup)
            await _io(bot_host.stop_headless)
            discord_bot.start_all()             # back in this FLUX
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("discord bot background %s failed: %s", "on" if req.enabled else "off", type(exc).__name__)
        raise HTTPException(status_code=500, detail="FLUX n'a pas pu changer le demarrage du bot sur ce PC")
    log.info("discord bot background %s on this PC", "on" if req.enabled else "off")
    cfg = await _io(lambda: store.read_project(project))
    return {"bot": await _io(lambda: _bot_status(project, cfg))}


@router.delete("/project/{project}/bot")
async def delete_bot(project: str, this_pc_only: bool = False) -> dict:
    """Remove the bot from the project (every PC stops), or with *this_pc_only* only take this
    PC out of the hosts (its token is deleted, another PC keeps the bot, ADR 0082)."""
    _ensure_project(project)
    _require_role(project)
    user = _user()
    from features.notify import bot_secret, discord_bot
    discord_bot.stop(project)
    await _io(lambda: bot_secret.delete_token(project))
    if this_pc_only:
        await _io(lambda: store.drop_candidate(project, discord_bot.host_name()))
        log.info("discord bot of %s: this PC is no longer a host (%s)", project, user)
        cfg = await _io(lambda: store.read_project(project))
        return {"bot": await _io(lambda: _bot_status(project, cfg))}
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
    return {"queued": len(items), "enabled": dispatch.enabled()}
