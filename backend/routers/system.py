# routers/system.py — machine-level info (disk usage today; more later).

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from core.logger import get_logger
from core.paths import get_flux_root, get_projects_dir

log = get_logger(__name__)
router = APIRouter()


@router.get("/disk-usage")
async def disk_usage(project: str = "", limit: int = 200) -> dict:
    """Heaviest files under DOSSIER_PROJETS (or one project). Simple, on-demand."""
    if limit <= 0 or limit > 2000:
        raise HTTPException(status_code=400, detail="limit must be in [1, 2000]")
    from features.system.disk_usage import scan
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: scan(project or None, limit))


@router.get("/flux-root")
async def flux_root() -> dict:
    """Return the local FLUX pipeline root. Used by Houdini's autostart to set
    $FLUX dynamically to whichever FLUX is currently running (agnostic of the
    pipe folder that installed the autostart)."""
    root = get_flux_root()
    return {
        "root":         str(root) if root else "",
        "projects_dir": str(get_projects_dir()),
    }
