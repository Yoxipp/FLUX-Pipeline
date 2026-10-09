"""
FLUX Work routes (ADR 0051): versions of a Houdini work subnet, called by the FLUX Work
HDA. Metadata only: Houdini writes the .cpio itself (ADR 0005).
Mounted at /dcc/houdini/work.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from features.houdini_work import work_store

log = get_logger(__name__)
router = APIRouter()

# Departments a FLUX Work can open (ADR 0051), in menu order; kept only when the
# project's TYPE_SHOT tokens know them.
WORK_TASKS = ("CFX", "FX", "LIGHT", "RENDER")


class TaskRef(BaseModel):
    project: str
    seq: str
    shot: str = ""            # empty = sequence task
    task: str


class ReserveRequest(TaskRef):
    author: str = ""
    host: str = ""
    based_on: str = ""
    comment: str = ""
    houdini_version: str = ""
    license: str = ""
    category: str = ""        # Sop | Lop
    template: bool = False


class CommitRequest(TaskRef):
    version: str
    hash: str = ""
    size: int = 0
    node_types: list = []
    external_deps: list = []
    embedded_hdas: list = []


class VersionRequest(TaskRef):
    version: str


class LockRequest(TaskRef):
    author: str = ""
    host: str = ""
    force: bool = False


def _project_path(project: str):
    from core.paths import get_project_path

    path = get_project_path(project)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")
    return path


def _folder(ref: TaskRef):
    try:
        return work_store.work_dir(_project_path(ref.project), ref.seq, ref.shot, ref.task)
    except work_store.WorkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _author(author: str) -> str:
    from core.config import get_current_user

    return author or get_current_user() or ""


async def _run(fn):
    try:
        return await asyncio.get_running_loop().run_in_executor(None, fn)
    except work_store.WorkError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tasks")
async def work_tasks(project: str) -> dict:
    """Departments a FLUX Work can open in this project."""
    from features.folder_manager.tokens import load_tokens

    known = (load_tokens(_project_path(project)) or {}).get("TYPE_SHOT") or {}
    return {"tasks": [t for t in WORK_TASKS if t in known]}


@router.get("/module")
async def work_module() -> dict:
    """PythonModule of the FLUX Work HDA, exec()'d by its bootstrap (no rebuild on fix)."""
    from dcc.houdini.hda.flux_work_hda import module_code

    return {"code": module_code()}


@router.get("/shots")
async def work_shots(project: str) -> dict:
    """Sequences of the Production planning and their shots, for the FLUX Work menus."""
    from features.production import production_store

    _project_path(project)
    production = await asyncio.get_running_loop().run_in_executor(
        None, lambda: production_store.load_production(project))
    names = {s.get("id"): str(s.get("name") or "").upper() for s in production.get("sequences", [])}
    out: dict[str, list[str]] = {name: [] for name in names.values() if name}
    for shot in production.get("shots", []):
        seq = names.get(shot.get("seq_id"))
        name = str(shot.get("name") or "").upper()
        if seq and name:
            out.setdefault(seq, []).append(name)
    return {"sequences": [{"seq": seq, "shots": sorted(shots)} for seq, shots in sorted(out.items())]}


@router.get("/status")
async def work_status(project: str, seq: str, task: str, shot: str = "", based_on: str = "",
                      author: str = "", host: str = "") -> dict:
    folder = _folder(TaskRef(project=project, seq=seq, shot=shot, task=task))
    return await _run(lambda: work_store.task_status(folder, based_on=based_on,
                                                     author=_author(author), host=host))


@router.post("/reserve")
async def work_reserve(req: ReserveRequest) -> dict:
    folder = _folder(req)
    return await _run(lambda: work_store.reserve_version(
        folder, author=_author(req.author), host=req.host, based_on=req.based_on,
        comment=req.comment, houdini_version=req.houdini_version, license=req.license,
        category=req.category, seq=req.seq.upper(), shot=req.shot.upper(), task=req.task.upper(),
        template=req.template))


@router.post("/commit")
async def work_commit(req: CommitRequest) -> dict:
    folder = _folder(req)
    return await _run(lambda: work_store.commit_version(
        folder, req.version, hash=req.hash, size=req.size, node_types=req.node_types,
        external_deps=req.external_deps, embedded_hdas=req.embedded_hdas))


@router.post("/abort")
async def work_abort(req: VersionRequest) -> dict:
    folder = _folder(req)
    return {"removed": await _run(lambda: work_store.abort_version(folder, req.version))}


@router.post("/lock")
async def work_lock(req: LockRequest) -> dict:
    folder = _folder(req)
    return await _run(lambda: work_store.take_lock(folder, author=_author(req.author),
                                                   host=req.host, force=req.force))


@router.post("/unlock")
async def work_unlock(req: LockRequest) -> dict:
    folder = _folder(req)
    return {"released": await _run(lambda: work_store.release_lock(
        folder, author=_author(req.author), host=req.host))}
