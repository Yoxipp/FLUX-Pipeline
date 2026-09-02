# routers/files.py — generic file browsing restricted to DOSSIER_PROJETS.

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from core.logger import get_logger
from core.paths import get_project_path
from features.importer.file_browser import get_file_info, list_files_immediate, list_folders

log = get_logger(__name__)
router = APIRouter()


@router.get("/projects/{project_name}/browse")
async def browse_project(project_name: str, subpath: str = "") -> dict:
    """Browse files inside a project folder."""
    project_path = get_project_path(project_name)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project_name}")

    target = (project_path / subpath).resolve() if subpath else project_path.resolve()
    loop = asyncio.get_event_loop()
    folder_names = await loop.run_in_executor(
        None, lambda: list_folders(project_path, subpath)
    )
    all_files = await loop.run_in_executor(None, lambda: list_files_immediate(target))
    files_info = [get_file_info(f, target) for f in all_files]

    return {
        "path":    str(target),
        "folders": [{"name": n, "path": str(project_path / subpath / n if subpath else project_path / n)} for n in folder_names],
        "files":   files_info,
    }
