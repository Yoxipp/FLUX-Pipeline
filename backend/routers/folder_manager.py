# routers/folder_manager.py — project / asset / sequence / shot CRUD endpoints.

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from core.paths import force_remove, force_rmtree, get_project_path, get_projects_dir, is_subpath
from features.folder_manager.asset_creator import create_asset, heal_tokens_from_disk, list_assets
from features.folder_manager.locks import is_locked, load_locks, set_lock
from features.folder_manager.project_config import ensure_project_config, is_direct_project_dir
from features.folder_manager.project_init import create_project, list_projects, project_exists
from features.folder_manager.seq_shot_creator import (
    create_sequence, create_shot, list_sequences, list_shots,
)
from features.folder_manager.tokens import add_token, get_path_for_token, load_tokens
from features.folder_manager import preset_manager

log = get_logger(__name__)
router = APIRouter()

_NUM_RE = re.compile(r'\d+')


def _parse_int(label: str) -> int:
    """Extract integer from label like 'SEQ001' → 1, '10' → 10."""
    m = _NUM_RE.search(label)
    if not m:
        raise ValueError(f"Impossible d'extraire un numéro depuis '{label}'")
    return int(m.group())


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str


@router.get("/projects/{project_name}/tokens")
async def get_project_tokens(project_name: str) -> dict:
    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")
    loop = asyncio.get_event_loop()
    # Auto-heal first: adopt on-disk assets/shots that have no token yet so the
    # composer's NAME/SEQ/SHOT pickers list everything that exists on disk. Idempotent
    # and non-destructive; a scan hiccup must never block returning the tokens.
    try:
        await loop.run_in_executor(None, lambda: heal_tokens_from_disk(project_path))
    except Exception as exc:  # noqa: BLE001 — heal is best-effort, never fatal
        log.warning("Token auto-heal skipped for %s: %s", project_name, exc)
    # project.json auto-creation at first open (ADR 0006); best-effort, never blocks.
    try:
        if is_direct_project_dir(project_path, get_projects_dir()):
            await loop.run_in_executor(None, lambda: ensure_project_config(project_path))
    except Exception as exc:  # noqa: BLE001
        log.warning("project.json auto-create skipped for %s: %s", project_name, exc)
    tokens = await loop.run_in_executor(None, lambda: load_tokens(project_path))
    return {"tokens": tokens}


@router.get("/projects/{project_name}/config")
async def get_project_config(project_name: str) -> dict:
    """Return <project>/project.json, creating or healing it first (ADR 0006)."""
    project_path = get_project_path(project_name)
    if not is_direct_project_dir(project_path, get_projects_dir()):
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")
    loop = asyncio.get_running_loop()
    config, warnings = await loop.run_in_executor(None, lambda: ensure_project_config(project_path))
    return {"config": config, "warnings": warnings}


@router.get("/projects")
async def get_projects() -> dict:
    loop = asyncio.get_event_loop()
    projects = await loop.run_in_executor(None, list_projects)
    return {"projects": projects}


@router.post("/projects")
async def post_project(req: ProjectCreate) -> dict:
    if project_exists(req.name):
        raise HTTPException(status_code=409, detail=f"Projet '{req.name}' existe déjà")
    loop = asyncio.get_event_loop()
    try:
        path = await loop.run_in_executor(None, lambda: create_project(req.name))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": req.name, "path": str(path)}


