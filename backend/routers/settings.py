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
from core.paths import (
    add_flux_root, ensure_dir, get_flux_root, get_flux_roots, remove_flux_root,
    same_root, set_config_username, set_flux_root,
)
from utils import user_utils

log = get_logger(__name__)
router = APIRouter()


class InitRequest(BaseModel):
    workspace: str
    username: str = ""             # existing artist picked in the wizard
    first_name: str | None = None  # new artist: identifier built from first + last name
    last_name: str | None = None
    password: str | None = None    # new artist: optional; existing artist: its password
    remember: bool = False         # "Se souvenir sur ce PC"


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
    password: str | None = None     # password of the artist switched to, if it has one
    remember: bool = False          # remember that artist on this PC


def _taken_names() -> set[str]:
    """Current artists and retired names: never given to a new artist."""
    from features.accounts import aliases
    return set(user_utils.list_users()) | set(aliases.load_aliases())


def _check_can_enter(name: str, password: str | None, remember: bool) -> None:
    """403 when *name* has a password that was not given (and is not remembered here).

    A supervisor of the active project, or someone coming back to his own account, needs
    none: the local identity then stays his. Any other entry makes *name* that identity.
    """
    from features.accounts import passwords, sup_access
    if not user_utils.user_exists(name):
        sup_access.set_local_identity(name)
        return
    if sup_access.enter_without_password(name):
        return
    if not passwords.can_enter(name, password):
        raise HTTPException(status_code=403, detail="Mot de passe incorrect.")
    if remember and password:
        passwords.remember_on_this_pc(name)
    sup_access.set_local_identity(name)


def _refuse_during_sup_entry(project_name: str | None = None) -> None:
    """403 while a supervisor is inside another account, outside the project of that entry."""
    from features.accounts import sup_access
    refused = sup_access.refusal(project_name)
    if refused:
        raise HTTPException(status_code=403, detail=refused)


