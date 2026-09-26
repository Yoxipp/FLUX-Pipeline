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
from dcc.substance_designer import autostart as _designer_autostart
from dcc.marvelous import autostart as _marvelous_autostart
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
    "substance_designer": _designer_autostart,
    "marvelous": _marvelous_autostart,
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
    loop = asyncio.get_running_loop()
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


async def _maya_target(port: int | None) -> int:
    """Maya port for an export / publish: never a Maya with no window (a session that
    never finished quitting keeps its port and an empty scene, live 2026-09-18)."""
    from core.dcc_instances import scan_instances
    from dcc.maya.maya_connection import GhostMayaError, pick_live_port

    requested = _resolve_target_port("Maya", port)
    loop = asyncio.get_running_loop()

    def _pick() -> int:
        open_ports = [i["port"] for i in scan_instances("Maya")]
        return pick_live_port(requested, open_ports) if open_ports else requested

    try:
        return await loop.run_in_executor(None, _pick)
    except GhostMayaError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


class ActiveInstanceRequest(BaseModel):
    dcc:  str
    port: int | None = None


@router.post("/active-instance")
async def set_active_instance(req: ActiveInstanceRequest) -> dict:
    """Instance of a DCC the user works with (sidebar menu, publish picker): clients
    without an explicit port (Houdini) follow it."""
    from core.dcc_instances import set_active_port

    try:
        set_active_port(req.dcc, req.port)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "dcc": req.dcc, "port": req.port}


def _instance_scene(dcc: str, port: int) -> str:
    """Open scene of one running instance ('' when unknown)."""
    try:
        if dcc == "Maya":
            from dcc.maya.maya_connection import send_command_direct

            res = send_command_direct(
                "__import__('maya.cmds', fromlist=['cmds']).file(q=True, sceneName=True)",
                timeout=2.0, port=port)
            return (res or "").strip().strip("\x00").strip()
        if dcc == "Houdini":
            from dcc.houdini.client import HoudiniClient

            return str(HoudiniClient(port=port)._get("/state").get("hip_file") or "")
    except Exception:                       # noqa: BLE001 - a label is best effort
        return ""
    return ""


@router.get("/instances/{dcc}")
async def list_dcc_instances(dcc: str) -> dict:
    """Running instances of *dcc* with their open scene, for the publish picker."""
    from core.dcc_instances import get_active_port, scan_instances

    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(None, lambda: scan_instances(dcc))
    for item in items:
        item["scene"] = await loop.run_in_executor(
            None, lambda p=item["port"]: _instance_scene(dcc, p)) or None
    return {"dcc": dcc, "active": get_active_port(dcc), "instances": items}


@router.post("/execute", response_model=CommandResult)
async def execute_command(req: CommandRequest) -> CommandResult:
    """Send a Python command to a connected DCC instance via TCP socket."""
    target = _resolve_target_port(req.dcc, req.port)

    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
    instances = await loop.run_in_executor(None, lambda: scan_instances(dcc_key))
    return {"dcc": dcc_key, "instances": instances}


class CloseInstanceRequest(BaseModel):
    port: int
    force: bool = False     # kill (unsaved work lost); default = like the window's X


@router.post("/instances/{dcc_key}/close")
async def close_dcc_instance(dcc_key: str, req: CloseInstanceRequest) -> dict:
    """Close one running instance of a DCC (instance menu of the sidebar)."""
    from core.dcc_process import close_instance

    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: close_instance(dcc_key, req.port, req.force))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if dcc_key == "Maya":
        _invalidate_maya_stuck_cache()
    return res


@router.post("/connect/{dcc_name}")
async def connect_dcc(dcc_name: str, port: int | None = Query(None)) -> dict:
    """Explicitly open a socket connection to a DCC instance (base port if omitted)."""
    target = _resolve_target_port(dcc_name, port)
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, lambda: socket_manager.connect_port(target))
    return {"dcc": dcc_name, "port": target, "connected": ok}


@router.post("/disconnect/{dcc_name}")
async def disconnect_dcc(dcc_name: str, port: int | None = Query(None)) -> dict:
    target = _resolve_target_port(dcc_name, port)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: socket_manager.disconnect_port(target))
    return {"dcc": dcc_name, "port": target, "connected": False}


@router.get("/find/{dcc_key}")
async def auto_find_dcc(dcc_key: str) -> dict:
    """Glob-scan default install paths for dcc_key, save if found."""
    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(None, lambda: find_dcc_exe(dcc_key))
    return {"dcc": dcc_key, "path": path, "found": path is not None}


@router.get("/installed")
async def get_installed() -> dict:
    """Return all DCCs detected on this machine."""
    loop = asyncio.get_running_loop()
    found = await loop.run_in_executor(None, get_installed_dccs)
    return {"dccs": found}


@router.post("/launch")
async def launch(req: LaunchRequest) -> dict:
    """Launch a DCC application (optionally saving a custom exe path first)."""
    from features.launcher.launcher_core import set_custom_exe_path
    loop = asyncio.get_running_loop()
    if req.exe_path:
        await loop.run_in_executor(None, lambda: set_custom_exe_path(req.dcc, req.exe_path))
    ok = await loop.run_in_executor(None, lambda: launch_dcc(req.dcc))
    return {"dcc": req.dcc, "launched": ok}


@router.get("/houdini/state")
async def houdini_state() -> dict:
    """Return current Houdini state: selected nodes, frame, path, hip file."""
    from dcc.houdini.client import houdini_client
    loop = asyncio.get_running_loop()
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


