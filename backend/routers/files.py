# routers/files.py — generic file browsing restricted to DOSSIER_PROJETS.

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from core.logger import get_logger
from core.paths import get_project_path, get_projects_dir, is_subpath
from core.project_setup import SETUP_FILES, is_setup_rel
from features.importer.file_browser import get_file_info, list_files_immediate, list_folders

log = get_logger(__name__)
router = APIRouter()


# B3 (2026-09-28): folder listings cached by the folder's own mtime. Adding, removing
# or renaming an entry changes it (NTFS and ext4), so a hit is never stale for names;
# one stat replaces the full listing (slow on OneDrive / network shares).
_LIST_CACHE: dict[Path, tuple[int, list[str], list[Path]]] = {}
_LIST_CACHE_MAX = 512


def _list_dir_cached(project_path: Path, subpath: str, target: Path) -> tuple[list[str], list[Path]]:
    try:
        mtime = target.stat().st_mtime_ns
    except OSError:
        return list_folders(project_path, subpath), list_files_immediate(target)
    hit = _LIST_CACHE.get(target)
    if hit and hit[0] == mtime:
        return list(hit[1]), list(hit[2])
    folders = list_folders(project_path, subpath)
    files = list_files_immediate(target)
    if len(_LIST_CACHE) >= _LIST_CACHE_MAX:
        _LIST_CACHE.clear()
    _LIST_CACHE[target] = (mtime, folders, files)
    return list(folders), list(files)


def _filter_setup(project: Path, target: Path, folders: list, files: list, setup: bool) -> tuple[list, list]:
    """Hide (default) or reveal the project setup entries (core.project_setup)."""
    rel = target.relative_to(project).as_posix() if target != project else ""
    if not setup:
        if rel:
            return folders, files
        return ([n for n in folders if not is_setup_rel(n)],
                [f for f in files if not is_setup_rel(Path(f).name)])
    if rel and not is_setup_rel(rel):
        return folders, files
    # The listing hides every .json: add back the setup ones (all of them inside _flux_setup/).
    try:
        extra = [p for p in target.glob("*.json") if p.is_file() and (rel or p.name in SETUP_FILES)]
    except OSError:
        extra = []
    known = {Path(f).name for f in files}
    return folders, [*files, *sorted((p for p in extra if p.name not in known), key=lambda p: p.name.lower())]


@router.get("/projects/{project_name}/browse")
async def browse_project(project_name: str, subpath: str = "", setup: bool = False) -> dict:
    """Browse files inside a project folder. *setup* (Folder Manager "Setup files" box):
    also list _flux_setup/ and the FLUX JSON files; hidden otherwise."""
    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")

    # Security S5: the project must be a direct child of the projects dir (no "..")
    # and the browsed folder must stay inside the project.
    if project_path.resolve().parent != get_projects_dir().resolve():
        raise HTTPException(status_code=403, detail="Chemin non autorisé")
    target = (project_path / subpath).resolve() if subpath else project_path.resolve()
    if not is_subpath(target, project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")
    loop = asyncio.get_running_loop()
    folder_names, all_files = await loop.run_in_executor(
        None, lambda: _list_dir_cached(project_path, subpath, target)
    )
    folder_names, all_files = _filter_setup(project_path.resolve(), target, folder_names, all_files, setup)
    # One modif_logs.json parse per folder (was one per file), off the event loop.
    logs_cache: dict = {}
    files_info = await loop.run_in_executor(
        None, lambda: [get_file_info(f, target, logs_cache) for f in all_files]
    )
    # V4: old Constructor files of usd/assembly are flagged "ancien" (never imported).
    from features.usd_assembler.assembly_v2 import assembly_root
    if target == assembly_root(project_path).resolve():
        from features.importer.load_target import is_legacy_file

        for info, f in zip(files_info, all_files):
            info["legacy"] = await loop.run_in_executor(None, lambda f=f: is_legacy_file(project_path, f))

    return {
        "path":    str(target),
        "folders": [{"name": n, "path": str(project_path / subpath / n if subpath else project_path / n)} for n in folder_names],
        "files":   files_info,
    }


@router.get("/projects/{project_name}/publish-note")
async def publish_note(project_name: str, rel_path: str) -> dict:
    """Note of a published file (N7): latest entry of its version + history, from modif_logs.json."""
    from features.publisher.publish_note import publish_notes

    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")
    target = (project_path / rel_path).resolve()
    if not is_subpath(target, project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: publish_notes(project_path, rel_path))


@router.get("/projects/{project_name}/file-log")
async def get_file_log(project_name: str, rel_path: str) -> dict:
    """Raw modif_logs.json entries for a file, plus the folder's whole log."""
    from features.publisher.publish_note import file_log

    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")
    target = (project_path / rel_path).resolve()
    if not is_subpath(target, project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorisé")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: file_log(project_path, rel_path))
