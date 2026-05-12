# routers/settings.py — user prefs + workspace init endpoints.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pathlib import Path

from core import config
from core.constants import FLUX_MARKER_FILENAME, FLUX_ROOT_DIRS
from core.logger import get_logger
from core.paths import ensure_dir, get_flux_root, set_config_username, set_flux_root

log = get_logger(__name__)
router = APIRouter()


class InitRequest(BaseModel):
    workspace: str
    username: str


class SettingsUpdate(BaseModel):
    theme_bg: str | None = None
    theme_surface: str | None = None
    theme_fg: str | None = None
    theme_accent: str | None = None
    last_project: str | None = None
    dcc_path: dict | None = None   # {"Maya": "C:/path/maya.exe", ...}
    username: str | None = None


@router.get("")
async def get_settings() -> dict:
    """Return current settings + first-launch state."""
    loop = asyncio.get_event_loop()
    is_first = await loop.run_in_executor(None, config.is_first_launch)
    root = get_flux_root()
    user = config.get_current_user()
    theme = await loop.run_in_executor(None, config.get_theme)
    last_proj = await loop.run_in_executor(None, config.get_last_project)

    dcc_paths = await loop.run_in_executor(None, lambda: config.get("dcc_paths", {}))

    return {
        "first_launch": is_first,
        "workspace":    str(root) if root else None,
        "username":     user,
        "theme":        theme,
        "last_project": last_proj,
        "dcc_paths":    dcc_paths,
    }


@router.post("/init")
async def init_first_launch(req: InitRequest) -> dict:
    """First-launch setup: scaffold FLUX root structure, persist workspace + username."""
    def _scaffold():
        root = Path(req.workspace)
        for d in FLUX_ROOT_DIRS:
            ensure_dir(root / d)
        (root / FLUX_MARKER_FILENAME).touch()
        # Écrire workspace dans les deux emplacements :
        # - config.json (next to exe, lu par get_flux_root())
        # - prefs.json  (AppData, lu par config._load())
        set_flux_root(root)
        config.create_user(req.username, req.workspace)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _scaffold)
    return {"success": True, "workspace": req.workspace, "username": req.username}


@router.put("")
async def update_settings(req: SettingsUpdate) -> dict:
    """Update one or more settings fields."""
    loop = asyncio.get_event_loop()

    if req.theme_bg or req.theme_surface or req.theme_fg or req.theme_accent:
        current = await loop.run_in_executor(None, config.get_theme)
        await loop.run_in_executor(
            None,
            lambda: config.set_theme(
                req.theme_bg      or current["bg"],
                req.theme_surface or current["surface"],
                req.theme_fg      or current["fg"],
                req.theme_accent  or current["accent"],
            ),
        )

    if req.last_project is not None:
        await loop.run_in_executor(None, lambda: config.set_last_project(req.last_project))

    if req.dcc_path:
        for dcc_name, path in req.dcc_path.items():
            await loop.run_in_executor(None, lambda d=dcc_name, p=path: config.set_dcc_exe(d, p))

    if req.username:
        await loop.run_in_executor(None, lambda: set_config_username(req.username))
        config.set_current_user(req.username)
        log.info("User switched to '%s'", req.username)

    return {"success": True}


@router.get("/users")
async def list_users() -> dict:
    """Return existing usernames (for first-launch suggestions)."""
    from utils.user_utils import list_users as _list
    loop = asyncio.get_event_loop()
    users = await loop.run_in_executor(None, _list)
    return {"users": users}