def _ping_designer() -> dict:
    from dcc.substance_designer.client import designer_client
    return designer_client.ping()


def _ping_marvelous() -> dict:
    from dcc.marvelous.client import marvelous_client
    return marvelous_client.ping()


_PING_PROBES = {
    "houdini": _ping_houdini,
    "zbrush": _ping_zbrush,
    "maya": _ping_maya,
    "nuke": _ping_nuke,
    "photoshop": _ping_photoshop,
    "substance_painter": _ping_painter,
    "mari": _ping_mari,
    "substance_designer": _ping_designer,
    "marvelous": _ping_marvelous,
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
        if result.get("busy"):
            answer["busy"] = True          # e.g. Mari exporting: reachable, just not answering
        _ping_cache[dcc_key] = (time.monotonic(), answer)
    return answer


@router.get("/{dcc_key}/autostart")
async def get_autostart(dcc_key: str) -> dict:
    """Check whether the FLUX autostart block is installed for a DCC."""
    mod = _AUTOSTART_MODULES.get(dcc_key)
    if mod is None:
        raise HTTPException(status_code=400, detail=f"Autostart not supported for: {dcc_key}")
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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


@router.get("/load-targets")
async def dcc_load_targets(project: str, rel_path: str) -> dict:
    """V4: what "Ouvrir dans..." loads for a file (asset / decor / shot first, the
    department layer second, old files refused). See features/importer/load_target.py."""
    from core.paths import get_project_path, is_subpath
    from features.importer.load_target import load_targets

    project_path = get_project_path(project)
    target = (project_path / rel_path).resolve()
    if not project_path.exists() or not is_subpath(target, project_path.resolve()):
        raise HTTPException(status_code=404, detail=f"Fichier introuvable : {rel_path}")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: load_targets(project_path, target))


class HoudiniLopImportRequest(BaseModel):
    project:  str
    rel_path: str
    mode:     str = "reference"   # reference | payload | sublayer


@router.post("/houdini/import/lop")
async def houdini_import_lop(req: HoudiniLopImportRequest) -> dict:
    """Load a project file in a LOP network as a Reference, Payload or Sublayer:
    added to the selected LOP of that kind, else a new LOP wired after the selection
    (see dcc.houdini.houdini_import.import_into_lop)."""
    from core.paths import get_project_path, is_subpath
    from dcc.houdini.houdini_import import import_into_lop

    if req.mode not in ("reference", "payload", "sublayer"):
        raise HTTPException(status_code=400, detail=f"Mode inconnu : {req.mode}")
    pp = get_project_path(req.project)
    target = (pp / req.rel_path).resolve()
    if not pp.exists() or not is_subpath(target, pp.resolve()) or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Fichier introuvable : {req.rel_path}")
    _refuse_legacy(pp, target)

    file_value = str(target)
    from flux_actions.switch import portable_paths_enabled
    if portable_paths_enabled():
        from core.paths import to_flux_token
        file_value = to_flux_token(file_value)

    loop = asyncio.get_running_loop()
    resp = await loop.run_in_executor(
        None, lambda: import_into_lop(file_value, req.mode, str(target)))
    if not resp.get("ok"):
        raise HTTPException(status_code=503, detail=resp.get("error", "Import LOP echoue"))
    return resp


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
            _refuse_legacy(pp, cand)
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

    loop = asyncio.get_running_loop()

    # LOP context: a selected Reference / Sublayer LOP receives the file as a new
    # entry, and a non-USD file (bgeo, abc, fbx...) is referenced (Houdini reads it
    # through its USD file format plugins) instead of falling back to /obj.
    if selected_file:
        from dcc.houdini.houdini_import import import_into_lop
        abs_sel = str(get_project_path(req.project) / req.rel_path.replace("/", "\\"))
        lop = await loop.run_in_executor(
            None, lambda: import_into_lop(selected_file, "auto", abs_sel))
        if not lop.get("ok"):
            raise HTTPException(status_code=503, detail=lop.get("error", "Import LOP echoue"))
        if (lop.get("result") or {}).get("handled"):
            return lop

    # Non-USD: the flux_importer HDA is USD-only, so a .bgeo/.abc/.fbx/.obj file
    # goes through a plain native import in the current pane (falls back to /obj
    # from a LOP context). Fixes "Open in Houdini" that did nothing for non-USD.
    if selected_file:
        ext = _PLib(req.rel_path).suffix.lower()
        # .bgeo.sc is a compound extension that .suffix drops the ".sc" from.
        if req.rel_path.endswith(".bgeo.sc"):
            ext = ".bgeo.sc"
        if ext not in USD_EXTS:
            from dcc.houdini.houdini_import import create_native_import_in_context
            resp = await loop.run_in_executor(
                None, lambda: create_native_import_in_context(selected_file))
            if not resp.get("ok"):
                raise HTTPException(status_code=503, detail=resp.get("error", "Import natif echoue"))
            return resp

    # USD: import by context (flux_importer HDA in /stage and in SOP, whose
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
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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

    loop = asyncio.get_running_loop()

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

    loop = asyncio.get_running_loop()
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


def _resolve_look_target(project_path, filename: str, fmt: str) -> tuple[str, str]:
    """(publish folder, base name) for a look publish, or 400 when tokens cannot place it."""
    from features.folder_manager.naming_validator import get_base_name
    from features.publisher.publish_core import resolve_publish_path

    full = f"{filename}.{fmt.lstrip('.')}"
    dest = resolve_publish_path(project_path, full)
    if dest is None:
        raise HTTPException(status_code=400, detail=f"Chemin de publish introuvable pour {filename}")
    return str(dest), get_base_name(full)


