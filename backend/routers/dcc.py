# routers/dcc.py — DCC connection status + command execution + WebSocket push.

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
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


@router.get("/houdini/state")
async def houdini_state() -> dict:
    """Return current Houdini state: selected nodes, frame, path, hip file."""
    from dcc.houdini.client import houdini_client
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, houdini_client.state)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


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


class HoudiniImportCreateRequest(BaseModel):
    network_path: str
    file_path: str


class HoudiniImportSetPathRequest(BaseModel):
    node_path: str
    file_path: str


class HoudiniMoveToLocalRequest(BaseModel):
    file_path: str


@router.post("/houdini/import/create")
async def houdini_import_create(req: HoudiniImportCreateRequest) -> dict:
    """Create a Houdini import node (type auto-detected from extension)."""
    from dcc.houdini.houdini_import import create_import_node
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: create_import_node(req.network_path, req.file_path)
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Import failed"))
    return result


@router.post("/houdini/import/set_path")
async def houdini_import_set_path(req: HoudiniImportSetPathRequest) -> dict:
    """Update the file path parameter on an existing Houdini import node."""
    from dcc.houdini.houdini_import import set_import_path
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: set_import_path(req.node_path, req.file_path)
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Set path failed"))
    return result


@router.post("/houdini/import/move_to_local")
async def houdini_import_move_to_local(req: HoudiniMoveToLocalRequest) -> dict:
    """Copy a pipeline file into $HIP/sourceimages/ of the current Houdini project."""
    from dcc.houdini.houdini_import import move_to_local
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: move_to_local(req.file_path)
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Move to local failed"))
    return result


class HoudiniGeoExportRequest(BaseModel):
    node_path: str
    file_path: str
    extension: str = ".bgeo"


class HoudiniSceneExportRequest(BaseModel):
    file_path: str
    extension: str = ".hip"


class HoudiniPublishRequest(BaseModel):
    project_name: str
    filename: str               # base name without version/ext, e.g. "CHAR_RIG_HorseBody_adam"
    extension: str              # e.g. ".abc"
    rop_node_path: str | None = None  # uses Houdini selection when None
    is_sequence: bool = False
    frame_range: list[int] | None = None   # [start, end, step]
    frame_padding: int = 4
    description: str = ""
    user: str | None = None


@router.post("/houdini/export/geo")
async def houdini_export_geo(req: HoudiniGeoExportRequest) -> dict:
    """Export geometry from a Houdini SOP node. Requires Houdini to be running with FLUX server."""
    from dcc.houdini.houdini_export import export_geo
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: export_geo(req.node_path, req.file_path, req.extension)
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Export failed"))
    return result


@router.post("/houdini/export/scene")
async def houdini_export_scene(req: HoudiniSceneExportRequest) -> dict:
    """Save the current Houdini scene to disk. Requires Houdini to be running with FLUX server."""
    from dcc.houdini.houdini_export import export_scene
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: export_scene(req.file_path, req.extension)
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Export failed"))
    return result


@router.post("/houdini/publish")
async def houdini_publish(req: HoudiniPublishRequest) -> dict:
    """Houdini ROP publish workflow.

    Builds a versioned pipeline path from tokens, sets it on the selected (or given)
    ROP node, triggers the cook, then archives the previous version.
    Sequence mode creates a versioned subfolder with $F4 frame tokens.
    """
    from core import config
    from core.paths import get_project_path
    from dcc.houdini.houdini_export import publish_houdini_rop

    user = req.user or config.get_current_user() or "unknown"
    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    frame_range = tuple(req.frame_range) if req.frame_range and len(req.frame_range) == 3 else None  # type: ignore[arg-type]

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_houdini_rop(
            project_path=project_path,
            filename=req.filename,
            extension=req.extension,
            rop_node_path=req.rop_node_path,
            is_sequence=req.is_sequence,
            frame_range=frame_range,
            frame_padding=req.frame_padding,
            description=req.description,
            user=user,
        ),
    )

    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Publish failed"))
    return result


