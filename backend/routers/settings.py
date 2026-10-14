# routers/settings.py — user prefs + workspace init endpoints.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pathlib import Path

from core import config
from core.constants import FLUX_MARKER_FILENAME, FLUX_ROOT_DIRS
from features.system.manual import ensure_manual_in_root
from core.logger import get_logger
from core.repository_factory import reset_repository, reset_storage
from core.paths import ensure_dir, get_flux_root, set_config_username, set_flux_root
from utils import user_utils

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
    workspace: str | None = None   # change le répertoire du pipe
    language: str | None = None    # UI language: "fr" | "en"
    log_colors: dict | None = None  # console log-color overrides {level: color}


@router.get("")
async def get_settings() -> dict:
    """Return current settings + first-launch state."""
    loop = asyncio.get_running_loop()
    is_first = await loop.run_in_executor(None, config.is_first_launch)
    root = get_flux_root()
    user = config.get_current_user()
    theme = await loop.run_in_executor(None, config.get_theme)
    last_proj = await loop.run_in_executor(None, config.get_last_project)

    dcc_paths = await loop.run_in_executor(None, lambda: config.get("dcc_paths", {}))
    language = await loop.run_in_executor(None, lambda: config.get("language", "fr"))
    log_colors = await loop.run_in_executor(None, config.get_log_colors)

    return {
        "first_launch": is_first,
        "workspace":    str(root) if root else None,
        "username":     user,
        "theme":        theme,
        "last_project": last_proj,
        "dcc_paths":    dcc_paths,
        "language":     language,
        "log_colors":   log_colors,
    }


@router.post("/init")
async def init_first_launch(req: InitRequest) -> dict:
    """First-launch setup: scaffold FLUX root structure, persist workspace + username."""
    # Artist names are always stored/displayed in FULL UPPERCASE (frontend + backend).
    username = req.username.strip().upper()

    def _scaffold():
        root = Path(req.workspace)
        for d in FLUX_ROOT_DIRS:
            ensure_dir(root / d)
        (root / FLUX_MARKER_FILENAME).touch()
        ensure_manual_in_root(root)
        # Bootstrap keys go into config.json (next to exe / %APPDATA%/FluxPipeline/
        # when frozen) because is_first_launch reads that file directly - it must NOT
        # depend on the metadata repository, whose location depends on the workspace.
        # When frozen, config.json and prefs.json are two different files, so writing
        # only to prefs.json (via create_user) would leave the wizard looping forever.
        set_flux_root(root)
        set_config_username(username)
        config.create_user(username, req.workspace)

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _scaffold)
    except Exception as exc:
        log.error("init_first_launch failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"success": True, "workspace": req.workspace, "username": username}


@router.put("")
async def update_settings(req: SettingsUpdate) -> dict:
    """Update one or more settings fields."""
    loop = asyncio.get_running_loop()

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

    if req.language:
        lang = req.language if req.language in ("fr", "en") else "fr"
        await loop.run_in_executor(None, lambda: config.set("language", lang))

    if req.log_colors is not None:
        await loop.run_in_executor(None, lambda: config.set_log_colors(req.log_colors))

    if req.dcc_path:
        for dcc_name, path in req.dcc_path.items():
            await loop.run_in_executor(None, lambda d=dcc_name, p=path: config.set_dcc_exe(d, p))

    if req.username:
        # Artist names are always stored/displayed in FULL UPPERCASE (frontend + backend).
        new_user = req.username.strip().upper()
        # set_current_user crée le dossier FLUX_ROOT/USER/<name>/ en plus de persister
        await loop.run_in_executor(None, lambda: user_utils.set_current_user(new_user))
        await loop.run_in_executor(None, lambda: set_config_username(new_user))
        log.info("User switched to '%s'", new_user)

    if req.workspace:
        def _update_workspace():
            ws = Path(req.workspace)
            for d in FLUX_ROOT_DIRS:
                ensure_dir(ws / d)
            (ws / FLUX_MARKER_FILENAME).touch(exist_ok=True)
            ensure_manual_in_root(ws)
            # Forget the previous root's projects and restore this root's own prefs;
            # the cached metadata/storage backends are bound to the old root, drop them.
            old_root = get_flux_root()
            if old_root:
                config.stash_workspace_prefs(str(old_root))
            set_flux_root(ws)
            reset_repository()
            reset_storage()
            config.set("workspace", str(ws))
            config.restore_workspace_prefs(str(ws))
        await loop.run_in_executor(None, _update_workspace)
        log.info("Workspace changed to '%s'", req.workspace)

    return {"success": True}


@router.get("/users")
async def list_users() -> dict:
    """Return existing usernames (for first-launch suggestions)."""
    from utils.user_utils import list_users as _list
    loop = asyncio.get_running_loop()
    users = await loop.run_in_executor(None, _list)
    return {"users": users}


class UserRenameRequest(BaseModel):
    old: str
    new: str


@router.put("/users/rename")
async def rename_user_endpoint(req: UserRenameRequest) -> dict:
    """Rename an artist (renames their USER folder; active user follows)."""
    loop = asyncio.get_running_loop()
    ok, msg = await loop.run_in_executor(None, lambda: user_utils.rename_user(req.old, req.new))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@router.delete("/users/{name}")
async def delete_user_endpoint(name: str) -> dict:
    """Delete an artist and their data (refuses the active user)."""
    loop = asyncio.get_running_loop()
    ok, msg = await loop.run_in_executor(None, lambda: user_utils.delete_user(name))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


# ── Per-user data blob (favorites / recents / archived, …) ────────────────────

@router.get("/user-data")
async def get_user_data() -> dict:
    """Return the active user's settings blob (USER/<user>/UserSettings/User.json)."""
    user = config.get_current_user()
    if not user:
        return {}
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: user_utils.read_user_data(user))