def _require_role(project: str | None, action: str) -> None:
    """403 unless the active user holds the role *action* needs on *project*."""
    if not project:
        raise HTTPException(status_code=403, detail="Ouvre un projet : cette action dépend de ton rôle.")
    try:
        from features.roles import project_roles
        project_roles.require(project, action)
    except ImportError:
        raise HTTPException(status_code=403, detail="Rôles indisponibles.")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


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
    from features.accounts import sup_access
    sup_entry = await loop.run_in_executor(None, sup_access.current_entry)

    return {
        "sup_entry":    sup_entry,
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
    from features.accounts import identity, passwords, sup_access

    def _scaffold():
        root = Path(req.workspace)
        set_flux_root(root)   # users and aliases live under the chosen root
        sup_access.forget()
        new_artist = bool(req.first_name or req.last_name)
        if new_artist:
            username = identity.make_user_id(req.first_name or "", req.last_name or "", _taken_names())
            if req.password:
                passwords.validate_new_password(req.password)
        else:
            username = req.username.strip().upper()
            if not user_utils.is_valid_user_name(username):
                raise ValueError(f"Nom d'artiste invalide : {username}")
            _check_can_enter(username, req.password, req.remember)
        for d in FLUX_ROOT_DIRS:
            ensure_dir(root / d)
        (root / FLUX_MARKER_FILENAME).touch()
        ensure_manual_in_root(root)
        # Bootstrap keys go into config.json (next to exe / %APPDATA%/FluxPipeline/
        # when frozen) because is_first_launch reads that file directly - it must NOT
        # depend on the metadata repository, whose location depends on the workspace.
        # When frozen, config.json and prefs.json are two different files, so writing
        # only to prefs.json (via create_user) would leave the wizard looping forever.
        set_config_username(username)
        config.create_user(username, req.workspace)
        if new_artist:
            sup_access.set_local_identity(username)
            identity.write_profile(username, req.first_name, req.last_name)
            if req.password:
                passwords.set_password(username, req.password)
                if req.remember:
                    passwords.remember_on_this_pc(username)
        return username

    loop = asyncio.get_running_loop()
    try:
        username = await loop.run_in_executor(None, _scaffold)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
        await loop.run_in_executor(None, lambda: _refuse_during_sup_entry(req.last_project))
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
        if not user_utils.is_valid_user_name(new_user):
            raise HTTPException(status_code=400, detail=f"Nom d'artiste invalide : {new_user}")
        if new_user != config.get_current_user():
            from features.accounts import aliases
            if not user_utils.user_exists(new_user) and aliases.is_retired_name(new_user):
                raise HTTPException(status_code=400,
                                    detail=f"{new_user} a appartenu à un autre artiste, choisis un autre nom.")
            await loop.run_in_executor(
                None, lambda: _check_can_enter(new_user, req.password, req.remember))
        # set_current_user crée le dossier FLUX_ROOT/USER/<name>/ en plus de persister
        await loop.run_in_executor(None, lambda: user_utils.set_current_user(new_user))
        await loop.run_in_executor(None, lambda: set_config_username(new_user))
        log.info("User switched to '%s'", new_user)

    if req.workspace:
        await loop.run_in_executor(None, _refuse_during_sup_entry)

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


class WorkspacePath(BaseModel):
    path: str


def _workspaces_payload() -> dict:
    root = get_flux_root()
    return {
        "active": str(root) if root else None,
        "workspaces": [
            {"path": p, "exists": Path(p).is_dir(), "active": bool(root) and same_root(p, str(root))}
            for p in get_flux_roots()
        ],
    }


@router.get("/workspaces")
async def list_workspaces() -> dict:
    """Known FLUX directories on this machine and the active one."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _workspaces_payload)


@router.post("/workspaces")
async def add_workspace(req: WorkspacePath) -> dict:
    """Register a FLUX directory (not activated; activate with PUT /settings)."""
    if not req.path.strip():
        raise HTTPException(status_code=400, detail="Chemin vide")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: add_flux_root(req.path.strip()))
    return await loop.run_in_executor(None, _workspaces_payload)


@router.post("/workspaces/remove")
async def remove_workspace(req: WorkspacePath) -> dict:
    """Forget a FLUX directory from the list. Files are kept; the active one is refused."""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: remove_flux_root(req.path))
    except ValueError:
        raise HTTPException(status_code=409, detail="Impossible de retirer le répertoire actif")
    return await loop.run_in_executor(None, _workspaces_payload)


@router.get("/users")
async def list_users() -> dict:
    """Return existing usernames (for first-launch suggestions)."""
    from utils.user_utils import list_users as _list
    loop = asyncio.get_running_loop()
    users = await loop.run_in_executor(None, _list)
    return {"users": users}


@router.get("/users/profiles")
async def list_user_profiles() -> dict:
    """Every artist: first / last name, password set or not, opens freely here (Login, Settings)."""
    from features.accounts import identity, sup_access

    def _profiles() -> list[dict]:
        is_supervisor = sup_access.identity_is_supervisor()
        return [{**identity.read_profile(u), "free_entry": sup_access.is_free_entry(u, is_supervisor)}
                for u in user_utils.list_users()]

    loop = asyncio.get_running_loop()
    return {"profiles": await loop.run_in_executor(None, _profiles)}


@router.post("/users/profiles-at")
async def list_user_profiles_at(req: WorkspacePath) -> dict:
    """First launch: the artists of the chosen directory, before any account exists here.

    The repository only reads the active root, so an existing team directory becomes the
    root now. Still a first launch without a username, and a new folder is left untouched.
    """
    from features.accounts import identity

    def _read() -> list[dict]:
        if not config.is_first_launch():
            raise PermissionError
        root = Path(req.path.strip())
        if not req.path.strip() or not (root / "USER").is_dir():
            return []
        set_flux_root(root)
        reset_repository()
        reset_storage()
        return [identity.read_profile(u) for u in user_utils.list_users()]

    loop = asyncio.get_running_loop()
    try:
        return {"profiles": await loop.run_in_executor(None, _read)}
    except PermissionError:
        raise HTTPException(status_code=409, detail="Réservé au premier lancement.")


class NewArtistRequest(BaseModel):
    first_name: str
    last_name: str
    password: str | None = None
    remember: bool = False
    switch: bool = True        # become the active artist right away


@router.post("/users/id-preview")
async def preview_user_id(req: NewArtistRequest) -> dict:
    """Identifier a new artist would get (shown before validation)."""
    from features.accounts import identity
    loop = asyncio.get_running_loop()
    try:
        user_id = await loop.run_in_executor(
            None, lambda: identity.make_user_id(req.first_name, req.last_name, _taken_names()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": user_id}


@router.post("/users")
async def create_artist(req: NewArtistRequest) -> dict:
    """Create an artist from first + last name (optional password), switch to it if asked."""
    from features.accounts import identity, passwords, sup_access

    def _create() -> str:
        user_id = identity.make_user_id(req.first_name, req.last_name, _taken_names())
        if req.password:
            passwords.validate_new_password(req.password)
        user_utils.create_user_dir(user_id)
        identity.write_profile(user_id, req.first_name, req.last_name)
        if req.password:
            passwords.set_password(user_id, req.password)
            if req.remember:
                passwords.remember_on_this_pc(user_id)
        if req.switch:
            user_utils.set_current_user(user_id)
            set_config_username(user_id)
            sup_access.set_local_identity(user_id)
        return user_id

    loop = asyncio.get_running_loop()
    try:
        user_id = await loop.run_in_executor(None, _create)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    log.info("Artist created '%s'", user_id)
    return {"id": user_id}


@router.get("/user/profile")
async def get_own_profile() -> dict:
    """Active artist's profile (identifier, first / last name, password set)."""
    from features.accounts import identity
    user = config.get_current_user()
    if not user:
        raise HTTPException(status_code=400, detail="Aucun utilisateur actif")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: identity.read_profile(user))


