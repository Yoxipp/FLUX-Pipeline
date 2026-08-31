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
from dcc.maya    import autostart as _maya_autostart
from dcc.zbrush  import autostart as _zbrush_autostart
from features.launcher.launcher_core import find_dcc_exe, get_installed_dccs, launch_dcc

# Maps dcc_key (lowercase) → autostart module. Extend here when adding new DCCs.
_AUTOSTART_MODULES: dict = {
    "houdini": _houdini_autostart,
    "maya":    _maya_autostart,
    "zbrush":  _zbrush_autostart,
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
    if dcc_key == "zbrush":
        from dcc.zbrush.client import zbrush_client
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, zbrush_client.ping)
        return {"connected": result.get("ok", False), "version": result.get("version")}
    if dcc_key == "maya":
        from dcc.maya.maya_connection import is_server_running
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, is_server_running)
        return {"connected": ok, "version": None}
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


class HoudiniFluxImporterCreateRequest(BaseModel):
    project:       str = ""
    flux_class:    str = ""
    flux_type:     str = ""
    flux_name:     str = ""
    flux_instance: str = ""
    flux_iter:     str = "LAST"


@router.post("/houdini/importer/create_node")
async def houdini_importer_create_node(req: HoudiniFluxImporterCreateRequest) -> dict:
    """Create a flux_importer HDA node in the active Houdini network."""
    from dcc.houdini.houdini_import import create_flux_importer_node
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: create_flux_importer_node(
            req.project, req.flux_class, req.flux_type,
            req.flux_name, req.flux_instance, req.flux_iter,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Create node failed"))
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
    export_options: dict | None = None     # ROP parms to set (see houdini_export)
    attr_filter: dict | None = None        # {"mode": "keep"|"remove", "names": [...]}
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
            options=req.export_options,
            attr_filter=req.attr_filter,
        ),
    )

    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Publish failed"))
    return result


class HoudiniLightExportRequest(BaseModel):
    project_name: str
    asset:        str
    filename:     str | None = None   # full base for the token publish path
    skel_node:    str | None = None
    mesh_node:    str | None = None
    frame_start:  int | None = None
    frame_end:    int | None = None
    fmt:          str = "usd"
    # Which USD layers/data to author (same contract as the Maya light export).
    include_geo:     bool = True
    include_skel:    bool = True
    include_anim:    bool = True
    include_weights: bool = True
    include_uv:      bool = True


@router.post("/houdini/export-usd")
async def houdini_export_usd(req: HoudiniLightExportRequest) -> dict:
    """Light layered UsdSkel export from a KineFX rig: Houdini extracts, backend authors."""
    from core.paths import get_project_path
    from dcc.houdini.houdini_usd_light_export import run_light_export

    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    dest_dir = None
    base_name = None
    if req.filename:
        from features.folder_manager.naming_validator import get_base_name
        from features.publisher.publish_core import resolve_publish_path

        full = f"{req.filename}.{req.fmt}"
        rp = resolve_publish_path(project_path, full)
        if rp is None:
            raise HTTPException(status_code=400, detail=f"Chemin de publish introuvable pour {req.filename}")
        dest_dir, base_name = str(rp), get_base_name(full)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: run_light_export(
            req.asset, str(project_path),
            skel_node=req.skel_node, mesh_node=req.mesh_node,
            frame_start=req.frame_start, frame_end=req.frame_end, fmt=req.fmt,
            dest_dir=dest_dir, base_name=base_name,
            include_geo=req.include_geo, include_skel=req.include_skel,
            include_anim=req.include_anim, include_weights=req.include_weights,
            include_uv=req.include_uv,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Export USD léger échoué"))
    return result


class HoudiniCharacterImportRequest(BaseModel):
    file_path:    str            # absolute path to a skinned .usd*/.fbx
    network_path: str = "/obj"   # where to create the import (wraps in a geo if OBJ ctx)


@router.post("/houdini/import-character")
async def houdini_import_character(req: HoudiniCharacterImportRequest) -> dict:
    """Import a skinned asset as a KineFX character → mesh carries boneCapture.

    Uses kinefx::usdcharacterimport (.usd*) / kinefx::fbxcharacterimport (.fbx).
    """
    from dcc.houdini.client import houdini_client
    from dcc.houdini.houdini_import import create_character_import_node

    if not houdini_client.is_connected():
        raise HTTPException(status_code=503, detail="Houdini non connecté (lance le serveur FLUX dans Houdini)")
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None, lambda: create_character_import_node(req.network_path, req.file_path)
    )
    if not resp.get("ok"):
        raise HTTPException(status_code=503, detail=resp.get("error", "Import KineFX character échoué"))
    return resp.get("result", {})


