# routers/dcc.py — DCC connection status + command execution + WebSocket push.

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core import config as _config
from core.constants import DCC_COLORS, DCC_PORT_RANGES, DCC_PORTS
from core.dcc_instances import scan_instances
from core.logger import get_logger
from core.socket_manager import socket_manager
from dcc.houdini import autostart as _houdini_autostart
from dcc.maya    import autostart as _maya_autostart
from dcc.nuke    import autostart as _nuke_autostart
from dcc.zbrush  import autostart as _zbrush_autostart
from dcc.substance_painter import autostart as _substance_autostart
from dcc.mari    import autostart as _mari_autostart
from features.launcher.launcher_core import find_dcc_exe, get_installed_dccs, launch_dcc
from dcc.maya.maya_export_client import ANIM_EXTS as MAYA_ANIM_EXTS

# Maps dcc_key (lowercase) → autostart module. Extend here when adding new DCCs.
# Keys are the ONE canonical frontend key per soft (matches Sidebar SOFTWARE,
# launcher _FRONTEND_KEY_MAP and exe detection). Painter is "substance_painter"
# everywhere — the old "substance" key here was the plug-button mismatch.
_AUTOSTART_MODULES: dict = {
    "houdini": _houdini_autostart,
    "maya":    _maya_autostart,
    "nuke":    _nuke_autostart,
    "zbrush":  _zbrush_autostart,
    "substance_painter": _substance_autostart,
    "mari":    _mari_autostart,
}

log = get_logger(__name__)
router = APIRouter()

# ── Continuous Maya zombie detection (throttled) ──────────────────────────────
# find_stuck_maya() shells out to netstat/tasklist, so it is far too heavy to run
# on every 2s status push. We cache its verdict and only re-run it when the cache
# is stale AND Maya's port is unreachable (a responsive Maya is never a zombie).
import time as _time

_MAYA_STUCK_CACHE: dict = {"ts": 0.0, "stuck": False, "pid": None}
_MAYA_STUCK_TTL_S: float = 8.0


def _maya_stuck_throttled() -> tuple[bool, int | None]:
    """Return (stuck, pid) for the Maya commandPort, re-checking at most every TTL."""
    now = _time.monotonic()
    if now - _MAYA_STUCK_CACHE["ts"] < _MAYA_STUCK_TTL_S:
        return _MAYA_STUCK_CACHE["stuck"], _MAYA_STUCK_CACHE["pid"]
    from dcc.maya.port_guard import find_stuck_maya
    stuck = find_stuck_maya()
    _MAYA_STUCK_CACHE.update(
        ts=now, stuck=stuck is not None, pid=(stuck["pid"] if stuck else None)
    )
    return _MAYA_STUCK_CACHE["stuck"], _MAYA_STUCK_CACHE["pid"]


def _invalidate_maya_stuck_cache() -> None:
    """Force the next status probe to re-check (used right after a reap)."""
    _MAYA_STUCK_CACHE.update(ts=0.0, stuck=False, pid=None)


class CommandRequest(BaseModel):
    dcc: str
    command: str
    # Multi-instance: target a specific instance by port. None → the DCC's base
    # (legacy single-instance) port, preserving current behaviour.
    port: int | None = None


class CommandResult(BaseModel):
    success: bool
    result: str
    dcc: str


class LaunchRequest(BaseModel):
    dcc: str
    exe_path: str | None = None


async def _probe_all_dccs() -> dict:
    """Discover every DCC's running instances in parallel. Returns status dict.

    Multi-instance (cluster C): each DCC entry carries an `instances` list (one
    record per reachable port in the DCC's range). `connected` and `port` are kept
    for back-compat — `connected` is true when at least one instance is up, and
    `port` is the lowest open instance port (or the base port when none is up).
    """
    loop = asyncio.get_event_loop()
    names = list(DCC_PORT_RANGES.keys())
    # One executor task per DCC scans its whole port range; DCCs run in parallel.
    scans = await asyncio.gather(
        *[loop.run_in_executor(None, lambda d=name: scan_instances(d)) for name in names]
    )
    status = {}
    for name, instances in zip(names, scans):
        base = DCC_PORTS[name]
        status[name] = {
            "connected": len(instances) > 0,
            "port":      instances[0]["port"] if instances else base,
            "color":     DCC_COLORS.get(name, DCC_COLORS["disconnected"]),
            "instances": instances,
        }

    # Continuous zombie detection: surface a stuck Maya (port bound by a headless
    # maya.exe that never accepts) so the UI can offer a reap without waiting for a
    # launch. Only runs when no Maya instance is up, and is throttled internally.
    # (Still checks the base commandPort 7001 — per-instance zombie detection is a
    # later phase, once the DCC side registers each instance's port.)
    maya = status.get("Maya")
    if maya is not None and not maya["connected"]:
        stuck, pid = await loop.run_in_executor(None, _maya_stuck_throttled)
        maya["stuck"] = stuck
        maya["stuck_pid"] = pid

    return status


