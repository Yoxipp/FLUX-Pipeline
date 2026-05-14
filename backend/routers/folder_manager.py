# routers/folder_manager.py — project / asset / sequence / shot CRUD endpoints.

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from core.paths import get_project_path, is_subpath
from features.folder_manager.asset_creator import create_asset, list_assets
from features.folder_manager.project_init import create_project, list_projects, project_exists
from features.folder_manager.seq_shot_creator import (
    create_sequence, create_shot, list_sequences, list_shots,
)
from features.folder_manager.tokens import add_token, get_path_for_token, load_tokens

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


# ── Assets ────────────────────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    project: str
    class_token: str
    name: str


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

    loop = asyncio.get_event_loop()
    try:
        if item_path.is_dir():
            await loop.run_in_executor(None, lambda: shutil.rmtree(item_path))
        else:
            await loop.run_in_executor(None, item_path.unlink)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    log.info("Deleted %s", item_path)
    return {"deleted": req.name}