# ── Maya endpoints ───────────────────────────────────────────────────────────


class MayaPublishRequest(BaseModel):
    project_name: str
    filename:     str               # base name without version/ext, e.g. "CHAR_RIG_HorseBody_adam"
    extension:    str               # e.g. ".abc"
    scope:        str = "scene"    # "scene" | "selection"
    is_sequence:  bool = False
    frame_range:  list[int] | None = None   # [start, end]
    export_options: dict | None = None      # per-format export options (see maya_export)
    description:  str = ""
    user:         str | None = None


@router.get("/maya/connect_cmd")
async def maya_connect_cmd() -> dict:
    """Return the Python command to paste in Maya's Script Editor to open commandPort."""
    from pathlib import Path as _PL
    backend = str(_PL(__file__).resolve().parent.parent)
    cmd = (
        f"import sys; sys.path.insert(0, r'{backend}'); "
        f"import maya.cmds as cmds; "
        f"cmds.commandPort(name=':7001', sourceType='python', noreturn=False); "
        f"print('[FLUX] commandPort 7001 opened')"
    )
    return {"cmd": cmd, "backend": backend}


@router.get("/maya/diag")
async def maya_diag() -> dict:
    """Diagnostic — reports autostart install state and what's actually in userSetup.py."""
    from dcc.maya import autostart as _ma
    loop = asyncio.get_event_loop()
    startup = await loop.run_in_executor(None, lambda: _ma.get_startup_file())
    installed = await loop.run_in_executor(None, lambda: _ma.is_installed())
    snippet: str | None = None
    if startup and startup.exists():
        try:
            content = startup.read_text(encoding="utf-8")
            # Extract just the FLUX block for inspection
            begin = "# >>> FLUX autostart"
            end   = "# <<< FLUX autostart"
            b = content.find(begin)
            e = content.find(end, b)
            if b >= 0 and e >= 0:
                snippet = content[b : e + len(end)]
        except OSError:
            pass
    return {
        "startup_file": str(startup) if startup else None,
        "file_exists": startup.exists() if startup else False,
        "installed": installed,
        "flux_block_snippet": snippet,
    }


class MayaImportRequest(BaseModel):
    project_name: str
    rel_path: str  # project-relative path, e.g. "CHAR/RIG/HorseBody/adam/HorseBody_adam.fbx"


_MAYA_IMPORT_EXTS = {".obj", ".fbx", ".ma", ".mb", ".abc", ".usd", ".usda", ".usdc", ".usdz"}