class HoudiniLookExportRequest(BaseModel):
    project_name: str
    filename:     str            # full base (CLASS_SHADING_NAME_INSTANCE)
    lop_node:     str | None = None   # LOP to export; None = display node of /stage
    fmt:          str = "usda"
    user:         str | None = None


@router.post("/houdini/export-usd-look")
async def houdini_export_usd_look(req: HoudiniLookExportRequest) -> dict:
    """Look department of an asset from Solaris: Houdini writes, the backend authors."""
    from core.paths import get_project_path
    from dcc.houdini.houdini_usd_look_export import run_look_export

    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    dest_dir, base_name = _resolve_look_target(project_path, req.filename, req.fmt)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: run_look_export(str(project_path), lop_node=req.lop_node, fmt=req.fmt,
                                dest_dir=dest_dir, base_name=base_name, user=req.user or ""),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Export look echoue"))
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
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, reap_stuck_maya)
    # Drop the cached verdict so the next status push reflects the reap immediately
    # instead of showing a stale "stuck" banner for up to one TTL.
    _invalidate_maya_stuck_cache()
    return result


@router.get("/maya/diag")
async def maya_diag() -> dict:
    """Diagnostic — reports autostart install state and what's actually in userSetup.py."""
    from dcc.maya import autostart as _ma
    loop = asyncio.get_running_loop()
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
    # USD only (V4): "import" = flattened copy (default), "proxy" = mayaUsdProxyShape
    # on the file itself (variants kept, editable).
    mode: str = "import"


# Maya import helpers live in dcc/maya/import_prep.py (V9-08); old names kept for callers.
from dcc.maya.import_prep import (  # noqa: E402
    ascii_path as _ascii_path,
    call_maya_update as _maya_call_json,
    drop_proxy_prims as _drop_proxy_prims,
    usd_source_for_maya as _maya_usd_source,
)


def _refuse_legacy(project_path, file_path) -> None:
    """V4 (ADR 0019 point 7): an old flat Constructor file is never opened in a DCC."""
    from features.importer.load_target import is_legacy_file, load_targets

    if is_legacy_file(project_path, file_path):
        raise HTTPException(status_code=400, detail=load_targets(project_path, file_path)["message"])


_MAYA_IMPORT_EXTS = {".obj", ".fbx", ".ma", ".mb", ".abc", ".usd", ".usda", ".usdc", ".usdz"}
# USD container extensions whose binary-crate form must be transcoded to ASCII for Maya.
_USD_IMPORT_EXTS = {".usd", ".usda", ".usdc", ".usdz"}


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
    _refuse_legacy(project_path, file_path)
    proxy_mode = req.mode == "proxy"
    if proxy_mode and ext not in _USD_IMPORT_EXTS:
        raise HTTPException(status_code=400, detail="Le mode proxy USD ne s'applique qu'a un fichier USD")

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
    if proxy_mode:
        # The stage itself (no flattening): mayaUsd reads the sublayers and variants. An
        # accented folder goes through its Windows short name (mayaUsd fails on accents).
        fp_fwd = _ascii_path(file_path)
        if fp_fwd is None:
            _shutil.rmtree(result_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=(
                "Chemin avec accents sans nom court Windows : ouvre plutot l'import aplati"))
    elif ext in _USD_IMPORT_EXTS:
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

    from features.importer.import_tracking import source_stamp

    tag = _json.dumps({"project": req.project_name, "source": req.rel_path.replace("\\", "/"),
                       "stamp": source_stamp(file_path), "mode": "proxy" if proxy_mode else "import"})
    cmd = (
        f"import sys, base64 as _b64; "
        f"sys.path.insert(0, _b64.b64decode('{_enc(_backend_root)}').decode('utf-8')); "
        f"sys.modules.pop('dcc.maya.maya_import', None); "
        f"sys.modules.pop('dcc.maya.maya_update', None); "
        f"from dcc.maya.maya_import import run_import; "
        f"run_import(_b64.b64decode('{_enc(fp_fwd)}').decode('utf-8'), "
        f"_b64.b64decode('{_enc(result_path)}').decode('utf-8'), "
        f"mode={'proxy' if proxy_mode else 'import'!r}, "
        f"tag_json=_b64.b64decode('{_enc(tag)}').decode('utf-8'))"
    )

    target_port = await _maya_target(req.port)
    loop = asyncio.get_running_loop()
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


class MayaUpdateImportsRequest(BaseModel):
    port: int | None = None     # the Maya that asks (shelf button "MAJ")


