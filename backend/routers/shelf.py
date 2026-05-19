# routers/shelf.py — DCC shelf install/remove endpoints.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from features.shelf_manager.shelf_core import (
    get_installed_versions,
    install_shelf,
    is_shelf_installed,
    remove_shelf,
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


@router.get("")
async def get_shelves() -> dict:
    """Return shelf status for all supported DCCs and their installed versions."""
    loop = asyncio.get_event_loop()
    result = {}
    for dcc in _SUPPORTED_DCCS:
        versions = await loop.run_in_executor(None, lambda d=dcc: get_installed_versions(d))
        installed = {
            v: await loop.run_in_executor(None, lambda d=dcc, ver=v: is_shelf_installed(d, ver))
            for v in versions
        }
        result[dcc] = {"versions": versions, "installed": installed}
    return result


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