class ProfileUpdate(BaseModel):
    first_name: str = ""
    last_name: str = ""


@router.put("/user/profile")
async def put_own_profile(req: ProfileUpdate) -> dict:
    """Fill or change the active artist's first / last name (identifier unchanged)."""
    from features.accounts import identity
    user = config.get_current_user()
    if not user:
        raise HTTPException(status_code=400, detail="Aucun utilisateur actif")
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, lambda: identity.write_profile(user, req.first_name, req.last_name))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class PasswordChange(BaseModel):
    current: str | None = None   # required when a password is already set
    new: str | None = None       # empty / None removes the password


@router.put("/user/password")
async def put_own_password(req: PasswordChange) -> dict:
    """Set, change or remove the active artist's password."""
    from features.accounts import passwords
    user = config.get_current_user()
    if not user:
        raise HTTPException(status_code=400, detail="Aucun utilisateur actif")

    def _change() -> bool:
        if not passwords.check_password(user, req.current):
            raise PermissionError("Mot de passe actuel incorrect.")
        has = passwords.set_password(user, req.new)
        passwords.forget_on_this_pc(user)
        return has

    loop = asyncio.get_running_loop()
    try:
        has = await loop.run_in_executor(None, _change)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    log.info("Password %s for '%s'", "set" if has else "removed", user)
    return {"has_password": has}


class ProjectScoped(BaseModel):
    project: str | None = None


@router.post("/users/{name}/reset-password")
async def reset_password(name: str, req: ProjectScoped) -> dict:
    """Remove an artist's password: lead or supervisor of the active project only."""
    from features.accounts import passwords
    name = name.strip().upper()
    if not user_utils.user_exists(name):
        raise HTTPException(status_code=404, detail=f"Artiste introuvable : {name}")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: _require_role(req.project, "reset_password"))
    try:
        await loop.run_in_executor(None, lambda: passwords.set_password(name, None))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    log.info("Password reset for '%s' by '%s' (project %s)", name, config.get_current_user(), req.project)
    return {"success": True}