@router.post("/maya/update-imports")
async def maya_update_imports(req: MayaUpdateImportsRequest) -> dict:
    """Bring the FLUX imports of the Maya scene to their LAST (X4): each tagged import whose
    published file changed is re-imported in place (same parent and transform); vNNN
    imports stay frozen. Called by the shelf button "MAJ" of the Maya that asks."""
    import json as _json
    import shutil as _shutil
    import tempfile as _tempfile

    from core.paths import get_project_path
    from features.importer.import_tracking import plan_updates, summary

    port = await _maya_target(req.port)
    loop = asyncio.get_running_loop()
    listed = await loop.run_in_executor(None, lambda: _maya_call_json(port, "run_list"))
    if listed is None:
        raise HTTPException(status_code=503, detail="Maya ne repond pas (commandPort).")
    items = listed.get("items", [])
    projects = {p: get_project_path(p) for p in {str(i.get("project") or "") for i in items} if p}
    plan = plan_updates(items, {k: v for k, v in projects.items() if v.exists()})
    done, failed = 0, []
    for entry in plan:
        if entry["status"] != "update":
            continue
        project_path = projects[entry["project"]]
        file_path = project_path / entry["source"]
        tmp = _tempfile.mkdtemp(prefix="flux_maya_update_src_")
        try:
            if entry["mode"] == "proxy":
                fp = str(file_path).replace("\\", "/")
            elif file_path.suffix.lower() in _USD_IMPORT_EXTS:
                fp = await loop.run_in_executor(None, lambda: _maya_usd_source(file_path, tmp))
            else:
                fp = str(file_path).replace("\\", "/")
            tag = _json.dumps({"project": entry["project"], "source": entry["source"],
                               "stamp": entry["stamp"], "mode": entry["mode"] or "import"})
            res = await loop.run_in_executor(
                None, lambda: _maya_call_json(port, "run_replace", entry["node"], fp, tag, timeout=120.0))
        finally:
            await loop.run_in_executor(None, lambda: _shutil.rmtree(tmp, ignore_errors=True))
        if res and res.get("ok"):
            done += 1
            entry["status"] = "updated"
        else:
            failed.append(entry["node"].rsplit("|", 1)[-1])
            log.warning("[Maya] MAJ import %s echouee : %s", entry["node"], (res or {}).get("error"))
    message = summary(plan, done, failed)
    log.info("[Maya] %s", message)
    return {"ok": not failed, "message": message, "items": plan}


@router.get("/maya/anim-range")
async def maya_anim_range(scope: str = "scene", port: int | None = None) -> dict:
    """First / last key of the animation to export (U1): selection and its hierarchy
    (scope=selection) or the whole scene; the playback range when there is no key."""
    target = await _maya_target(port)
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, lambda: _maya_call_json(
        target, "run_anim_range", "selection" if scope == "selection" else "scene",
        timeout=20.0, module="maya_keys"))
    if res is None:
        raise HTTPException(status_code=503, detail="Maya ne repond pas (commandPort).")
    if not res.get("ok"):
        raise HTTPException(status_code=500, detail=str(res.get("error") or "plage introuvable"))
    return res


@router.get("/maya/character-instances")
async def maya_character_instances(name: str, port: int | None = None) -> dict:
    """Instances of one character in the Maya scene (U2): top nodes / namespaces named
    after it or FLUX imports of it, with their instance number (DINGO_02 -> 2)."""
    target = await _maya_target(port)
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, lambda: _maya_call_json(
        target, "run_list_instances", name, timeout=20.0, module="maya_instances"))
    if res is None:
        raise HTTPException(status_code=503, detail="Maya ne repond pas (commandPort).")
    if not res.get("ok"):
        raise HTTPException(status_code=500, detail=str(res.get("error") or "liste impossible"))
    return res


@router.get("/houdini/anim-range")
async def houdini_anim_range() -> dict:
    """Houdini animation range (U1): the playbar range (caches and ROPs follow it)."""
    from dcc.houdini.client import houdini_client

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, lambda: houdini_client.run(
        "result = [int(v) for v in hou.playbar.frameRange()]", timeout=10.0))
    if not res or not res.get("ok"):
        raise HTTPException(status_code=503, detail="Houdini ne repond pas.")
    start, end = res["result"]
    return {"ok": True, "start": start, "end": end, "source": "timeline", "curves": 0}


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
    root:         str | None = None   # one character instance node (U2), overrides scope
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
        f"include_uv={_arg(req.include_uv)}, scope={_arg(req.scope)}, root={_arg(req.root)})"
    )

    target_port = await _maya_target(req.port)
    loop = asyncio.get_running_loop()
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


class MayaLookExportRequest(BaseModel):
    project_name: str
    filename:     str            # full base (CLASS_SHADING_NAME_INSTANCE)
    fmt:          str = "usda"
    scope:        str = "scene"  # "scene" | "selection"
    user:         str | None = None
    port:         int | None = None


