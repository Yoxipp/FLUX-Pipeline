# routers/system.py — machine-level info (disk usage, FLUX root, manual, uninstall plan).

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

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


@router.get("/manual")
async def manual(doc: Literal["flux", "flows"] = "flux") -> HTMLResponse:
    """A manual as HTML, for the Settings > Doc tabs (iframe): ``doc=flux`` the FLUX
    manual, ``doc=flows`` the Flows manual. Bundled copy first, else FLUX_DOC (ADR 0049)."""
    from features.system.manual import manual_path
    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(None, manual_path, doc)
    if path is None:
        raise HTTPException(status_code=404, detail="Manuel introuvable")
    text = await loop.run_in_executor(None, lambda: path.read_text(encoding="utf-8"))
    return HTMLResponse(text)


@router.get("/manual-info")
async def manual_info() -> dict:
    """Where the manual lives on disk (to open it in the system browser)."""
    from features.system.manual import manual_path
    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(None, manual_path)
    flows = await loop.run_in_executor(None, manual_path, "flows")
    root = get_flux_root()
    return {
        "path":    str(path) if path else "",
        "flows_path": str(flows) if flows else "",
        "doc_dir": str(root / "FLUX_DOC") if root else "",
    }


@router.get("/uninstall-plan")
async def uninstall_plan() -> dict:
    """What "Desinstaller FLUX" would remove on this machine, and what it keeps.
    Read only: the removal itself runs in the uninstaller (installer.nsh)."""
    from features.system.uninstall import plan
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, plan)
