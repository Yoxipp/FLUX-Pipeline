# routers/dcc.py — DCC connection status + command execution + WebSocket push.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core import config as _config
from core.constants import DCC_COLORS, DCC_PORTS
from core.logger import get_logger
from core.socket_manager import socket_manager
from dcc.houdini import autostart as _houdini_autostart
from features.launcher.launcher_core import find_dcc_exe, get_installed_dccs, launch_dcc

# Maps dcc_key (lowercase) → autostart module. Extend here when adding new DCCs.
_AUTOSTART_MODULES: dict = {
    "houdini": _houdini_autostart,
}

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


async def _probe_all_dccs() -> dict:
    """Probe all DCC ports in parallel. Returns status dict."""
    loop = asyncio.get_event_loop()
    names = list(DCC_PORTS.keys())
    ports = list(DCC_PORTS.values())
    results = await asyncio.gather(
        *[loop.run_in_executor(None, lambda p=port: socket_manager.probe_port(p)) for port in ports]
    )
    return {
        name: {
            "connected": reachable,
            "port":      port,
            "color":     DCC_COLORS.get(name, DCC_COLORS["disconnected"]),
        }
        for name, port, reachable in zip(names, ports, results)
    }


@router.get("/status")
async def get_dcc_status() -> dict:
    """Return reachability state for every known DCC."""
    return await _probe_all_dccs()


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


@router.get("/find/{dcc_key}")
async def auto_find_dcc(dcc_key: str) -> dict:
    """Glob-scan default install paths for dcc_key, save if found."""
    loop = asyncio.get_event_loop()
    path = await loop.run_in_executor(None, lambda: find_dcc_exe(dcc_key))
    return {"dcc": dcc_key, "path": path, "found": path is not None}


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


@router.get("/{dcc_key}/ping")
async def ping_dcc(dcc_key: str) -> dict:
    """HTTP-level ping — confirms the DCC server module is actually running."""
    if dcc_key == "houdini":
        from dcc.houdini.client import houdini_client
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, houdini_client.ping)
        return {"connected": result.get("ok", False), "version": result.get("version")}
    raise HTTPException(status_code=400, detail=f"Ping not implemented for: {dcc_key}")


@router.get("/{dcc_key}/autostart")
async def get_autostart(dcc_key: str) -> dict:
    """Check whether the FLUX autostart block is installed for a DCC."""
    mod = _AUTOSTART_MODULES.get(dcc_key)
    if mod is None:
        raise HTTPException(status_code=400, detail=f"Autostart not supported for: {dcc_key}")
    loop = asyncio.get_event_loop()
    exe = await loop.run_in_executor(None, lambda: _config.get("dcc_paths", {}).get(dcc_key))
    installed = await loop.run_in_executor(None, lambda: mod.is_installed(exe))
    startup = await loop.run_in_executor(None, lambda: mod.get_startup_file(exe))
    return {"installed": installed, "startup_file": str(startup) if startup else None}


@router.post("/{dcc_key}/autostart")
async def install_autostart(dcc_key: str) -> dict:
    """Install FLUX autostart block in a DCC's startup script."""
    mod = _AUTOSTART_MODULES.get(dcc_key)
    if mod is None:
        raise HTTPException(status_code=400, detail=f"Autostart not supported for: {dcc_key}")
    loop = asyncio.get_event_loop()
    exe = await loop.run_in_executor(None, lambda: _config.get("dcc_paths", {}).get(dcc_key))
    result = await loop.run_in_executor(None, lambda: mod.install(exe))
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.delete("/{dcc_key}/autostart")
async def remove_autostart(dcc_key: str) -> dict:
    """Remove FLUX autostart block from a DCC's startup script."""
    mod = _AUTOSTART_MODULES.get(dcc_key)
    if mod is None:
        raise HTTPException(status_code=400, detail=f"Autostart not supported for: {dcc_key}")
    loop = asyncio.get_event_loop()
    exe = await loop.run_in_executor(None, lambda: _config.get("dcc_paths", {}).get(dcc_key))
    result = await loop.run_in_executor(None, lambda: mod.uninstall(exe))
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.websocket("/ws/status")
async def dcc_status_websocket(websocket: WebSocket):
    """Push DCC status every 2 seconds via WebSocket (probes run in parallel)."""
    await websocket.accept()
    try:
        while True:
            status = await _probe_all_dccs()
            await websocket.send_json(status)
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        pass