@router.post("/maya/export-usd-look")
async def maya_export_usd_look(req: MayaLookExportRequest) -> dict:
    """Look department of an asset from Maya: mayaUSDExport writes a throwaway USD,
    the backend rewrites it into /<NAME>/mtl + bindings and publishes it (ADR 0019)."""
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

    dest_dir, base_name = _resolve_look_target(project_path, req.filename, req.fmt)

    _backend_root = str(_PLib(__file__).resolve().parent.parent)
    work_dir = _tempfile.mkdtemp(prefix="flux_maya_look_")
    out_path = work_dir.replace("\\", "/") + "/look_export.usda"
    result_path = work_dir.replace("\\", "/") + "/_flux_look_export.json"

    cmd = (
        f"import sys; sys.path.insert(0, r'{_backend_root}'); "
        f"sys.modules.pop('dcc.maya.maya_usd_look_export', None); "
        f"from dcc.maya.maya_usd_look_export import run_look_export; "
        f"run_look_export(r'{out_path}', r'{result_path}', scope='{req.scope}')"
    )

    target_port = await _maya_target(req.port)
    loop = asyncio.get_running_loop()
    try:
        sent = await loop.run_in_executor(
            None, lambda: send_command_direct(cmd, timeout=300.0, port=target_port))
        if sent is None:
            raise HTTPException(status_code=503,
                                detail="Maya ne repond pas. Ouvre Maya avec le bridge FLUX actif.")

        envelope = None
        if _os.path.exists(result_path):
            try:
                with open(result_path, encoding="utf-8") as _fh:
                    envelope = _json.load(_fh)
            except (OSError, ValueError):
                envelope = None
        maya_errors: list[str] = []
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
        if not envelope or not envelope.get("ok") or not envelope.get("usd"):
            reason = f" ({' | '.join(maya_errors)})" if maya_errors else ""
            raise HTTPException(status_code=500, detail=f"Export look echoue{reason}")

        from features.usd_export.look_export import publish_look_asset

        try:
            pub = await loop.run_in_executor(
                None,
                lambda: publish_look_asset(envelope["usd"], project_path, fmt=req.fmt,
                                           dest_dir=dest_dir, base_name=base_name,
                                           user=req.user or ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        log.info("Look published: %s (%s) -> %s", base_name, pub["version"], pub["folder"])
        return {"ok": True, "asset": base_name, "version": pub["version"],
                "root": str(pub["root"]), "materials": pub["materials"],
                "bindings": pub["bindings"], "warnings": pub["warnings"]}
    finally:
        await loop.run_in_executor(None, lambda: _shutil.rmtree(work_dir, ignore_errors=True))


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
    loop = asyncio.get_running_loop()
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
        target_port = await _maya_target(req.port)
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

    target_port = await _maya_target(req.port)
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

    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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

    loop = asyncio.get_running_loop()
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

    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: open_document(str(file_path)))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Photoshop open failed"))
    return result


@router.get("/photoshop/status")
async def photoshop_status() -> dict:
    """Actionable Photoshop state: lib_missing / not_running / ok (+ version)."""
    from dcc.photoshop.client import status as ps_status
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, ps_status)


@router.post("/photoshop/install")
async def photoshop_install() -> dict:
    """Install photoshop-python-api into the backend env when missing (dev)."""
    from dcc.photoshop.client import ensure_library
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, ensure_library)


@router.post("/photoshop/publish")
async def photoshop_publish(req: PhotoshopPublishRequest) -> dict:
    """Save the active Photoshop document into the FLUX layout (PSD, PNG, JPG, TIF...)."""
    from core import config
    from dcc.photoshop.photoshop_export import publish_photoshop

    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_running_loop()
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
    texture_sets: list[str] | None = None   # None / [] = every texture set
    size:         int | None = None         # output width, None = the set's own size
    padding:      str = "infinite"          # Painter dilation algorithm
    dilation:     int = 16                  # pixels, for the non-infinite algorithms
    maps:         list[str] | None = None   # output maps of the preset (fileName), None = all
    map_params:   dict[str, dict] | None = None   # {fileName: {"bit_depth", "size"}}
    channels:     list[dict] | None = None  # "Canaux du shader": [{"id", "label", "gray"}]


@router.post("/substance/publish")
async def substance_publish(req: SubstancePublishRequest) -> dict:
    """Export Substance Painter maps and ingest them into FLUX (opt .tx conform)."""
    from core import config
    from dcc.substance_painter.substance_export import publish_painter

    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_painter(
            req.project_name, req.class_token, req.task_token, req.name_token,
            req.instance, req.preset, req.file_format, req.bit_depth,
            req.conform_tx, req.description or "", user,
            req.texture_sets, req.size, req.padding, req.dilation,
            req.maps, req.map_params, req.channels,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Substance publish failed"))
    return result


@router.get("/texture/formats")
async def texture_formats() -> dict:
    """Bit depths each texture format holds (Publisher: per-map format / depth menus)."""
    from dcc.texture_convert import FORMAT_DEPTHS, SIZES
    return {"formats": {k: list(v) for k, v in FORMAT_DEPTHS.items()}, "sizes": list(SIZES)}


class PainterPresetsUpdate(BaseModel):
    project: str
    presets: list[str]


@router.get("/substance/presets")
async def substance_presets(project: str = "") -> dict:
    """Export presets FLUX ships, and those the project uses (Publisher offers only them)."""
    from core.paths import get_project_path
    from dcc.substance_painter.presets import bundled_presets, project_presets

    proj: list[str] = []
    if project and get_project_path(project).exists():
        proj = project_presets(get_project_path(project))
    return {"bundled": bundled_presets(), "project": proj}


@router.put("/substance/presets")
async def put_substance_presets(req: PainterPresetsUpdate) -> dict:
    """Change the Painter export presets of a project."""
    from core.paths import get_project_path
    from features.folder_manager.project_init import set_painter_presets

    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")
    set_painter_presets(project_path, req.presets)
    return {"project": req.presets}


@router.get("/substance/info")
async def substance_info() -> dict:
    """Texture sets of the open Painter project (Publisher export options)."""
    from dcc.substance_painter.client import substance_client

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, substance_client.info)
    if not res.get("ok"):
        raise HTTPException(status_code=503, detail=res.get("error", "Painter ne repond pas"))
    return res


def _mari_error(error: str | None, default: str) -> str:
    """Mari's error, plus where the bridge is and its log when Mari does not answer."""
    from dcc.mari import autostart as mari_autostart

    msg = error or default
    low = msg.lower()
    if any(k in low for k in ("refused", "timed out", "timeout", "10061", "111", "no answer", "unreachable")):
        msg = f"Mari ne repond pas sur le port du bridge ({msg}). {mari_autostart.diagnose()}"
    return msg