@router.post("/maya/import")
async def maya_import_file(req: MayaImportRequest) -> dict:
    """Import a file into the current Maya scene via commandPort.

    Resolves the absolute path from project_name + rel_path, then sends
    import_file() to Maya. Supports .obj .fbx .ma .mb .abc (Alembic cache).
    """
    from pathlib import Path as _PLib
    from core.paths import get_project_path
    from dcc.maya.maya_connection import send_command_direct

    ext = _PLib(req.rel_path).suffix.lower()
    if ext not in _MAYA_IMPORT_EXTS:
        raise HTTPException(status_code=400, detail=f"Format non supporté pour l'import Maya : {ext}")

    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    file_path = project_path / req.rel_path.replace("/", "\\")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Fichier introuvable : {file_path}")

    import json as _json
    import os as _os
    import shutil as _shutil
    import tempfile as _tempfile

    _backend_root = str(_PLib(__file__).resolve().parent.parent)
    fp_fwd = str(file_path).replace("\\", "/")
    # Maya writes a JSON result envelope here so the hub knows if the import actually
    # succeeded (Maya runs in another process; a plain call always looked like success).
    result_dir = _tempfile.mkdtemp(prefix="flux_maya_import_")
    result_path = result_dir.replace("\\", "/") + "/_flux_import_result.json"
    cmd = (
        f"import sys; sys.path.insert(0, r'{_backend_root}'); "
        f"sys.modules.pop('dcc.maya.maya_import', None); "
        f"from dcc.maya.maya_import import run_import; "
        f"run_import(r'{fp_fwd}', r'{result_path}')"
    )

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: send_command_direct(cmd, timeout=30.0))
        if result is None:
            raise HTTPException(
                status_code=503,
                detail="Maya ne répond pas. Assure-toi que Maya est ouvert et le commandPort actif.",
            )

        # Read the envelope; mirror Maya's logs into the hub logger (Flux console) and
        # keep error lines for the failure detail.
        ok = False
        maya_errors: list[str] = []
        if _os.path.exists(result_path):
            try:
                with open(result_path, encoding="utf-8") as _fh:
                    envelope = _json.load(_fh)
            except (OSError, ValueError):
                envelope = None
            if envelope:
                ok = bool(envelope.get("ok"))
                for rec in envelope.get("logs", []):
                    lvl = str(rec.get("level", "INFO")).upper()
                    text = f"[Maya] {rec.get('msg', '')}"
                    if lvl in ("ERROR", "CRITICAL"):
                        log.error(text)
                        maya_errors.append(str(rec.get("msg", "")))
                    elif lvl == "WARNING":
                        log.warning(text)
                    else:
                        log.info(text)

        if not ok:
            reason = f" ({' | '.join(maya_errors)})" if maya_errors else ""
            log.error("Import Maya échoué : %s%s", fp_fwd, reason)
            raise HTTPException(status_code=500, detail=f"Import Maya échoué : {_PLib(fp_fwd).name}{reason}")

        return {"ok": True, "file": fp_fwd}
    finally:
        await loop.run_in_executor(None, lambda: _shutil.rmtree(result_dir, ignore_errors=True))


class MayaLightExportRequest(BaseModel):
    project_name: str
    asset:        str
    filename:     str | None = None   # full base (CLASS_TYPE_NAME_INSTANCE) for token path
    mesh:         str | None = None
    root_joint:   str | None = None
    frame_start:  int | None = None
    frame_end:    int | None = None
    fmt:          str = "usd"
    # What to include in the light export (checkboxes in the Publisher).
    include_geo:     bool = True
    include_skel:    bool = True
    include_anim:    bool = True
    include_weights: bool = True   # UsdSkel skin binding (bone capture)
    include_uv:      bool = True