@router.get("/status")
async def get_dcc_status() -> dict:
    """Return reachability state for every known DCC."""
    return await _probe_all_dccs()


def _resolve_target_port(dcc: str, port: int | None) -> int:
    """Resolve (dcc, optional port) to the concrete instance port to talk to.

    A given port must fall inside the DCC's range; None falls back to the base
    (legacy single-instance) port. Raises HTTPException(400) on a bad pairing.
    """
    if dcc not in DCC_PORT_RANGES:
        raise HTTPException(status_code=400, detail=f"DCC inconnu : {dcc}")
    if port is None:
        return DCC_PORTS[dcc]
    base, count = DCC_PORT_RANGES[dcc]
    if not (base <= port < base + count):
        raise HTTPException(status_code=400, detail=f"Port {port} hors de la plage de {dcc}")
    return port


@router.post("/execute", response_model=CommandResult)
async def execute_command(req: CommandRequest) -> CommandResult:
    """Send a Python command to a connected DCC instance via TCP socket."""
    target = _resolve_target_port(req.dcc, req.port)

    loop = asyncio.get_event_loop()
    if not await loop.run_in_executor(None, lambda: socket_manager.is_port_connected(target)):
        connected = await loop.run_in_executor(None, lambda: socket_manager.connect_port(target))
        if not connected:
            raise HTTPException(status_code=503, detail=f"{req.dcc} non connecté (port {target})")

    result = await loop.run_in_executor(
        None, lambda: socket_manager.send_command_port_safe(target, req.command)
    )
    if result is None:
        return CommandResult(success=False, result="Pas de réponse du DCC", dcc=req.dcc)
    return CommandResult(success=True, result=result, dcc=req.dcc)


@router.get("/instances/{dcc_key}")
async def get_dcc_instances(dcc_key: str) -> dict:
    """List the running instances of a single DCC (one record per open port)."""
    if dcc_key not in DCC_PORT_RANGES:
        raise HTTPException(status_code=400, detail=f"DCC inconnu : {dcc_key}")
    loop = asyncio.get_event_loop()
    instances = await loop.run_in_executor(None, lambda: scan_instances(dcc_key))
    return {"dcc": dcc_key, "instances": instances}


@router.post("/connect/{dcc_name}")
async def connect_dcc(dcc_name: str, port: int | None = Query(None)) -> dict:
    """Explicitly open a socket connection to a DCC instance (base port if omitted)."""
    target = _resolve_target_port(dcc_name, port)
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: socket_manager.connect_port(target))
    return {"dcc": dcc_name, "port": target, "connected": ok}


@router.post("/disconnect/{dcc_name}")
async def disconnect_dcc(dcc_name: str, port: int | None = Query(None)) -> dict:
    target = _resolve_target_port(dcc_name, port)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: socket_manager.disconnect_port(target))
    return {"dcc": dcc_name, "port": target, "connected": False}


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


def _ping_houdini() -> dict:
    from dcc.houdini.client import houdini_client
    return houdini_client.ping()


def _ping_zbrush() -> dict:
    from dcc.zbrush.client import zbrush_client
    return zbrush_client.ping()


def _ping_maya() -> dict:
    from dcc.maya.maya_connection import is_server_running
    return {"ok": is_server_running(), "version": None}


def _ping_nuke() -> dict:
    from dcc.nuke.client import nuke_client
    return nuke_client.ping()


def _ping_photoshop() -> dict:
    from dcc.photoshop.client import ping as ps_ping
    return ps_ping()


def _ping_painter() -> dict:
    from dcc.substance_painter.client import substance_client
    return substance_client.ping()


def _ping_mari() -> dict:
    from dcc.mari.client import mari_client
    return mari_client.ping()


_PING_PROBES = {
    "houdini": _ping_houdini,
    "zbrush": _ping_zbrush,
    "maya": _ping_maya,
    "nuke": _ping_nuke,
    "photoshop": _ping_photoshop,
    "substance_painter": _ping_painter,
    "mari": _ping_mari,
}

# The Sidebar and the Publisher poll the same DCCs every few seconds: one probe per
# DCC per _PING_TTL_S serves them all, and a lock keeps concurrent polls from each
# opening a socket (a closed DCC holds an executor thread for the connect timeout).
_PING_TTL_S = 2.0
_ping_cache: dict[str, tuple[float, dict]] = {}
_ping_locks: dict[str, asyncio.Lock] = {}