@router.get("/mari/info")
async def mari_info() -> dict:
    """Channels of Mari's current geo (Publisher export options)."""
    from dcc.mari.client import mari_client

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, mari_client.info)
    if not res.get("ok"):
        raise HTTPException(status_code=503, detail=_mari_error(res.get("error"), "Mari ne repond pas"))
    return res


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
    channels:     list[str] | None = None   # None / [] = every channel of the current geo
    channel_params: dict[str, dict] | None = None   # {channel: {"format", "bit_depth", "size"}}


@router.post("/mari/publish")
async def mari_publish(req: MariPublishRequest) -> dict:
    """Export Mari channels and ingest them into FLUX (opt .tx conform)."""
    from core import config
    from dcc.mari.mari_export import publish_mari

    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_mari(
            req.project_name, req.class_token, req.task_token, req.name_token,
            req.instance, req.file_format, req.conform_tx, req.description or "", user,
            req.channels, req.channel_params,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=_mari_error(result.get("error"), "Mari publish failed"))
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
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: _ingest_file(req, "Designer"))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Designer publish failed"))
    return result


@router.post("/marvelous/publish")
async def marvelous_publish(req: FilePublishRequest) -> dict:
    """Ingest a Marvelous Designer file (.zprj / .abc / .obj / .fbx) into FLUX."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: _ingest_file(req, "Marvelous"))
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Marvelous publish failed"))
    return result


# ── Substance Designer / Marvelous bridges (Level 2, like Painter) ───────────
# The in-app bridge exports (Designer: graph maps / .sbsar / .sbs ; Marvelous: abc /
# obj / fbx / usd / glb / .zprj) and FLUX ingests under FLUX naming. The Level 1 file
# routes above stay for files exported by hand.


def _bridge_error(error: str | None, default: str, autostart_mod, soft: str) -> str:
    """The bridge's error, plus where it is and its log when the app does not answer."""
    msg = error or default
    low = msg.lower()
    if any(k in low for k in ("refused", "timed out", "timeout", "10061", "111", "unreachable")):
        msg = f"{soft} ne repond pas sur le port du bridge ({msg}). {autostart_mod.diagnose()}"
    return msg


class DesignerBridgePublishRequest(BaseModel):
    project_name: str
    class_token:  str
    task_token:   str
    name_token:   str
    instance:     str = "null"
    graphs:       list[dict] | None = None   # [{"package", "graph", "outputs"}], None = open graph
    file_format:  str = "png"
    size:         int | None = None          # $outputsize, None = the graph's own
    bit_depth:    str | None = None          # 8 / 16 / 16f / 32f, None = the graph's own
    maps:         bool = True
    sbsar:        bool = False
    sbs:          bool = False
    conform_tx:   bool = False
    description:  str | None = None
    user:         str | None = None


@router.get("/designer/info")
async def designer_info() -> dict:
    """Open packages / graphs / outputs of Designer (Publisher export options)."""
    from dcc.substance_designer.client import designer_client

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, designer_client.info)
    if not res.get("ok"):
        raise HTTPException(status_code=503, detail=_bridge_error(
            res.get("error"), "Designer ne repond pas", _designer_autostart, "Designer"))
    return res


@router.post("/designer/bridge/publish")
async def designer_bridge_publish(req: DesignerBridgePublishRequest) -> dict:
    """Export Designer graph maps / .sbsar / .sbs through the bridge and publish them."""
    from core import config
    from dcc.substance_designer.designer_export import publish_designer

    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_designer(
            req.project_name, req.class_token, req.task_token, req.name_token,
            req.instance, req.graphs, req.file_format, req.size, req.bit_depth,
            req.maps, req.sbsar, req.sbs, req.conform_tx, req.description or "", user,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=_bridge_error(
            result.get("error"), "Designer publish failed", _designer_autostart, "Designer"))
    return result


class MarvelousBridgePublishRequest(BaseModel):
    project_name: str
    target_name:  str                        # composed FLUX name (asset or shot)
    file_format:  str = "abc"
    options:      dict | None = None         # garment / avatar / single_object / thick / unified_uv / scale
    with_zprj:    bool = False               # also publish the .zprj source
    description:  str | None = None
    user:         str | None = None


@router.get("/marvelous/info")
async def marvelous_info() -> dict:
    """Open Marvelous project + the formats it can export (Publisher options)."""
    from dcc.marvelous.client import marvelous_client

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, marvelous_client.info)
    if not res.get("ok"):
        raise HTTPException(status_code=503, detail=_bridge_error(
            res.get("error"), "Marvelous ne repond pas", _marvelous_autostart, "Marvelous"))
    return res