@router.post("/maya/export-usd")
async def maya_export_usd(req: MayaLightExportRequest) -> dict:
    """Light layered UsdSkel export: Maya extracts raw data, the backend authors USD.

    Maya writes a JSON envelope (no pxr in Maya); the hub rebuilds the LightAsset and
    publishes it with pxr into {asset}/model/usd as the active LAST set.
    """
    import json as _json
    import os as _os
    import shutil as _shutil
    import tempfile as _tempfile
    from pathlib import Path as _PLib

    from core.paths import get_project_path
    from dcc.maya.maya_connection import send_command_direct

    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    _backend_root = str(_PLib(__file__).resolve().parent.parent)
    result_dir = _tempfile.mkdtemp(prefix="flux_maya_light_")
    result_path = result_dir.replace("\\", "/") + "/_flux_light_export.json"

    def _arg(v: object) -> str:
        if v is None:
            return "None"
        if isinstance(v, int):
            return str(v)
        return "r'" + str(v).replace("'", "") + "'"

    cmd = (
        f"import sys; sys.path.insert(0, r'{_backend_root}'); "
        f"sys.modules.pop('dcc.maya.maya_usd_light_export', None); "
        f"from dcc.maya.maya_usd_light_export import run_light_export; "
        f"run_light_export({_arg(req.asset)}, r'{result_path}', "
        f"mesh={_arg(req.mesh)}, root_joint={_arg(req.root_joint)}, "
        f"frame_start={_arg(req.frame_start)}, frame_end={_arg(req.frame_end)}, "
        f"include_geo={_arg(req.include_geo)}, include_skel={_arg(req.include_skel)}, "
        f"include_anim={_arg(req.include_anim)}, include_weights={_arg(req.include_weights)}, "
        f"include_uv={_arg(req.include_uv)})"
    )

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: send_command_direct(cmd, timeout=300.0))
        if result is None:
            raise HTTPException(
                status_code=503,
                detail="Maya ne répond pas. Ouvre Maya avec le bridge FLUX actif.",
            )

        # Read the envelope; mirror Maya's logs into the Flux console.
        maya_errors: list[str] = []
        envelope = None
        if _os.path.exists(result_path):
            try:
                with open(result_path, encoding="utf-8") as _fh:
                    envelope = _json.load(_fh)
            except (OSError, ValueError):
                envelope = None
        if envelope:
            for rec in envelope.get("logs", []):
                lvl = str(rec.get("level", "INFO")).upper()
                text = f"[Maya] {rec.get('msg', '')}"
                if lvl in ("ERROR", "CRITICAL"):
                    log.error(text)
                    maya_errors.append(str(rec.get("msg", "")))
                elif lvl == "WARNING":
                    log.warning(text)
                else:
                    log.info(text)

        if not envelope or not envelope.get("ok") or not envelope.get("asset"):
            reason = f" ({' | '.join(maya_errors)})" if maya_errors else ""
            raise HTTPException(status_code=500, detail=f"Export USD léger échoué{reason}")

        # Author + publish with pxr, backend-side (Maya stays pxr-free). Resolve the
        # destination from tokens so the light asset lands next to normal publishes,
        # grouped in a {base}_LAST folder.
        from features.usd_export import publish_light_asset
        from features.usd_export.contract import light_asset_from_dict

        dest_dir = None
        base_name = None
        if req.filename:
            from features.folder_manager.naming_validator import get_base_name
            from features.publisher.publish_core import resolve_publish_path

            full = f"{req.filename}.{req.fmt}"
            dest_dir = resolve_publish_path(project_path, full)
            if dest_dir is None:
                raise HTTPException(status_code=400, detail=f"Chemin de publish introuvable pour {req.filename}")
            base_name = get_base_name(full)

        light = light_asset_from_dict(envelope["asset"])
        pub = await loop.run_in_executor(
            None,
            lambda: publish_light_asset(
                light, project_path, fmt=req.fmt, dest_dir=dest_dir, base_name=base_name
            ),
        )
        log.info("Light USD export published: %s (%s) -> %s", base_name or req.asset, pub["version"], pub["folder"])
        return {"ok": True, "asset": base_name or req.asset, "version": pub["version"],
                "root": str(pub["root"]), "folder": str(pub["folder"])}
    finally:
        await loop.run_in_executor(None, lambda: _shutil.rmtree(result_dir, ignore_errors=True))