@router.get("/{dcc_key}/ping")
async def ping_dcc(dcc_key: str) -> dict:
    """HTTP-level ping: confirms the DCC server module is actually running (cached 2 s)."""
    probe = _PING_PROBES.get(dcc_key)
    if probe is None:
        raise HTTPException(status_code=400, detail=f"Ping not implemented for: {dcc_key}")
    hit = _ping_cache.get(dcc_key)
    if hit and time.monotonic() - hit[0] < _PING_TTL_S:
        return hit[1]
    lock = _ping_locks.setdefault(dcc_key, asyncio.Lock())
    async with lock:
        hit = _ping_cache.get(dcc_key)
        if hit and time.monotonic() - hit[0] < _PING_TTL_S:
            return hit[1]
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, probe)
        except Exception as exc:  # noqa: BLE001 - a probe never breaks the poll
            log.debug("Ping %s failed: %s", dcc_key, exc)
            result = {}
        answer = {"connected": bool(result.get("ok", False)), "version": result.get("version")}
        _ping_cache[dcc_key] = (time.monotonic(), answer)
    return answer


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
    dest_folder: str = ""   # explicit local dir; empty → $HIP/sourceimages/


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
        None, lambda: move_to_local(req.file_path, req.dest_folder or None)
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
    # Exact project-relative path of the file the user selected in the folder
    # manager. Used to re-path a selected node with the file they actually picked
    # (the token flow below resolves to a default format/iter and can pick a
    # different category folder, e.g. .abc instead of the selected .obj).
    rel_path:      str = ""