@router.post("/marvelous/bridge/publish")
async def marvelous_bridge_publish(req: MarvelousBridgePublishRequest) -> dict:
    """Export the open Marvelous project through the bridge and publish it."""
    from core import config
    from dcc.marvelous.marvelous_export import publish_marvelous

    user = req.user or config.get_current_user() or "unknown"
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: publish_marvelous(
            req.project_name, req.target_name, req.file_format, req.options,
            req.with_zprj, req.description or "", user,
        ),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=_bridge_error(
            result.get("error"), "Marvelous publish failed", _marvelous_autostart, "Marvelous"))
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

    loop = asyncio.get_running_loop()
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

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: resolve_import_path(project_path, class_tok, type, name, instance, iter),
    )
    # A USD publish with a skeleton (GEO with skin, RIG, ANIM) imports as a KineFX
    # character in the HDA (mesh + boneCapture, skeleton, animated skeleton).
    if result.get("ok") and result.get("path"):
        from features.importer.library_import import probe_file
        probed = await loop.run_in_executor(None, lambda: probe_file(result["path"]))
        result["has_skel"] = bool(probed.get("has_skel"))
        result["prim_path"] = probed.get("prim_path", "")
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
    loop = asyncio.get_running_loop()
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
    loop = asyncio.get_running_loop()
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

    loop = asyncio.get_running_loop()
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

    loop = asyncio.get_running_loop()
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

    loop = asyncio.get_running_loop()
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

    loop = asyncio.get_running_loop()
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

    loop = asyncio.get_running_loop()
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


@router.get("/houdini/exporter/module")
async def houdini_exporter_module() -> dict:
    """PythonModule of the FLUX Export HDA (SOP / LOP / OBJ), exec()'d by its bootstrap."""
    from dcc.houdini.hda.flux_exporter_hda import MODULE_FUNCTIONS
    return {"code": MODULE_FUNCTIONS}


@router.get("/houdini/exporter/tokens")
async def houdini_exporter_tokens(project: str = "") -> dict:
    """Projects + token map for the FLUX Export menus (same data as the importer)."""
    return await houdini_importer_tokens(project)


class HoudiniExporterRequest(BaseModel):
    project: str
    filename: str                       # CLASS_TYPE_NAME_INSTANCE, as the Publisher builds it
    format: str                         # "bgeo.sc", "abc", "usd", ...
    source_path: str                    # the FLUX Export node (SOP / LOP) or the picked object
    frame_range: list[int] | None = None
    description: str = ""
    houdini_port: int | None = None     # the Houdini that asked (several can run)
    user: str | None = None


@router.post("/houdini/exporter/export")
async def houdini_exporter_export(req: HoudiniExporterRequest) -> dict:
    """Publish from the FLUX Export HDA: same workflow as the Publisher's Houdini ROP publish."""
    if req.houdini_port:
        from core.dcc_instances import set_active_port
        set_active_port("Houdini", req.houdini_port)
    fmt = req.format.strip().lstrip(".")
    if not fmt:
        raise HTTPException(status_code=400, detail="Format manquant")
    animated = bool(req.frame_range and len(req.frame_range) == 3)
    return await houdini_publish(HoudiniPublishRequest(
        project_name=req.project,
        filename=req.filename,
        extension="." + fmt,
        rop_node_path=req.source_path,
        # bgeo / obj write one file per frame; abc / usd / fbx one animated file.
        is_sequence=animated and fmt in ("bgeo.sc", "bgeo", "obj"),
        frame_range=req.frame_range if animated else None,
        description=req.description,
        user=req.user,
    ))


@router.get("/houdini/anim/module")
async def houdini_anim_module() -> dict:
    """PythonModule of the FLUX Anim HDA, exec()'d by its bootstrap (no rebuild on fix)."""
    from dcc.houdini.hda.flux_anim_hda import MODULE_FUNCTIONS
    return {"code": MODULE_FUNCTIONS}


@router.get("/houdini/anim/publishes")
async def houdini_anim_publishes(project: str) -> dict:
    """Shot animations (SEQ_SHOT_ANIM_<NAME>) the FLUX Anim HDA can apply."""
    from core.paths import get_project_path
    from features.importer.shot_anim import list_shot_anims

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(None, lambda: list_shot_anims(project_path))
    return {"ok": True, "items": items}


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


# ── FLUX Shot node of the sequence scene (A5) ────────────────────────────────

@router.get("/houdini/shot_switch/module")
async def houdini_shot_switch_module() -> dict:
    """PythonModule of the FLUX Shot HDA, exec()'d by its bootstrap (no rebuild on fix)."""
    from dcc.houdini.hda.flux_shot_switch_hda import MODULE_FUNCTIONS
    return {"code": MODULE_FUNCTIONS}


@router.get("/houdini/shot_switch/shots")
async def houdini_shot_switch_shots(project: str) -> dict:
    """Shots with a generated stage (ADR 0020): menus of the FLUX Shot node."""
    from core.paths import get_project_path
    from features.usd_assembler.shot_light import list_stage_shots

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")
    loop = asyncio.get_running_loop()
    shots = await loop.run_in_executor(None, lambda: list_stage_shots(project_path))
    from flux_actions.switch import portable_paths_enabled
    if portable_paths_enabled():
        from core.paths import to_flux_token
        for s in shots:
            s["last"] = to_flux_token(s["last"])
            s["files"] = {v: to_flux_token(p) for v, p in s["files"].items()}
    return {"shots": shots}


# ── FLUX Crowd node (A7, ADR 0022) ───────────────────────────────────────────

@router.get("/houdini/crowd/module")
async def houdini_crowd_module() -> dict:
    """PythonModule of the FLUX Crowd HDA, exec()'d by its bootstrap (no rebuild on fix)."""
    from dcc.houdini.hda.flux_crowd_hda import MODULE_FUNCTIONS
    return {"code": MODULE_FUNCTIONS}