@router.put("/user-data")
async def put_user_data(patch: dict) -> dict:
    """Merge *patch* into the active user's settings blob and persist it."""
    user = config.get_current_user()
    if not user:
        raise HTTPException(status_code=400, detail="Aucun utilisateur actif")

    def _merge() -> dict:
        data = user_utils.read_user_data(user)
        data.update(patch)
        user_utils.write_user_data(user, data)
        return data

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _merge)


# ── Enabled DCCs per user (V8 U10) ────────────────────────────────────────────

class EnabledDccsUpdate(BaseModel):
    enabled: list[str] | None = None   # None = reset (all DCCs enabled)


def _known_dcc_keys() -> set[str]:
    from features.launcher.launcher_core import DCC_FRONTEND_KEYS
    return set(DCC_FRONTEND_KEYS)


@router.get("/enabled-dccs")
async def get_enabled_dccs() -> dict:
    """Return {known, enabled}; enabled is None when the user never chose (= all)."""
    user = config.get_current_user()
    known = sorted(_known_dcc_keys())
    if not user:
        return {"known": known, "enabled": None}
    loop = asyncio.get_running_loop()
    enabled = await loop.run_in_executor(None, lambda: user_utils.get_enabled_dccs(user))
    return {"known": known, "enabled": enabled}


@router.put("/enabled-dccs")
async def put_enabled_dccs(req: EnabledDccsUpdate) -> dict:
    """Persist the active user's enabled DCC keys in USER/<user>/ (User.json)."""
    user = config.get_current_user()
    if not user:
        raise HTTPException(status_code=400, detail="Aucun utilisateur actif")
    known = _known_dcc_keys()
    loop = asyncio.get_running_loop()
    try:
        enabled = await loop.run_in_executor(
            None, lambda: user_utils.set_enabled_dccs(user, req.enabled, known)
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"known": sorted(known), "enabled": enabled}


# ── Parametres avances (N8) ───────────────────────────────────────────────────

class AdvancedProjectUpdate(BaseModel):
    project: str
    values: dict


class AdvancedSwitchesUpdate(BaseModel):
    values: dict        # {name: value, or null to go back to the default}


@router.get("/advanced")
async def get_advanced(project: str | None = None) -> dict:
    """project.json settings of *project* (or the last project) + this machine's publish switches."""
    from core.paths import get_project_path
    from features.settings.advanced import read_project_settings, read_switches

    loop = asyncio.get_running_loop()
    name = project or config.get_last_project()
    proj = None
    if name and get_project_path(name).exists():
        proj = await loop.run_in_executor(None, lambda: read_project_settings(get_project_path(name)))
        proj["name"] = name
    return {"project": proj, "switches": await loop.run_in_executor(None, read_switches)}


@router.put("/advanced/project")
async def put_advanced_project(req: AdvancedProjectUpdate) -> dict:
    """Write the project.json settings (validated; nothing written on error)."""
    from core.paths import get_project_path
    from features.settings.advanced import write_project_settings

    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: write_project_settings(project_path, req.values))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    res["name"] = req.project
    return res


@router.put("/advanced/switches")
async def put_advanced_switches(req: AdvancedSwitchesUpdate) -> dict:
    """Save and apply the publish switches of this machine (decision D1)."""
    from features.settings.advanced import save_switches

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: save_switches(req.values))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