class UserRenameRequest(BaseModel):
    old: str
    new: str
    project: str | None = None   # needed to rename ANOTHER artist (supervisor)


@router.put("/users/rename")
async def rename_user_endpoint(req: UserRenameRequest) -> dict:
    """Rename an artist (folder + alias so the history follows; active user follows).

    Your own account is always yours; another artist's needs a lead of the project.
    """
    loop = asyncio.get_running_loop()
    if req.old.strip().upper() != (config.get_current_user() or ""):
        await loop.run_in_executor(None, lambda: _require_role(req.project, "rename_accounts"))
    ok, msg = await loop.run_in_executor(None, lambda: user_utils.rename_user(req.old, req.new))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


class UserRenameByNameRequest(BaseModel):
    old: str
    first_name: str
    last_name: str = ""          # empty = the first name alone
    project: str | None = None   # needed to rename ANOTHER artist (lead or supervisor)


@router.post("/users/rename-preview")
async def preview_rename(req: UserRenameByNameRequest) -> dict:
    """Identifier artist *old* would get with this first / last name (ADR 0079)."""
    from features.accounts import identity
    loop = asyncio.get_running_loop()
    try:
        user_id = await loop.run_in_executor(
            None, lambda: identity.id_for_rename(req.first_name, req.last_name, req.old, _taken_names()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": user_id}


@router.put("/users/rename-by-name")
async def rename_user_by_name(req: UserRenameByNameRequest) -> dict:
    """Rename an artist from first + last name: identifier from the initials (ADR 0079),
    folder + alias as /users/rename, display name stored. Same identifier = only the
    display name changes. Another artist's account needs a lead of the project."""
    from features.accounts import identity
    loop = asyncio.get_running_loop()
    old = req.old.strip().upper()
    if old != (config.get_current_user() or ""):
        await loop.run_in_executor(None, lambda: _require_role(req.project, "rename_accounts"))

    def _rename() -> tuple[str, str]:
        if not user_utils.user_exists(old):
            raise ValueError(f"Artiste introuvable : {old}")
        new_id = identity.id_for_rename(req.first_name, req.last_name, old, _taken_names())
        if new_id != old:
            ok, msg = user_utils.rename_user(old, new_id)
            if not ok:
                raise ValueError(msg)
        else:
            msg = f"Nom de {old} mis à jour"
        identity.write_profile(new_id, req.first_name, req.last_name)
        return new_id, msg

    try:
        new_id, msg = await loop.run_in_executor(None, _rename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"success": True, "id": new_id, "message": msg}


@router.delete("/users/{name}")
async def delete_user_endpoint(name: str, project: str | None = None) -> dict:
    """Delete an artist and their data (refuses the active user; supervisor only)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: _require_role(project, "manage_accounts"))
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
    from features.accounts.passwords import PASSWORD_KEY
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, lambda: user_utils.read_user_data(user))
    data.pop(PASSWORD_KEY, None)   # the hash never leaves the backend
    return data


@router.put("/user-data")
async def put_user_data(patch: dict) -> dict:
    """Merge *patch* into the active user's settings blob and persist it."""
    user = config.get_current_user()
    if not user:
        raise HTTPException(status_code=400, detail="Aucun utilisateur actif")

    from features.accounts.passwords import PASSWORD_KEY

    def _merge() -> dict:
        data = user_utils.read_user_data(user)
        # The password only changes through PUT /settings/user/password.
        data.update({k: v for k, v in patch.items() if k != PASSWORD_KEY})
        user_utils.write_user_data(user, data)
        return {k: v for k, v in data.items() if k != PASSWORD_KEY}

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