class CrowdBuildRequest(BaseModel):
    project: str
    seq: str = ""                   # empty: preview without a shot (publish needs one)
    shot: str = ""
    group: str = "crowd"
    points: list[dict]              # [{"p": [x, y, z], "ry": deg, "scale": s}] from the SOP
    components: list[str]
    clips: list[str] = []
    seed: int = 0
    offset: list[float] = [0.0, 0.0]
    speed: list[float] = [1.0, 1.0]
    publish: bool = False
    user: str | None = None
    component_weights: dict[str, float] | None = None   # "more of this asset"
    clip_weights: dict[str, float] | None = None        # "more of this animation"
    sources: dict[str, dict] | None = None              # {asset: {"file", "prim"}} of input 1
    looks: dict[str, dict] | None = None                # {asset: {"variants", "inactive"}} of input 1
    rot_noise: float = 0.0                              # degrees per joint and per agent


@router.get("/houdini/crowd/shots")
async def houdini_crowd_shots(project: str) -> dict:
    """Every shot of the project (SHOT tokens), for the FLUX Crowd menus.

    Unlike FLUX Shot, a crowd does not need a generated stage: its publish creates it
    (2026-09-25: TEST_EN_DUR_V3 had shots but the menu said "aucun shot").
    Shot folders made by hand have no SHOT token: they are healed from disk first,
    as the Folder Manager does when it opens a project."""
    from core.paths import get_project_path
    from features.folder_manager.asset_creator import heal_tokens_from_disk
    from features.importer.library_import import _stage_shots

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")

    def _shots() -> list[tuple[str, str]]:
        try:
            heal_tokens_from_disk(project_path)
        except Exception:       # noqa: BLE001 - the tokens already there still list
            log.exception("crowd shots: token heal failed")
        return _stage_shots(project_path)

    loop = asyncio.get_running_loop()
    pairs = await loop.run_in_executor(None, _shots)
    return {"shots": [{"seq": seq, "shot": shot} for seq, shot in pairs]}


@router.post("/houdini/crowd/build")
async def houdini_crowd_build(req: CrowdBuildRequest) -> dict:
    """Preview (work layer in the shot) or publish (SEQ_SHOT_CROWD[_GROUP]) a crowd."""
    from core import config
    from core.paths import get_project_path
    from features.usd_assembler.crowd import build_crowd

    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")
    user = req.user or config.get("username") or ""
    offset = (tuple(req.offset) + (0.0, 0.0))[:2]
    speed = (tuple(req.speed) + (1.0, 1.0))[:2]
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: build_crowd(
            project_path, req.seq, req.shot, req.group, req.points, components=req.components,
            clips=req.clips, seed=req.seed, offset=offset, speed=speed, publish=req.publish, user=user,
            component_weights=req.component_weights, clip_weights=req.clip_weights,
            sources=req.sources, looks=req.looks, rot_noise=max(0.0, req.rot_noise)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    path = str(res["path"])
    from flux_actions.switch import portable_paths_enabled
    if portable_paths_enabled():
        from core.paths import to_flux_token
        path = to_flux_token(path)
    return {"ok": True, "path": path, "agents": res["agents"], "warnings": res["warnings"],
            "base": res.get("base", ""), "version": res.get("version", ""), "stage": res.get("stage")}


class ShotLightPublishRequest(BaseModel):
    project: str
    seq: str
    shot: str
    file: str               # light layer written by the FLUX Shot node (temp file)
    user: str | None = None


@router.get("/houdini/lighting/module")
async def houdini_lighting_module() -> dict:
    """PythonModule of the FLUX Lighting HDA, exec()'d by its bootstrap (no rebuild on fix)."""
    from dcc.houdini.hda.flux_lighting_hda import MODULE_FUNCTIONS
    return {"code": MODULE_FUNCTIONS}


@router.get("/houdini/lighting/sequences")
async def houdini_lighting_sequences(project: str) -> dict:
    """Sequences + their published light rig (FLUX Lighting menus)."""
    from core.paths import get_project_path
    from features.usd_assembler.shot_light import list_sequences

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")
    loop = asyncio.get_running_loop()
    return {"sequences": await loop.run_in_executor(None, lambda: list_sequences(project_path))}


class SequenceLightPublishRequest(BaseModel):
    project: str
    seq: str
    file: str               # layers written by the FLUX Lighting node (temp file)
    user: str | None = None


@router.post("/houdini/sequence-light/publish")
async def houdini_sequence_light_publish(req: SequenceLightPublishRequest) -> dict:
    """Publish the sequence light rig exported by FLUX Lighting (SEQ_LIGHT vNNN + LAST)."""
    from core import config
    from core.paths import get_project_path
    from features.usd_assembler.shot_light import publish_sequence_light

    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")
    user = req.user or config.get("username") or ""
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: publish_sequence_light(
            req.file, project_path, req.seq, user=user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "base": res["base"], "version": res["version"], "last": str(res["last"] or ""),
            "sequence_root": res["sequence_root"], "warnings": res["warnings"]}


@router.post("/houdini/shot-light/publish")
async def houdini_shot_light_publish(req: ShotLightPublishRequest) -> dict:
    """Publish the shot light rig exported by the FLUX Shot node (SEQ_SHOT_LIGHT)."""
    from core import config
    from core.paths import get_project_path
    from features.usd_assembler.shot_light import publish_shot_light

    project_path = get_project_path(req.project)
    if not project_path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {req.project}")
    user = req.user or config.get("username") or ""
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: publish_shot_light(
            req.file, project_path, req.seq, req.shot, user=user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "base": res["base"], "version": res["version"], "last": str(res["last"] or ""),
            "stage": res["stage"], "warnings": res.get("warnings", [])}