@router.delete("/projects/{project_name}")
async def delete_project(project_name: str) -> dict:
    """Hard-delete a whole project folder from the workspace.

    Deliberately destructive: the frontend only calls this after the user typed the
    exact confirmation phrase in the Archives view. Guarded so it can only ever remove
    a direct child of DOSSIER_PROJETS — never a traversal target, never the dir itself.
    """
    name = project_name.strip()
    if not name or not project_exists(name):
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {name}")

    projects_dir = get_projects_dir().resolve()
    project_path = get_project_path(name).resolve()

    # Must be a direct child of the projects dir (blocks '..', absolute names, symlink escapes).
    if project_path.parent != projects_dir or not is_subpath(project_path, projects_dir):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: force_rmtree(project_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # If the deleted project was the active one, clear it so the app falls back cleanly.
    from utils import project_utils
    if project_utils.get_current_project() == name:
        project_utils.set_current_project("")

    log.warning("Hard-deleted project %s", project_path)
    return {"deleted": name}


# ── Assets ────────────────────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    project: str
    class_token: str
    name: str


@router.get("/projects/{project_name}/types")
async def get_types_for_class(project_name: str, class_token: str | None = None) -> dict:
    """Return TYPE token keys that have at least one matching subfolder under the given CLASS.

    Scans project/<class_path>/<any_asset>/ for immediate subdirectories, then maps
    found folder names back to TYPE token keys (by lowercased key comparison).
    Falls back to all TYPE tokens when class_token is absent or the class path is missing.
    """
    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")
    loop = asyncio.get_event_loop()
    tokens = await loop.run_in_executor(None, lambda: load_tokens(project_path))
    type_tokens: dict[str, str] = tokens.get("TYPE", {})
    all_type_keys = list(type_tokens.keys())

    if not class_token:
        return {"types": all_type_keys}

    class_rel = get_path_for_token(tokens, "CLASS", class_token)
    if not class_rel:
        return {"types": all_type_keys}

    class_path = project_path / class_rel.replace("/", "\\")

    def _scan() -> list[str]:
        if not class_path.exists():
            return all_type_keys
        found_dirs: set[str] = set()
        try:
            for asset_dir in class_path.iterdir():
                if not asset_dir.is_dir():
                    continue
                for type_dir in asset_dir.iterdir():
                    if type_dir.is_dir():
                        found_dirs.add(type_dir.name.lower())
        except OSError:
            pass
        matched = [k for k in all_type_keys if k.lower() in found_dirs]
        return matched if matched else all_type_keys

    types = await loop.run_in_executor(None, _scan)
    return {"types": types}


@router.get("/suggest")
async def suggest_tokens(
    project: str,
    field: str,                # 'instance' | 'variante' | 'name'
    mode: str = "asset",
    class_token: str = "",
    name: str = "",
    type_token: str = "",
    instance: str = "",
    seq: str = "",
    shot: str = "",
) -> dict:
    """Contextual token suggestions, scanned from what is actually published on disk.

    Never returns a global list — always scoped to the current selection.
    """
    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")

    from features.folder_manager.naming_validator import parse_filename

    def _work() -> list[str]:
        tokens = load_tokens(project_path)
        vals: set[str] = set()

        if mode == "asset":
            # NAME suggestions only need the class → list asset folders under it
            if field == "name":
                class_rel = get_path_for_token(tokens, "CLASS", class_token)
                if class_rel:
                    folder = project_path / class_rel
                    if folder.exists():
                        vals = {p.name for p in folder.iterdir() if p.is_dir()}
                return sorted(vals)

            # instance / variante need a resolved asset (name)
            name_rel = get_path_for_token(tokens, "NAME", name)
            if not name_rel:
                class_rel = get_path_for_token(tokens, "CLASS", class_token)
                if not class_rel or not name:
                    return []
                name_rel = f"{class_rel}/{name}"
            type_sub = tokens.get("TYPE", {}).get(type_token) or (type_token.lower() if type_token else "")

            if field == "instance":
                folder = (project_path / name_rel / type_sub) if type_sub else (project_path / name_rel)
                if folder.exists():
                    vals = {p.name for p in folder.iterdir() if p.is_dir()}
            elif field == "variante":
                inst = (instance or "null").lower()
                folder = project_path / name_rel / type_sub / inst
                if folder.exists():
                    for f in folder.iterdir():
                        if f.is_file():
                            parsed = parse_filename(f.name)
                            if parsed and parsed.get("VARIANTE"):
                                vals.add(parsed["VARIANTE"])
        else:  # shot
            if field == "name":
                folder = project_path / "shot" / seq / shot
                if folder.exists():
                    vals = {p.name.upper() for p in folder.iterdir() if p.is_dir()}
            elif field == "variante":
                class_rel = get_path_for_token(tokens, "CLASS", name)
                folder = None
                if class_rel:
                    try:
                        folder = project_path / class_rel.format(seq=seq, shot=shot)
                    except (KeyError, IndexError):
                        folder = None
                if folder is None:
                    folder = project_path / "shot" / seq / shot
                if folder.exists():
                    for f in folder.rglob("*"):
                        if f.is_file():
                            parsed = parse_filename(f.name)
                            if parsed and parsed.get("VARIANTE"):
                                vals.add(parsed["VARIANTE"])
        return sorted(vals)

    loop = asyncio.get_event_loop()
    suggestions = await loop.run_in_executor(None, _work)
    return {"suggestions": suggestions}


@router.get("/projects/{project_name}/assets")
async def get_assets(project_name: str, class_token: str | None = None) -> dict:
    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")
    loop = asyncio.get_event_loop()
    assets = await loop.run_in_executor(
        None, lambda: list_assets(project_path, class_token)
    )
    return {"assets": assets}


@router.post("/assets")
async def post_asset(req: AssetCreate) -> dict:
    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")
    loop = asyncio.get_event_loop()
    try:
        path = await loop.run_in_executor(
            None, lambda: create_asset(project_path, req.class_token, req.name)
        )
    except (ValueError, FileExistsError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": req.name, "path": str(path)}


# ── Sequences & Shots ─────────────────────────────────────────────────────────

class SequenceCreate(BaseModel):
    project: str
    seq_number: int   # 1, 2, 3… → formaté en SEQ001


class ShotCreate(BaseModel):
    project: str
    seq_number: int
    shot_number: int  # 10, 20, 30… → formaté en SHOT010


@router.get("/projects/{project_name}/sequences")
async def get_sequences(project_name: str) -> dict:
    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")
    loop = asyncio.get_event_loop()
    seqs = await loop.run_in_executor(None, lambda: list_sequences(project_path))
    return {"sequences": seqs}   # ["SEQ001", "SEQ002", ...]


@router.post("/sequences")
async def post_sequence(req: SequenceCreate) -> dict:
    project_path = get_project_path(req.project)
    loop = asyncio.get_event_loop()
    try:
        path = await loop.run_in_executor(
            None, lambda: create_sequence(project_path, req.seq_number)
        )
    except (ValueError, FileExistsError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"seq_number": req.seq_number, "path": str(path)}


@router.get("/projects/{project_name}/sequences/{seq_label}/shots")
async def get_shots(project_name: str, seq_label: str) -> dict:
    """seq_label can be 'SEQ001' or '1'."""
    project_path = get_project_path(project_name)
    try:
        seq_number = _parse_int(seq_label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    loop = asyncio.get_event_loop()
    shots = await loop.run_in_executor(
        None, lambda: list_shots(project_path, seq_number)
    )
    return {"shots": shots}   # ["SEQ001/SHOT010", ...]


@router.post("/shots")
async def post_shot(req: ShotCreate) -> dict:
    project_path = get_project_path(req.project)
    loop = asyncio.get_event_loop()
    try:
        path = await loop.run_in_executor(
            None, lambda: create_shot(project_path, req.seq_number, req.shot_number)
        )
    except (ValueError, FileExistsError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"seq_number": req.seq_number, "shot_number": req.shot_number, "path": str(path)}


# ── Directory ─────────────────────────────────────────────────────────────────

class DirectoryCreate(BaseModel):
    project:    str
    subpath:    str   # chemin actuel relatif depuis la racine projet (peut être "")
    name:       str   # nom du dossier à créer
    token:      str = ""   # token optionnel (ex: "SLA")
    token_type: str = ""   # type du token (CLASS / TYPE / NAME / …)


@router.post("/directory")
async def post_directory(req: DirectoryCreate) -> dict:
    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")

    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Le nom du dossier est requis")

    loop = asyncio.get_event_loop()

    if req.token and req.token_type:
        tokens = await loop.run_in_executor(None, lambda: load_tokens(project_path))
        existing_rel = get_path_for_token(tokens, req.token_type, req.token)

        if existing_rel:
            # Token déjà mappé → créer le dossier à l'emplacement du token
            dir_path = project_path / existing_rel / req.name
            rel_created = f"{existing_rel}/{req.name}"
        else:
            # Token inconnu → créer au chemin courant + enregistrer le token
            rel_created = f"{req.subpath}/{req.name}".lstrip("/") if req.subpath else req.name
            dir_path = project_path / rel_created
            await loop.run_in_executor(
                None, lambda: add_token(project_path, req.token_type, req.token, rel_created)
            )
    else:
        rel_created = f"{req.subpath}/{req.name}".lstrip("/") if req.subpath else req.name
        dir_path = project_path / rel_created

    if not is_subpath(dir_path.resolve(), project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")

    try:
        await loop.run_in_executor(None, lambda: dir_path.mkdir(parents=True, exist_ok=False))
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"'{req.name}' existe déjà")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    log.info("Created directory %s", dir_path)
    return {"name": req.name, "path": str(dir_path), "rel_path": rel_created}


# ── Rename / Move ─────────────────────────────────────────────────────────────

class ItemPatch(BaseModel):
    project:     str
    subpath:     str   # current parent, relative from project root
    name:        str   # current item name
    new_name:    str = ""   # desired new name  (empty = keep)
    new_subpath: str = ""   # desired new parent (empty = keep)


@router.patch("/items")
async def patch_item(req: ItemPatch) -> dict:
    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")

    src_path = (project_path / req.subpath / req.name) if req.subpath else (project_path / req.name)
    # Security S5: the source must stay inside the project, like the destination.
    if not is_subpath(src_path.resolve().parent, project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")
    if not src_path.exists():
        raise HTTPException(status_code=404, detail=f"Introuvable : {req.name}")

    new_name    = req.new_name.strip()    or req.name
    new_subpath = req.new_subpath.strip() if req.new_subpath.strip() != "" else req.subpath
    dst_path    = (project_path / new_subpath / new_name) if new_subpath else (project_path / new_name)

    # A locked item cannot be MOVED (parent change). Pure rename stays allowed.
    # Only the item itself is checked — a locked child never blocks its parent.
    rel_src = f"{req.subpath}/{req.name}" if req.subpath else req.name
    if new_subpath != req.subpath and is_locked(project_path, rel_src):
        raise HTTPException(status_code=423, detail=f"Élément verrouillé : {req.name}")

    if src_path.resolve() == dst_path.resolve():
        raise HTTPException(status_code=400, detail="Source et destination identiques")

    if not is_subpath(dst_path.resolve().parent, project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")

    if src_path.is_dir():
        try:
            dst_path.resolve().relative_to(src_path.resolve())
            raise HTTPException(status_code=400, detail="Impossible de déplacer un dossier dans lui-même")
        except ValueError:
            pass

    if dst_path.exists():
        raise HTTPException(status_code=409, detail=f"'{new_name}' existe déjà à destination")

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: shutil.move(str(src_path), str(dst_path)))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    log.info("Moved/renamed %s → %s", src_path, dst_path)
    return {"name": new_name, "path": str(dst_path)}


# ── Locks ─────────────────────────────────────────────────────────────────────

class LockSet(BaseModel):
    project: str
    subpath: str   # parent relative path; "" = project root
    name:    str
    locked:  bool


@router.get("/projects/{project_name}/locks")
async def get_locks(project_name: str) -> dict:
    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")
    loop = asyncio.get_event_loop()
    locked = await loop.run_in_executor(None, lambda: load_locks(project_path))
    return {"locked": locked}


@router.post("/locks")
async def post_lock(req: LockSet) -> dict:
    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")
    rel = f"{req.subpath}/{req.name}" if req.subpath else req.name
    loop = asyncio.get_event_loop()
    locked = await loop.run_in_executor(None, lambda: set_lock(project_path, rel, req.locked))
    return {"locked": locked}


# ── Copy ──────────────────────────────────────────────────────────────────────

class ItemCopy(BaseModel):
    project:     str
    subpath:     str        # source parent, relative from project root
    name:        str        # source item name
    dst_subpath: str = ""   # destination parent (relative); "" = project root
    new_name:    str = ""   # optional target name (for conflict resolution)


@router.post("/copy")
async def copy_item(req: ItemCopy) -> dict:
    """Copy a file or folder (recursively) to another location inside the same project."""
    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")

    src_path = (project_path / req.subpath / req.name) if req.subpath else (project_path / req.name)
    # Security S5: the source must stay inside the project, like the destination.
    if not is_subpath(src_path.resolve().parent, project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")
    if not src_path.exists():
        raise HTTPException(status_code=404, detail=f"Introuvable : {req.name}")

    dst_name   = req.new_name.strip() or req.name
    dst_parent = (project_path / req.dst_subpath) if req.dst_subpath else project_path
    dst_path   = dst_parent / dst_name

    if not is_subpath(dst_path.resolve().parent, project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")

    if src_path.is_dir():
        try:
            dst_path.resolve().relative_to(src_path.resolve())
            raise HTTPException(status_code=400, detail="Impossible de copier un dossier dans lui-même")
        except ValueError:
            pass

    if dst_path.exists():
        raise HTTPException(status_code=409, detail=f"'{dst_name}' existe déjà à destination")

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()
    try:
        if src_path.is_dir():
            await loop.run_in_executor(None, lambda: shutil.copytree(src_path, dst_path))
        else:
            await loop.run_in_executor(None, lambda: shutil.copy2(src_path, dst_path))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission refusée : {dst_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    log.info("Copied %s → %s", src_path, dst_path)
    return {"name": dst_name, "path": str(dst_path)}


# ── Presets (template library, RETAKES-3) ──────────────────────────────────────

class PresetAdd(BaseModel):
    name: str = ""


class PresetLink(BaseModel):
    src_path: str   # absolute source file path (chosen via the OS file picker)


class PresetRename(BaseModel):
    name: str


class PresetDrop(BaseModel):
    dest_subpath: str = ""   # folder (relative from project root) to drop into; "" = root


class PresetMeta(BaseModel):
    task: str = ""   # TASK token (or DEFAULT); "" clears
    soft: str = ""   # target software key (maya, houdini…); "" clears


class PresetLaunch(BaseModel):
    dcc: str         # frontend software key to launch the linked scene with


def _require_project(project_name: str) -> Path:
    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")
    return project_path


def _preset_or_400(result: dict) -> dict:
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "preset operation failed"))
    return result


@router.get("/projects/{project_name}/presets")
async def get_presets(project_name: str) -> dict:
    project_path = _require_project(project_name)
    loop = asyncio.get_event_loop()
    presets = await loop.run_in_executor(None, lambda: preset_manager.list_presets(project_path))
    return {"presets": presets}


@router.post("/projects/{project_name}/presets")
async def post_preset(project_name: str, req: PresetAdd) -> dict:
    project_path = _require_project(project_name)
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: preset_manager.add_preset_slot(project_path, req.name))
    return _preset_or_400(res)


@router.put("/projects/{project_name}/presets/{preset_id}/link")
async def put_preset_link(project_name: str, preset_id: str, req: PresetLink) -> dict:
    project_path = _require_project(project_name)
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None, lambda: preset_manager.link_preset(project_path, preset_id, Path(req.src_path))
    )
    return _preset_or_400(res)


@router.put("/projects/{project_name}/presets/{preset_id}/unlink")
async def put_preset_unlink(project_name: str, preset_id: str) -> dict:
    project_path = _require_project(project_name)
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: preset_manager.unlink_preset(project_path, preset_id))
    return _preset_or_400(res)


@router.put("/projects/{project_name}/presets/{preset_id}/rename")
async def put_preset_rename(project_name: str, preset_id: str, req: PresetRename) -> dict:
    project_path = _require_project(project_name)
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None, lambda: preset_manager.rename_preset(project_path, preset_id, req.name)
    )
    return _preset_or_400(res)


@router.delete("/projects/{project_name}/presets/{preset_id}")
async def delete_preset(project_name: str, preset_id: str) -> dict:
    project_path = _require_project(project_name)
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: preset_manager.remove_preset_slot(project_path, preset_id))
    return _preset_or_400(res)


