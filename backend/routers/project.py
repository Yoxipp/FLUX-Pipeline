# routers/project.py — single source of truth for the active project.
#
# The active project is persisted in config.json (last_project) via project_utils,
# so it survives a backend restart. The frontend ProjectContext syncs against this.

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from utils import project_utils

log = get_logger(__name__)
router = APIRouter()


class ProjectPayload(BaseModel):
    project: str


@router.get("/current")
def get_current_project() -> dict:
    """Return the active project name (may be None on a fresh workspace)."""
    return {"project": project_utils.get_current_project()}


@router.put("/current")
def set_current_project(payload: ProjectPayload) -> dict:
    """Set and persist the active project. 404 if the project does not exist."""
    name = payload.project.strip()
    if not name or not project_utils.project_exists(name):
        raise HTTPException(status_code=404, detail=f"Project not found: {name!r}")
    project_utils.set_current_project(name)
    # First open by this code: create/heal project.json (ADR 0006). Never blocks.
    try:
        from core.paths import get_project_path, get_projects_dir
        from features.folder_manager.project_config import ensure_project_config, is_direct_project_dir
        if is_direct_project_dir(get_project_path(name), get_projects_dir()):
            ensure_project_config(get_project_path(name))
    except Exception as exc:  # noqa: BLE001
        log.warning("project.json auto-create skipped for %s: %s", name, exc)
    return {"project": name}