@router.post("/maya/publish")
async def maya_publish(req: MayaPublishRequest) -> dict:
    """Maya publish workflow.

    Resolves the pipeline path from tokens, sends an export command to Maya
    (which writes the file to a temp location), then archives the previous version.
    For .abc with is_sequence, passes frame_range to AbcExport.
    """
    import shutil
    import tempfile

    import os

    from core import config
    from core.paths import get_project_path
    from dcc.maya.maya_connection import send_command_direct
    from features.folder_manager.naming_validator import format_version, get_base_name
    from features.publisher.publish_core import publish_file, resolve_publish_path
    from features.publisher.version_resolver import get_last_file, get_next_version

    user = req.user or config.get_current_user() or "unknown"
    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    ext = req.extension if req.extension.startswith(".") else f".{req.extension}"
    filename_with_ext = f"{req.filename}{ext}"

    # Pre-flight: compute the version number that will be assigned after publish
    loop = asyncio.get_event_loop()
    dest_folder = await loop.run_in_executor(
        None, lambda: resolve_publish_path(project_path, filename_with_ext)
    )
    if dest_folder is not None:
        base_name = get_base_name(filename_with_ext)
        next_ver  = await loop.run_in_executor(None, lambda: get_next_version(dest_folder, base_name))
        had_last  = await loop.run_in_executor(None, lambda: get_last_file(dest_folder, base_name)) is not None
        new_ver   = next_ver + 1 if had_last else next_ver
        version_str = format_version(new_ver)
    else:
        version_str = "001"

    # Build temp export path
    tmp_dir = await loop.run_in_executor(None, lambda: tempfile.mkdtemp(prefix="flux_maya_pub_"))
    tmp_path = str(tmp_dir).replace("\\", "/") + f"/{filename_with_ext}"
    # Maya writes a JSON result envelope here (captures its own logs for the console)
    result_path = str(tmp_dir).replace("\\", "/") + "/_flux_export_result.json"

    # Flux backend path — prepended to every Maya command so dcc.maya.* is importable
    # even in sessions started before the autostart was installed.
    from pathlib import Path as _PLib
    _backend_root = str(_PLib(__file__).resolve().parent.parent)  # backend/

    # Drop the cached export module so a running Maya picks up updated backend code
    # without needing a restart (Maya keeps sys.modules across commandPort calls).
    path_prefix = (
        f"import sys; sys.path.insert(0, r'{_backend_root}'); "
        f"sys.modules.pop('dcc.maya.maya_export', None)"
    )

    # Build single-line command (semicolons) — Maya commandPort runs this in exec() context.
    # run_publish_export writes a JSON envelope to result_path with Maya's own logs so
    # the hub can report the real failure reason (Maya is a separate process).
    scope = "scene" if req.scope == "scene" else "selection"

    # Export options travel as base64(JSON) so the single-line Maya command stays
    # quote-safe (base64 is [A-Za-z0-9+/=], never breaks the surrounding quotes).
    import base64 as _b64
    import json as _json2
    opts_b64 = ""
    if req.export_options:
        opts_b64 = _b64.b64encode(_json2.dumps(req.export_options).encode("utf-8")).decode("ascii")

    if ext == ".abc" and req.is_sequence and req.frame_range and len(req.frame_range) == 2:
        fs, fe = req.frame_range
        cmd = (
            f"{path_prefix}; "
            f"from dcc.maya.maya_export import run_publish_export; "
            f"run_publish_export(r'{tmp_path}', '{ext}', '{scope}', r'{result_path}', "
            f"frame_start={fs}, frame_end={fe}, options_b64='{opts_b64}')"
        )
    else:
        cmd = (
            f"{path_prefix}; "
            f"from dcc.maya.maya_export import run_publish_export; "
            f"run_publish_export(r'{tmp_path}', '{ext}', '{scope}', r'{result_path}', options_b64='{opts_b64}')"
        )

    # Timeout: 30s for static exports, 600s for animated ABC (100 frames can be slow)
    export_timeout = 600.0 if (ext == ".abc" and req.is_sequence) else 120.0

    try:
        result = await loop.run_in_executor(None, lambda: send_command_direct(cmd, timeout=export_timeout))
        if result is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Maya ne répond pas sur le port 7001. "
                    "Assure-toi que le commandPort est ouvert : dans Maya > Script Editor, "
                    "exécute cmds.commandPort(name=':7001', sourceType='python', noreturn=False)"
                ),
            )

        # Read the envelope Maya wrote; mirror its logs into the hub logger so they
        # appear in the Flux console, and keep any error lines for the failure detail.
        maya_errors: list[str] = []
        if os.path.exists(result_path):
            import json as _json
            try:
                with open(result_path, encoding="utf-8") as _fh:
                    envelope = _json.load(_fh)
            except (OSError, ValueError) as exc:
                log.warning("Could not read Maya export envelope: %s", exc)
                envelope = None
            if envelope:
                for rec in envelope.get("logs", []):
                    lvl = str(rec.get("level", "INFO")).upper()
                    text = f"[Maya] {rec.get('msg', '')}"
                    if lvl in ("ERROR", "CRITICAL"):
                        log.error(text)
                        maya_errors.append(str(rec.get("msg", "")))
                    elif lvl == "WARNING":
                        log.warning(text)
                    else:
                        log.info(text)

        if not os.path.exists(tmp_path):
            reason = f" ({' | '.join(maya_errors)})" if maya_errors else ""
            log.error("Export Maya échoué, fichier absent : %s%s", tmp_path, reason)
            raise HTTPException(
                status_code=503,
                detail=f"Export Maya échoué, fichier absent : {tmp_path}{reason}",
            )

        from pathlib import Path as _Path
        pub_result = await loop.run_in_executor(
            None,
            lambda: publish_file(_Path(tmp_path), project_path, req.description, user, req.project_name),
        )
        if pub_result is None:
            raise HTTPException(status_code=500, detail="publish_core a échoué")

        return {"ok": True, "version_str": version_str, "dest": str(pub_result)}
    finally:
        await loop.run_in_executor(None, lambda: shutil.rmtree(tmp_dir, ignore_errors=True))