# ── Houdini Importer HDA endpoints ───────────────────────────────────────────


class HoudiniBuildHdaRequest(BaseModel):
    hda_path: str


@router.get("/houdini/importer/tokens")
async def houdini_importer_tokens(project: str = "") -> dict:
    """Return project list and token map for populating the HDA dropdowns.

    When *project* is provided, tokens for that project are included.
    Always returns the full list of known projects.
    """
    from core.paths import get_project_path
    from features.importer.importer_resolve import get_import_tokens, get_project_list

    loop = asyncio.get_event_loop()
    projects = await loop.run_in_executor(None, get_project_list)
    tokens: dict = {}
    if project:
        project_path = get_project_path(project)
        if project_path.exists():
            tokens = await loop.run_in_executor(None, lambda: get_import_tokens(project_path))
    return {"projects": projects, "tokens": tokens}


@router.get("/houdini/importer/resolve")
async def houdini_importer_resolve(
    project: str,
    class_tok: str = Query("", alias="class"),
    type: str = "",
    name: str = "",
    instance: str = "null",
    iter: str = "LAST",
) -> dict:
    """Resolve token parameters to an absolute file path on disk."""
    from core.paths import get_project_path
    from features.importer.importer_resolve import resolve_import_path

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: resolve_import_path(project_path, class_tok, type, name, instance, iter),
    )
    return result


@router.get("/houdini/importer/iters")
async def houdini_importer_iters(
    project: str,
    class_tok: str = Query("", alias="class"),
    type: str = "",
    name: str = "",
    instance: str = "null",
) -> dict:
    """Return sorted iteration labels available on disk for the given tokens."""
    from core.paths import get_project_path
    from features.importer.importer_resolve import get_available_iters

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")

    loop = asyncio.get_event_loop()
    iters = await loop.run_in_executor(
        None,
        lambda: get_available_iters(project_path, class_tok, type, name, instance),
    )
    return {"iters": iters}


class HoudiniInjectModuleRequest(BaseModel):
    hda_name: str = "flux_importer"


@router.post("/houdini/importer/inject_module")
async def houdini_importer_inject_module(req: HoudiniInjectModuleRequest) -> dict:
    """Inject the FLUX PythonModule into an already-loaded HDA definition.

    Use when the HDA was created manually and its Python module section is empty.
    Houdini must be running with the FLUX server active.
    All existing node instances in the scene are reloaded automatically.
    """
    from dcc.houdini.hda.flux_importer_hda import inject_module

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: inject_module(req.hda_name))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Inject failed"))
    return result


@router.post("/houdini/importer/build_hda")
async def houdini_importer_build_hda(req: HoudiniBuildHdaRequest) -> dict:
    """Build the FLUX Importer HDA in the running Houdini instance.

    Saves the .hda file to *hda_path*. Houdini must be running with the
    FLUX server active (port 48884).
    """
    from dcc.houdini.hda.flux_importer_hda import build_hda

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: build_hda(req.hda_path))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "HDA build failed"))
    return result


@router.get("/houdini/importer/module")
async def houdini_importer_module() -> dict:
    """Serve the HDA PythonModule implementation for the bootstrap to exec().

    The HDA contains only a 15-line bootstrap that fetches and exec()s this
    response at load time. Updating _MODULE_FUNCTIONS here updates all HDA
    instances automatically — no re-injection required.
    """
    from dcc.houdini.hda.flux_importer_hda import _MODULE_FUNCTIONS
    return {"code": _MODULE_FUNCTIONS}


@router.get("/houdini/importer/open_hub")
async def houdini_importer_open_hub() -> dict:
    """Best-effort stub — signal to open/focus the FLUX Hub.

    Full integration with the Importer page is pending.
    Returns ok=True unconditionally so the HDA callback never errors out.
    """
    return {"ok": True, "message": "Hub open requested (stub)"}


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