@router.post("/houdini/importer/create_node")
async def houdini_importer_create_node(req: HoudiniFluxImporterCreateRequest) -> dict:
    """Create a flux_importer node in the active Houdini network.

    Resolves the concrete file backend-side so the node can fall back to a native
    importer when the flux_importer HDA is not registered in the running Houdini.
    """
    from pathlib import Path as _PLib

    from dcc.houdini.houdini_import import (
        create_flux_importer_node, set_path_on_selected_if_match,
    )
    from core.paths import get_project_path
    from features.importer.importer_resolve import resolve_import_path
    from features.importer.usd_probe import USD_EXTS

    # Backend-side token → absolute path (fallback for when the HDA is absent).
    resolved_path = ""
    if req.project and req.flux_class and req.flux_type and req.flux_name:
        pp = get_project_path(req.project)
        if pp.exists():
            r = resolve_import_path(
                pp, req.flux_class, req.flux_type, req.flux_name,
                req.flux_instance, req.flux_iter or "LAST",
            )
            if r.get("ok"):
                resolved_path = r.get("path") or ""

    # The exact file the user selected (project-relative → absolute). This is what
    # a selected node should be re-pathed to — NOT the token-resolved path, which
    # picks a default format/iter and can land in a different category folder.
    selected_file = ""
    if req.rel_path and req.project:
        pp = get_project_path(req.project)
        cand = pp / req.rel_path.replace("/", "\\")
        if cand.exists():
            selected_file = str(cand)

    # F2: store portable "$FLUX/..." tokens on the created / re-pathed node so the
    # scene stays portable. Opt-in; Houdini expands $FLUX (F1 package) at cook.
    from flux_actions.switch import portable_paths_enabled
    if portable_paths_enabled():
        from core.paths import to_flux_token
        if resolved_path:
            resolved_path = to_flux_token(resolved_path)
        if selected_file:
            selected_file = to_flux_token(selected_file)

    loop = asyncio.get_event_loop()

    # USD: import by context (Reference LOP in /stage, flux_importer HDA in SOP whose
    # source matches the file: tokens for a task publish, USD library for a component /
    # assembly, free path otherwise).
    if selected_file and _PLib(req.rel_path).suffix.lower() in USD_EXTS:
        from dcc.houdini.houdini_import import create_usd_context_import
        from features.importer.library_import import importer_source_for_file
        from features.importer.usd_probe import probe_usd

        abs_file = str(get_project_path(req.project) / req.rel_path.replace("/", "\\"))
        probe = await loop.run_in_executor(None, lambda: probe_usd(abs_file))
        # SOP context: flux_importer HDA pointing at the same file (tokens / library / path).
        importer = await loop.run_in_executor(
            None, lambda: importer_source_for_file(get_project_path(req.project), abs_file))
        if importer.get("source_mode") == "file":
            importer["free_path"] = selected_file
        importer["project"] = req.project
        resp = await loop.run_in_executor(
            None, lambda: create_usd_context_import(selected_file, probe, importer))
        if not resp.get("ok"):
            raise HTTPException(status_code=503, detail=resp.get("error", "Import USD echoue"))
        return resp

    # Prefer re-pathing a matching selected import node over creating a new one.
    # Only possible when we know the concrete selected file; otherwise (and on any
    # non-match) fall through to the create/HDA path below.
    if selected_file:
        sel = await loop.run_in_executor(
            None, lambda: set_path_on_selected_if_match(selected_file)
        )
        if not sel.get("ok"):
            raise HTTPException(status_code=503, detail=sel.get("error", "Set path failed"))
        if sel.get("matched"):
            return {"ok": True, "result": {
                "node_path": sel.get("node_path"),
                "resolved_path": selected_file,
                "mode": sel.get("mode", "replaced"),
            }}

    result = await loop.run_in_executor(
        None,
        lambda: create_flux_importer_node(
            req.project, req.flux_class, req.flux_type,
            req.flux_name, req.flux_instance, req.flux_iter,
            resolved_path,
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
    from flux_actions.switch import engine_publish_enabled

    user = req.user or config.get_current_user() or "unknown"
    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    frame_range = tuple(req.frame_range) if req.frame_range and len(req.frame_range) == 3 else None  # type: ignore[arg-type]

    loop = asyncio.get_event_loop()

    # Engine path (default; FLUX_LEGACY_PUBLISH falls back to legacy). Same UI,
    # same endpoint, same response shape — only the logic underneath changes.
    # The runner reuses publish_houdini_rop whole, so both paths cook identically.
    if engine_publish_enabled("houdini"):
        from flux_actions.runner import run_houdini_publish_action

        result = await loop.run_in_executor(
            None,
            lambda: run_houdini_publish_action(
                base_name=req.filename,
                extension=req.extension,
                project_path=project_path,
                description=req.description,
                user=user,
                project_name=req.project_name,
                rop_node_path=req.rop_node_path,
                is_sequence=req.is_sequence,
                frame_range=list(req.frame_range) if req.frame_range else None,
                frame_padding=req.frame_padding,
                options=req.export_options,
                attr_filter=req.attr_filter,
            ),
        )
        if result is None:
            raise HTTPException(status_code=503, detail="Publish failed")
        return result

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
    frame_range:  list[float] | None = None  # [start, end(, step)] one animated .abc / USD file
    export_options: dict | None = None      # per-format export options (see maya_export)
    description:  str = ""
    user:         str | None = None
    port:         int | None = None  # target Maya instance (None → base commandPort)


@router.get("/maya/connect_cmd")
async def maya_connect_cmd() -> dict:
    """Return the Python command to paste in Maya's Script Editor to open commandPort."""
    from pathlib import Path as _PL
    backend = str(_PL(__file__).resolve().parent.parent)
    cmd = (
        f"import sys; sys.path.insert(0, r'{backend}'); "
        f"import maya.cmds as cmds; "
        f"cmds.commandPort(name='127.0.0.1:7001', sourceType='python', noreturn=False); "
        f"print('[FLUX] commandPort 7001 opened')"
    )
    return {"cmd": cmd, "backend": backend}


@router.get("/maya/port_status")
async def maya_port_status() -> dict:
    """Report whether a stuck ('zombie') Maya is holding the commandPort.

    Used by the launcher UI to offer a one-click reap before launching Maya.
    Returns {"stuck": bool, "pid": int|None, "name": str|None}.
    """
    from dcc.maya.port_guard import find_stuck_maya
    loop = asyncio.get_event_loop()
    stuck = await loop.run_in_executor(None, find_stuck_maya)
    if stuck is None:
        return {"stuck": False, "pid": None, "name": None}
    return {"stuck": True, "pid": stuck["pid"], "name": stuck["name"]}


@router.post("/maya/reap")
async def maya_reap() -> dict:
    """Terminate a stuck Maya holding the commandPort (re-verified before killing).

    Returns {"killed": bool, "pid": int|None, "message": str}.
    """
    from dcc.maya.port_guard import reap_stuck_maya
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, reap_stuck_maya)
    # Drop the cached verdict so the next status push reflects the reap immediately
    # instead of showing a stale "stuck" banner for up to one TTL.
    _invalidate_maya_stuck_cache()
    return result


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
    port: int | None = None  # target Maya instance (None → base commandPort)


_MAYA_IMPORT_EXTS = {".obj", ".fbx", ".ma", ".mb", ".abc", ".usd", ".usda", ".usdc", ".usdz"}
# USD container extensions whose binary-crate form must be transcoded to ASCII for Maya.
_USD_IMPORT_EXTS = {".usd", ".usda", ".usdc", ".usdz"}


def _maya_usd_source(file_path, work_dir: str):
    """Return a USD path Maya's mayaUsd can actually read.

    Maya 2024 ships an older mayaUsd that fails with "Error reading file" on two
    things FLUX produces: binary crates authored by the backend's recent USD, and
    files under an accented path (OneDrive "Projets d'ete"), even for
    a plain ASCII .usda whose sublayers are fine. Flattening the composed stage into a
    self-contained ASCII .usda inside *work_dir* (an ASCII temp dir the caller owns and
    cleans up) avoids both: one file, no sublayer/reference resolution, no accents.
    .usdz packages and unreadable stages are returned unchanged.
    """
    from pathlib import Path as _PLib

    src = _PLib(file_path)
    if src.suffix.lower() == ".usdz":
        return str(src).replace("\\", "/")

    try:
        from pxr import Usd
        stage = Usd.Stage.Open(str(src))
        if stage is None:
            return str(src).replace("\\", "/")
        out = _PLib(work_dir) / (src.stem + ".usda")
        stage.Flatten().Export(str(out))
        log.info("[Maya] flattened USD to ASCII for import: %s", src.name)
        return str(out).replace("\\", "/")
    except Exception as exc:
        # Best-effort: if flattening fails, fall back to the original file.
        log.warning("[Maya] USD flatten for import failed for %s: %s", src.name, exc)
        return str(src).replace("\\", "/")


@router.post("/maya/import")
async def maya_import_file(req: MayaImportRequest) -> dict:
    """Import a file into the current Maya scene via commandPort.

    Resolves the absolute path from project_name + rel_path, then sends
    import_file() to Maya. Supports .obj .fbx .ma .mb .abc (Alembic cache) and USD
    (binary crate is transcoded to ASCII .usda so Maya 2024's mayaUsd can read it).
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
    # Maya writes a JSON result envelope here so the hub knows if the import actually
    # succeeded (Maya runs in another process; a plain call always looked like success).
    result_dir = _tempfile.mkdtemp(prefix="flux_maya_import_")
    result_path = result_dir.replace("\\", "/") + "/_flux_import_result.json"

    # Maya 2024's mayaUsd cannot read recent crates nor accented paths: flatten USD to a
    # temp ASCII .usda (in result_dir, cleaned up with it). Other formats pass through.
    if ext in _USD_IMPORT_EXTS:
        fp_fwd = _maya_usd_source(file_path, result_dir)
    else:
        fp_fwd = str(file_path).replace("\\", "/")

    # Every path travels as base64(UTF-8) and is decoded inside Maya. Maya's commandPort
    # decodes the incoming bytes with the system locale (cp1252 on a French Windows), so a
    # raw accented path (e.g. "OneDrive - Example School") gets mojibaked and
    # Maya reads a corrupt path → "Error reading file". base64 is pure ASCII, so it survives
    # any decode; we rebuild the real UTF-8 string on the Maya side. Same rationale as the
    # export options below.
    import base64 as _b64

    def _enc(_s: str) -> str:
        return _b64.b64encode(_s.encode("utf-8")).decode("ascii")

    cmd = (
        f"import sys, base64 as _b64; "
        f"sys.path.insert(0, _b64.b64decode('{_enc(_backend_root)}').decode('utf-8')); "
        f"sys.modules.pop('dcc.maya.maya_import', None); "
        f"from dcc.maya.maya_import import run_import; "
        f"run_import(_b64.b64decode('{_enc(fp_fwd)}').decode('utf-8'), "
        f"_b64.b64decode('{_enc(result_path)}').decode('utf-8'))"
    )

    target_port = _resolve_target_port("Maya", req.port)
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: send_command_direct(cmd, timeout=30.0, port=target_port))
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
    scope:        str = "selection"   # "scene" | "selection"
    # What to include in the light export (checkboxes in the Publisher).
    include_geo:     bool = True
    include_skel:    bool = True
    include_anim:    bool = True
    include_weights: bool = True   # UsdSkel skin binding (bone capture)
    include_uv:      bool = True
    port:            int | None = None  # target Maya instance (None → base commandPort)


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
        f"include_uv={_arg(req.include_uv)}, scope={_arg(req.scope)})"
    )

    target_port = _resolve_target_port("Maya", req.port)
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: send_command_direct(cmd, timeout=300.0, port=target_port))
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
        # destination from tokens so the light asset lands next to normal publishes:
        # an immutable {base}_vNNN/ folder + a {base}_LAST.<fmt> pointer layer (ADR 0017).
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
        try:
            pub = await loop.run_in_executor(
                None,
                lambda: publish_light_asset(
                    light, project_path, fmt=req.fmt, dest_dir=dest_dir, base_name=base_name
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log.info("Light USD export published: %s (%s) -> %s", base_name or req.asset, pub["version"], pub["folder"])
        return {"ok": True, "asset": base_name or req.asset, "version": pub["version"],
                "root": str(pub["root"]), "folder": str(pub["folder"]), "warnings": pub.get("warnings", [])}
    finally:
        await loop.run_in_executor(None, lambda: _shutil.rmtree(result_dir, ignore_errors=True))


@router.post("/maya/publish")
async def maya_publish(req: MayaPublishRequest) -> dict:
    """Maya publish workflow.

    Resolves the pipeline path from tokens, sends an export command to Maya
    (which writes the file to a temp location), then archives the previous version.
    frame_range exports ONE animated .abc / USD file over [start, end(, step)].
    """
    import shutil
    import tempfile

    import os

    from core import config
    from core.paths import get_project_path
    from dcc.maya.maya_connection import send_command_direct
    from features.folder_manager.naming_validator import format_version, get_base_name
    from features.publisher.publish_core import publish_file, resolve_publish_path
    from features.publisher.publish_layout import next_publish_version

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
        new_ver   = await loop.run_in_executor(
            None, lambda: next_publish_version(dest_folder, base_name, ext))
        version_str = format_version(new_ver)
    else:
        version_str = "001"

    # Engine path (default; FLUX_LEGACY_PUBLISH falls back to legacy). Same UI,
    # same endpoint, same response shape. The runner drives the SAME
    # run_publish_export over the commandPort and reuses copy_publish, so both
    # paths export and land identically. version_str stays the pre-flight number
    # the legacy path returns. Placed before the legacy temp dir so nothing leaks.
    from flux_actions.switch import engine_publish_enabled

    if engine_publish_enabled("maya"):
        from flux_actions.runner import run_maya_publish_action

        scope = "scene" if req.scope == "scene" else "selection"
        target_port = _resolve_target_port("Maya", req.port)
        # One animated file over the range (abc / USD): independent of is_sequence.
        is_anim = bool(ext in MAYA_ANIM_EXTS and req.frame_range and len(req.frame_range) >= 2)
        dest = await loop.run_in_executor(
            None,
            lambda: run_maya_publish_action(
                base_name=req.filename,
                extension=ext,
                scope=scope,
                project_path=project_path,
                description=req.description,
                user=user,
                project_name=req.project_name,
                port=target_port,
                frame_range=list(req.frame_range) if is_anim else None,
                options=req.export_options,
            ),
        )
        if dest is None:
            raise HTTPException(status_code=503, detail="Publish Maya (moteur) échoué")
        return {"ok": True, "version_str": version_str, "dest": str(dest)}

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

    is_anim = bool(ext in MAYA_ANIM_EXTS and req.frame_range and len(req.frame_range) >= 2)
    if is_anim:
        fs, fe = int(req.frame_range[0]), int(req.frame_range[1])
        step = float(req.frame_range[2]) if len(req.frame_range) > 2 else 1.0
        cmd = (
            f"{path_prefix}; "
            f"from dcc.maya.maya_export import run_publish_export; "
            f"run_publish_export(r'{tmp_path}', '{ext}', '{scope}', r'{result_path}', "
            f"frame_start={fs}, frame_end={fe}, frame_step={step}, options_b64='{opts_b64}')"
        )
    else:
        cmd = (
            f"{path_prefix}; "
            f"from dcc.maya.maya_export import run_publish_export; "
            f"run_publish_export(r'{tmp_path}', '{ext}', '{scope}', r'{result_path}', options_b64='{opts_b64}')"
        )

    # Timeout: 30s for static exports, 600s for animated ABC (100 frames can be slow)
    export_timeout = 600.0 if is_anim else 120.0

    target_port = _resolve_target_port("Maya", req.port)
    try:
        result = await loop.run_in_executor(None, lambda: send_command_direct(cmd, timeout=export_timeout, port=target_port))
        if result is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Maya ne répond pas sur le port 7001. "
                    "Assure-toi que le commandPort est ouvert : dans Maya > Script Editor, "
                    "exécute cmds.commandPort(name='127.0.0.1:7001', sourceType='python', noreturn=False)"
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
    """Release ZBrush from the freeze loop (user cancelled, or FLUX is closing).

    Sends 'stop' so the freeze loop breaks immediately; the bridge acks it even
    when idle, so this never hangs and is safe to call at app shutdown."""
    from dcc.zbrush.client import zbrush_client
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, zbrush_client.release)
    return {"cancelled": result.get("ok", False)}


# ── Nuke endpoints (V6 B1) ───────────────────────────────────────────────────
# Level 2 both ways: import a published EXR as a Read node; publish by ingesting
# the active Write node's already-rendered output (FLUX never re-renders).


class NukeImportRequest(BaseModel):
    project_name: str
    class_token:  str
    type_token:   str
    name_token:   str
    instance:     str = "null"
    iter:         str = "LAST"
    first:        int | None = None
    last:         int | None = None
    colorspace:   str | None = None


@router.post("/nuke/import")
async def nuke_import_read(req: NukeImportRequest) -> dict:
    """Create a Read node in Nuke for a FLUX-published file resolved from tokens."""
    from dcc.nuke.nuke_import import DEFAULT_READ_COLORSPACE, import_into_nuke

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: import_into_nuke(
            req.project_name, req.class_token, req.type_token, req.name_token,
            req.instance, req.iter, req.first, req.last,
            req.colorspace or DEFAULT_READ_COLORSPACE,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Nuke import failed"))
    return result


class NukeImportPathRequest(BaseModel):
    project_name: str
    rel_path:     str
    first:        int | None = None
    last:         int | None = None
    colorspace:   str | None = None


@router.post("/nuke/import_path")
async def nuke_import_path(req: NukeImportPathRequest) -> dict:
    """Create a Read node in Nuke from a project-relative file (Folder Manager)."""
    from dcc.nuke.nuke_import import DEFAULT_READ_COLORSPACE, import_path_into_nuke

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: import_path_into_nuke(
            req.project_name, req.rel_path, req.first, req.last,
            req.colorspace or DEFAULT_READ_COLORSPACE,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Nuke import failed"))
    return result


class NukePublishRequest(BaseModel):
    project_name:  str
    filename:      str
    extension:     str
    export_options: dict = {}
    is_sequence:   bool = False
    frame_range:   tuple[int, int] | None = None
    node_name:     str | None = None      # None -> the selected node in Nuke
    colorspace:    str | None = None      # None -> project default (color_picking)
    description:   str | None = None
    user:          str | None = None


@router.post("/nuke/publish")
async def nuke_publish_write(req: NukePublishRequest) -> dict:
    """Publish from Nuke like Houdini: build a Write on the selected node with the
    requested options, render it into the FLUX layout (Write outputs direct-to-dest)."""
    from core import config
    from dcc.nuke.nuke_publish import publish_from_nuke

    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_from_nuke(
            req.project_name, req.filename, req.extension, req.export_options,
            req.is_sequence, req.frame_range, req.node_name,
            req.description or "", user, req.colorspace,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Nuke publish failed"))
    return result


# ── Photoshop endpoints (V6 B6) ──────────────────────────────────────────────
# Backend-driven COM: FLUX resolves the FLUX destination and tells Photoshop to
# save the active document there. No in-app plugin (COM connects from outside).


class PhotoshopPublishRequest(BaseModel):
    project_name:   str
    filename:       str
    extension:      str
    export_options: dict = {}
    description:    str | None = None
    user:           str | None = None


class PhotoshopOpenRequest(BaseModel):
    project_name: str
    rel_path:     str


@router.post("/photoshop/open")
async def photoshop_open(req: PhotoshopOpenRequest) -> dict:
    """Open a project-relative file in Photoshop over COM (Folder Manager)."""
    from core.paths import get_project_path
    from dcc.photoshop.client import open_document

    file_path = get_project_path(req.project_name) / req.rel_path.replace("/", "\\")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: open_document(str(file_path)))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Photoshop open failed"))
    return result


@router.get("/photoshop/status")
async def photoshop_status() -> dict:
    """Actionable Photoshop state: lib_missing / not_running / ok (+ version)."""
    from dcc.photoshop.client import status as ps_status
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, ps_status)


@router.post("/photoshop/install")
async def photoshop_install() -> dict:
    """Install photoshop-python-api into the backend env when missing (dev)."""
    from dcc.photoshop.client import ensure_library
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, ensure_library)


@router.post("/photoshop/publish")
async def photoshop_publish(req: PhotoshopPublishRequest) -> dict:
    """Save the active Photoshop document into the FLUX layout (PSD, PNG, JPG, TIF...)."""
    from core import config
    from dcc.photoshop.photoshop_export import publish_photoshop

    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_photoshop(
            req.project_name, req.filename, req.extension, req.export_options,
            req.description or "", user,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Photoshop publish failed"))
    return result


# ── Substance Painter endpoints (V6 B2) ──────────────────────────────────────


class SubstancePublishRequest(BaseModel):
    project_name: str
    class_token:  str
    task_token:   str
    name_token:   str
    instance:     str = "null"
    preset:       str = "PBR Metallic Roughness"
    file_format:  str = "png"
    bit_depth:    str = "8"
    conform_tx:   bool = False
    description:  str | None = None
    user:         str | None = None


@router.post("/substance/publish")
async def substance_publish(req: SubstancePublishRequest) -> dict:
    """Export Substance Painter maps and ingest them into FLUX (opt .tx conform)."""
    from core import config
    from dcc.substance_painter.substance_export import publish_painter

    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_painter(
            req.project_name, req.class_token, req.task_token, req.name_token,
            req.instance, req.preset, req.file_format, req.bit_depth,
            req.conform_tx, req.description or "", user,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Substance publish failed"))
    return result


# ── Mari endpoints (V6 B7) ────────────────────────────────────────────────────


class MariPublishRequest(BaseModel):
    project_name: str
    class_token:  str
    task_token:   str
    name_token:   str
    instance:     str = "null"
    file_format:  str = "tif"
    conform_tx:   bool = False
    description:  str | None = None
    user:         str | None = None


@router.post("/mari/publish")
async def mari_publish(req: MariPublishRequest) -> dict:
    """Export Mari channels and ingest them into FLUX (opt .tx conform)."""
    from core import config
    from dcc.mari.mari_export import publish_mari

    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_mari(
            req.project_name, req.class_token, req.task_token, req.name_token,
            req.instance, req.file_format, req.conform_tx, req.description or "", user,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Mari publish failed"))
    return result


# ── File-based DCC publish (Substance Designer, Marvelous) — Level 1 (V6 B3/B4) ─
# The artist exports a file from the app; FLUX ingests it under FLUX naming, for any
# type. Reuses the tested publisher (publish_file). One endpoint per soft for a clear
# per-DCC entry point in the UI.


class FilePublishRequest(BaseModel):
    project_name: str
    source_path:  str          # the file the artist exported from the app
    target_name:  str          # composed FLUX name (tokens); ext taken from source
    description:  str | None = None
    user:         str | None = None


def _ingest_file(req: "FilePublishRequest", soft: str) -> dict:
    from pathlib import Path as _Path
    from core import config
    from core.paths import get_project_path
    from features.publisher.publish_core import publish_file

    user = req.user or config.get_current_user() or "unknown"
    source = _Path(req.source_path)
    if not source.exists():
        return {"ok": False, "error": f"Fichier source introuvable : {source}"}
    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {req.project_name}"}
    dest = publish_file(source, project_path, req.description or "", user,
                        req.project_name, req.target_name)
    if dest is None:
        return {"ok": False, "error": f"Publish {soft} échoué (nom FLUX invalide ?)"}
    return {"ok": True, "path": str(dest)}


@router.post("/designer/publish")
async def designer_publish(req: FilePublishRequest) -> dict:
    """Ingest a Substance Designer file (.sbsar / maps) into FLUX."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: _ingest_file(req, "Designer"))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Designer publish failed"))
    return result


