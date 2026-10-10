# routers/shelf.py — DCC shelf install/remove endpoints.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from features.shelf_manager.shelf_core import (
    get_installed_versions,
    get_shelf_tool_selection,
    install_flux_shelf,
    install_shelf,
    is_hda_installed,
    is_shelf_installed,
    list_tools,
    remove_shelf,
)

log = get_logger(__name__)
router = APIRouter()

_SUPPORTED_DCCS = ("Maya", "Houdini", "ZBrush")


class ShelfInstallRequest(BaseModel):
    dcc: str
    version: str


class ShelfRemoveRequest(BaseModel):
    dcc: str
    version: str


class ToolsApplyRequest(BaseModel):
    version: str
    tool_ids: list[str]


@router.get("")
async def get_shelves() -> dict:
    """Return shelf + HDA status for all supported DCCs and their installed versions."""
    loop = asyncio.get_running_loop()
    result = {}
    for dcc in _SUPPORTED_DCCS:
        versions = await loop.run_in_executor(None, lambda d=dcc: get_installed_versions(d))
        installed: dict[str, bool] = {
            v: await loop.run_in_executor(None, lambda d=dcc, ver=v: is_shelf_installed(d, ver))
            for v in versions
        }
        hdas: dict[str, bool] = {}
        if dcc == "Houdini":
            hdas = {
                v: await loop.run_in_executor(None, lambda ver=v: is_hda_installed(ver))
                for v in versions
            }
        result[dcc] = {"versions": versions, "installed": installed, "hdas_installed": hdas}
    return result


@router.get("/{dcc}/{version}/status")
async def get_shelf_status(dcc: str, version: str) -> dict:
    """Return shelf + HDA install status for a specific DCC version."""
    if dcc not in _SUPPORTED_DCCS:
        raise HTTPException(status_code=400, detail=f"DCC non supporté : {dcc}")
    loop = asyncio.get_running_loop()
    shelf = await loop.run_in_executor(None, lambda: is_shelf_installed(dcc, version))
    hdas = False
    if dcc == "Houdini":
        hdas = await loop.run_in_executor(None, lambda: is_hda_installed(version))
    return {"dcc": dcc, "version": version, "shelf": shelf, "hdas": hdas}


@router.post("/install")
async def install(req: ShelfInstallRequest) -> dict:
    """Install the Flux shelf for a given DCC + version."""
    if req.dcc not in _SUPPORTED_DCCS:
        raise HTTPException(status_code=400, detail=f"DCC non supporté : {req.dcc}")
    loop = asyncio.get_running_loop()
    ok, msg = await loop.run_in_executor(None, lambda: install_shelf(req.dcc, req.version))
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}


@router.delete("")
async def remove(req: ShelfRemoveRequest) -> dict:
    """Remove the Flux shelf for a given DCC + version."""
    if req.dcc not in _SUPPORTED_DCCS:
        raise HTTPException(status_code=400, detail=f"DCC non supporté : {req.dcc}")
    loop = asyncio.get_running_loop()
    ok, msg = await loop.run_in_executor(None, lambda: remove_shelf(req.dcc, req.version))
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}


# ── Maya tools → single Flux shelf (checkable, selection persisted) ───────────
@router.get("/tools")
async def get_tools() -> dict:
    """Return the Maya tools, their persisted selection, and shelf install status."""
    loop = asyncio.get_running_loop()
    versions = await loop.run_in_executor(None, lambda: get_installed_versions("Maya"))
    selection = await loop.run_in_executor(None, get_shelf_tool_selection)
    tools = list_tools()
    for t in tools:
        t["selected"] = t["id"] in selection
    installed = {
        v: await loop.run_in_executor(None, lambda ver=v: is_shelf_installed("Maya", ver))
        for v in versions
    }
    return {"versions": versions, "tools": tools, "installed": installed}


@router.post("/tools/apply")
async def apply_tools(req: ToolsApplyRequest) -> dict:
    """Install the single Flux shelf with the selected tools (persists the choice)."""
    loop = asyncio.get_running_loop()
    ok, msg = await loop.run_in_executor(
        None, lambda: install_flux_shelf(req.version, req.tool_ids))
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}


# ── Old FLUX files after a reinstall (features/shelf_manager/stale_cleanup.py) ──

class StaleRemoveRequest(BaseModel):
    dcc: str
    version: str
    paths: list[str]


@router.get("/stale")
async def stale_files(dcc: str, version: str) -> dict:
    """FLUX files of *dcc* *version* that are no longer the real install, with why.
    Only FLUX's own files are ever listed (never an artist's HDA or shelf)."""
    from features.shelf_manager import stale_cleanup

    loop = asyncio.get_running_loop()
    return {"items": await loop.run_in_executor(None, lambda: stale_cleanup.scan(dcc, version))}


@router.post("/stale/remove")
async def remove_stale_files(req: StaleRemoveRequest) -> dict:
    """Delete the ticked files; a path a fresh scan does not list is skipped."""
    from features.shelf_manager import stale_cleanup

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: stale_cleanup.remove(req.dcc, req.version, req.paths))
