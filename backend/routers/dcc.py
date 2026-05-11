# routers/dcc.py — DCC connection status + command execution + WebSocket push.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core.constants import DCC_COLORS, DCC_PORTS
from core.logger import get_logger
from core.socket_manager import socket_manager
from features.launcher.launcher_core import get_installed_dccs, launch_dcc

log = get_logger(__name__)
router = APIRouter()


class CommandRequest(BaseModel):
    dcc: str
    command: str


class CommandResult(BaseModel):
    success: bool
    result: str
    dcc: str


class LaunchRequest(BaseModel):
    dcc: str
    exe_path: str | None = None


@router.get("/status")
async def get_dcc_status() -> dict:
    """Return reachability state for every known DCC."""
    loop = asyncio.get_event_loop()
    status = {}
    for name, port in DCC_PORTS.items():
        reachable = await loop.run_in_executor(
            None, lambda p=port: socket_manager.probe_port(p)
        )
        status[name] = {
            "connected": reachable,
            "port":      port,
            "color":     DCC_COLORS.get(name, DCC_COLORS["disconnected"]),
        }
    return status


@router.post("/execute", response_model=CommandResult)
async def execute_command(req: CommandRequest) -> CommandResult:
    """Send a Python command to a connected DCC via TCP socket."""
    if req.dcc not in DCC_PORTS:
        raise HTTPException(status_code=400, detail=f"DCC inconnu : {req.dcc}")

    loop = asyncio.get_event_loop()
    if not await loop.run_in_executor(None, lambda: socket_manager.is_connected(req.dcc)):
        connected = await loop.run_in_executor(None, lambda: socket_manager.connect(req.dcc))
        if not connected:
            raise HTTPException(status_code=503, detail=f"{req.dcc} non connecté")

    result = await loop.run_in_executor(
        None, lambda: socket_manager.send_command_safe(req.dcc, req.command)
    )
    if result is None:
        return CommandResult(success=False, result="Pas de réponse du DCC", dcc=req.dcc)
    return CommandResult(success=True, result=result, dcc=req.dcc)


@router.post("/connect/{dcc_name}")
async def connect_dcc(dcc_name: str) -> dict:
    """Explicitly open a socket connection to a DCC."""
    if dcc_name not in DCC_PORTS:
        raise HTTPException(status_code=400, detail=f"DCC inconnu : {dcc_name}")
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: socket_manager.connect(dcc_name))
    return {"dcc": dcc_name, "connected": ok}


@router.post("/disconnect/{dcc_name}")
async def disconnect_dcc(dcc_name: str) -> dict:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: socket_manager.disconnect(dcc_name))
    return {"dcc": dcc_name, "connected": False}


@router.get("/installed")
async def get_installed() -> dict:
    """Return all DCCs detected on this machine."""
    loop = asyncio.get_event_loop()
    found = await loop.run_in_executor(None, get_installed_dccs)
    return {"dccs": found}


@router.post("/launch")
async def launch(req: LaunchRequest) -> dict:
    """Launch a DCC application (optionally saving a custom exe path first)."""
    from features.launcher.launcher_core import set_custom_exe_path
    loop = asyncio.get_event_loop()
    if req.exe_path:
        await loop.run_in_executor(None, lambda: set_custom_exe_path(req.dcc, req.exe_path))
    ok = await loop.run_in_executor(None, lambda: launch_dcc(req.dcc))
    return {"dcc": req.dcc, "launched": ok}


@router.websocket("/ws/status")
async def dcc_status_websocket(websocket: WebSocket):
    """Push DCC status every 2 seconds via WebSocket."""
    await websocket.accept()
    try:
        while True:
            loop = asyncio.get_event_loop()
            status: dict = {}
            for name, port in DCC_PORTS.items():
                reachable = await loop.run_in_executor(
                    None, lambda p=port: socket_manager.probe_port(p)
                )
                status[name] = {
                    "connected": reachable,
                    "color":     DCC_COLORS.get(name, DCC_COLORS["disconnected"]),
                }
            await websocket.send_json(status)
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        pass