@router.post("/marvelous/publish")
async def marvelous_publish(req: FilePublishRequest) -> dict:
    """Ingest a Marvelous Designer file (.zprj / .abc / .obj / .fbx) into FLUX."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: _ingest_file(req, "Marvelous"))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Marvelous publish failed"))
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
    # A USD publish with a skeleton (GEO with skin, RIG, ANIM) imports as a KineFX
    # character in the HDA (mesh + boneCapture, skeleton, animated skeleton).
    if result.get("ok") and result.get("path"):
        from features.importer.library_import import probe_file
        result["has_skel"] = bool(
            (await loop.run_in_executor(None, lambda: probe_file(result["path"]))).get("has_skel"))
    # F2: hand Houdini a portable "$FLUX/..." path so the HDA stores a token the
    # scene can carry across machines. Houdini expands $FLUX (F1 package) at cook.
    # Opt-in; the resolver itself stays absolute for backend-internal use.
    from flux_actions.switch import portable_paths_enabled
    if portable_paths_enabled() and result.get("ok") and result.get("path"):
        from core.paths import to_flux_token
        result["path"] = to_flux_token(result["path"])
    return result


@router.get("/houdini/importer/library")
async def houdini_importer_library(project: str) -> dict:
    """USD library items (components / assemblies) for the importer HDA "Bibliotheque" mode."""
    from core.paths import get_project_path
    from features.importer.library_import import library_items

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")
    loop = asyncio.get_event_loop()
    try:
        items = await loop.run_in_executor(None, lambda: library_items(project_path))
    except Exception as exc:
        log.exception("importer library failed")
        return {"ok": False, "error": str(exc), "items": []}
    return {"ok": True, "items": items}


@router.get("/houdini/importer/library_resolve")
async def houdini_importer_library_resolve(project: str, key: str, version: str = "LAST") -> dict:
    """Library item + version -> file ($FLUX token when portable) + has_skel."""
    from core.paths import get_project_path
    from features.importer.library_import import resolve_library_item

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: resolve_library_item(project_path, key, version))
    from flux_actions.switch import portable_paths_enabled
    if portable_paths_enabled() and result.get("ok"):
        from core.paths import to_flux_token
        result["path"] = to_flux_token(result["path"])
    return result


@router.get("/houdini/importer/probe")
async def houdini_importer_probe(file: str) -> dict:
    """Free path mode of the importer HDA: file exists? skeleton inside (USD)?"""
    from features.importer.library_import import probe_file

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: probe_file(file))


@router.get("/houdini/importer/instances")
async def houdini_importer_instances(
    project: str,
    class_tok: str = Query("", alias="class"),
    type: str = "",
    name: str = "",
) -> dict:
    """Return the instance folders that exist on disk for the given tokens.

    The INSTANCE token map usually only holds 'null', so the HDA menu reads the
    real instance folders from disk (e.g. 'allbody') here.
    """
    from core.paths import get_project_path
    from features.importer.importer_resolve import get_available_instances

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")

    loop = asyncio.get_event_loop()
    instances = await loop.run_in_executor(
        None,
        lambda: get_available_instances(project_path, class_tok, type, name),
    )
    return {"instances": instances}


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