# ── ZBrush endpoints ──────────────────────────────────────────────────────────



class ZBrushPublishRequest(BaseModel):
    project_name:   str
    filename:       str
    extension:      str
    export_options: dict  = {}
    keep_local:     bool  = False
    local_dir:      str | None = None
    description:    str | None = None
    user:           str | None = None


@router.post("/zbrush/publish")
async def zbrush_publish(req: ZBrushPublishRequest) -> dict:
    """ZBrush publish workflow.

    Resolves the pipeline path from tokens, sends the export command to ZBrush
    (which writes the file directly), then archives the previous version.
    Optionally copies the output to a local directory (keep_local).
    """
    from core import config
    from core.paths import get_project_path
    from dcc.zbrush.zbrush_export import publish_zbrush

    user = req.user or config.get_current_user() or "unknown"
    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_zbrush(
            project_path=project_path,
            filename=req.filename,
            extension=req.extension,
            export_options=req.export_options,
            description=req.description or "",
            user=user,
            project_name=req.project_name,
            keep_local=req.keep_local,
            local_dir=req.local_dir,
        ),
    )

    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Publish failed"))
    return result


@router.post("/zbrush/cancel")
async def cancel_zbrush() -> dict:
    """Release ZBrush from the freeze loop (user cancelled the publish)."""
    from dcc.zbrush.client import zbrush_client
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, zbrush_client.cancel)
    return {"cancelled": result.get("ok", False)}


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


@router.get("/houdini/importer/path_to_tokens")
async def houdini_importer_path_to_tokens(project: str, rel_path: str) -> dict:
    """Reverse-map a project-relative filesystem path to FLUX tokens.

    Returns {CLASS, TYPE, NAME, INSTANCE} — empty strings for unresolved tokens.
    """
    from core.paths import get_project_path
    from features.importer.importer_resolve import path_to_tokens as _path_to_tokens
    project_path = get_project_path(project)
    rel_parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    return _path_to_tokens(project_path, rel_parts)


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
