# routers/shelf.py — DCC shelf install/remove endpoints.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from features.shelf_manager.shelf_core import (
    get_installed_versions,
    install_hdas,
    install_shelf,
    install_tool_shelf,
    is_hda_installed,
    is_shelf_installed,
    is_tool_installed,
    list_tools,
    remove_hdas,
    remove_shelf,
    remove_tool_shelf,
)

log = get_logger(__name__)
router = APIRouter()

_SUPPORTED_DCCS = ("Maya", "Houdini")


class ShelfInstallRequest(BaseModel):
    dcc: str
    version: str


class ShelfRemoveRequest(BaseModel):
    dcc: str
    version: str


class ToolInstallRequest(BaseModel):
    tool_id: str
    version: str


@router.get("")
async def get_shelves() -> dict:
    """Return shelf + HDA status for all supported DCCs and their installed versions."""
    loop = asyncio.get_event_loop()
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
    loop = asyncio.get_event_loop()
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
    loop = asyncio.get_event_loop()
    ok, msg = await loop.run_in_executor(None, lambda: install_shelf(req.dcc, req.version))
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}


@router.delete("")
async def remove(req: ShelfRemoveRequest) -> dict:
    """Remove the Flux shelf for a given DCC + version."""
    if req.dcc not in _SUPPORTED_DCCS:
        raise HTTPException(status_code=400, detail=f"DCC non supporté : {req.dcc}")
    loop = asyncio.get_event_loop()
    ok, msg = await loop.run_in_executor(None, lambda: remove_shelf(req.dcc, req.version))
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}


# ── Catalogue de tools Maya (rig toolbox / anim tool / flux) ──────────────────
@router.get("/tools")
async def get_tools() -> dict:
    """Catalogue des tools Maya installables + statut installé par version."""
    loop = asyncio.get_event_loop()
    versions = await loop.run_in_executor(
        None, lambda: get_installed_versions("Maya"))
    tools = list_tools()
    for t in tools:
        t["installed"] = {
            v: await loop.run_in_executor(
                None, lambda tid=t["id"], ver=v: is_tool_installed(tid, ver))
            for v in versions
        }
    return {"versions": versions, "tools": tools}


@router.post("/tools/install")
async def install_tool(req: ToolInstallRequest) -> dict:
    """Installe le shelf d'un tool du catalogue pour une version Maya."""
    loop = asyncio.get_event_loop()
    ok, msg = await loop.run_in_executor(
        None, lambda: install_tool_shelf(req.tool_id, req.version))
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}


@router.post("/tools/remove")
async def remove_tool(req: ToolInstallRequest) -> dict:
    """Retire le shelf d'un tool du catalogue pour une version Maya."""
    loop = asyncio.get_event_loop()
    ok, msg = await loop.run_in_executor(
        None, lambda: remove_tool_shelf(req.tool_id, req.version))
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}