@router.post("/projects/{project_name}/presets/{preset_id}/drop")
async def post_preset_drop(project_name: str, preset_id: str, req: PresetDrop) -> dict:
    project_path = _require_project(project_name)
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None, lambda: preset_manager.drop_preset(project_path, preset_id, req.dest_subpath)
    )
    return _preset_or_400(res)


@router.put("/projects/{project_name}/presets/{preset_id}/meta")
async def put_preset_meta(project_name: str, preset_id: str, req: PresetMeta) -> dict:
    project_path = _require_project(project_name)
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None, lambda: preset_manager.set_preset_meta(project_path, preset_id, req.task, req.soft)
    )
    return _preset_or_400(res)


@router.post("/projects/{project_name}/presets/{preset_id}/launch")
async def post_preset_launch(project_name: str, preset_id: str, req: PresetLaunch) -> dict:
    """Launch *req.dcc* on a throwaway copy of the preset's scene ("New Scene").

    The preset template is copied to a temp dir first so opening it is non-destructive
    — saving over the New Scene can never corrupt the shared template.
    """
    from features.launcher.launcher_core import launch_dcc
    project_path = _require_project(project_name)
    loop = asyncio.get_event_loop()
    prep = await loop.run_in_executor(
        None, lambda: preset_manager.prepare_new_scene(project_path, preset_id)
    )
    if not prep.get("ok"):
        raise HTTPException(status_code=400, detail=prep.get("error", "preset introuvable"))
    scene = prep["path"]
    ok = await loop.run_in_executor(None, lambda: launch_dcc(req.dcc, scene))
    return {"ok": ok, "launched": ok, "dcc": req.dcc, "scene": scene}


# ── Delete ────────────────────────────────────────────────────────────────────

class ItemDelete(BaseModel):
    project: str
    subpath: str   # relative path from project root, NOT including item name; "" = project root
    name: str


@router.delete("/items")
async def delete_item(req: ItemDelete) -> dict:
    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")

    item_path = (project_path / req.subpath / req.name) if req.subpath else (project_path / req.name)

    if not is_subpath(item_path.resolve(), project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")

    if not item_path.exists():
        raise HTTPException(status_code=404, detail=f"Introuvable : {req.name}")

    rel = f"{req.subpath}/{req.name}" if req.subpath else req.name
    if is_locked(project_path, rel):
        raise HTTPException(status_code=423, detail=f"Élément verrouillé : {req.name}")

    loop = asyncio.get_event_loop()
    try:
        # force_remove clears read-only bits first: archived publishes are often
        # read-only, so a plain rmtree/unlink fails with WinError 5 on Windows.
        await loop.run_in_executor(None, lambda: force_remove(item_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    log.info("Deleted %s", item_path)
    return {"deleted": req.name}
