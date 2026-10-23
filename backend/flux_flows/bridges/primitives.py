# primitives.py — transport primitives of the Flows (01_ARCHITECTURE §12, 02_NODES §9).
#
# Synchronous (the nodes run them in the FLOWS pool). Each one WRAPS an existing
# client, never re-implements a protocol:
#   tcp_json_call      dcc/json_bridge.send_json_line (Nuke, Mari, Painter, Designer, ZBrush)
#   http_call          dcc/houdini/client.HoudiniClient (get / post)
#   command_port_call  dcc/maya/maya_connection.send_command_direct
#   file_mailbox_call  dcc/marvelous/client.call (any mailbox folder)
#   com_call           win32com (Photoshop style; Windows only)
#   scan_ports         core/dcc_instances.scan_instances
#   launch             features/launcher/launcher_core.launch_dcc (detached: FLUX never closes it)
#   ping, wait_ready   the ping of each soft, wait_ready = ping with backoff until the timeout
# Failures raise BridgeError with a message the artist can read.

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from flux_flows.bridges import softs

LOCAL_HOST = "127.0.0.1"


class BridgeError(Exception):
    """A transport failure, message shown on the node."""


def _check(resp: Any, what: str) -> Dict[str, Any]:
    if not isinstance(resp, dict):
        raise BridgeError(f"{what} : reponse illisible")
    if resp.get("ok") is False or "error" in resp and resp.get("ok") is not True:
        raise BridgeError(f"{what} : {resp.get('error') or 'echec'}")
    return resp


def tcp_json_call(port: int, payload: Dict[str, Any], *, host: str = LOCAL_HOST, timeout: float = 60.0,
                  raise_on_error: bool = True) -> Dict[str, Any]:
    """One JSON line to a TCP bridge, its JSON answer."""
    from dcc.json_bridge import send_json_line

    resp = send_json_line(host, int(port), dict(payload), float(timeout))
    return _check(resp, f"TCP {host}:{port}") if raise_on_error else resp


def http_call(port: int, path: str, body: Optional[Dict[str, Any]] = None, *, method: str = "POST",
              timeout: float = 60.0, raise_on_error: bool = True) -> Dict[str, Any]:
    """GET or POST on a Houdini style HTTP bridge (HoudiniClient transport)."""
    from dcc.houdini.client import HoudiniClient

    if not str(path).startswith("/"):
        raise BridgeError(f"chemin HTTP `{path}` : doit commencer par /")
    client = HoudiniClient(port=int(port))
    if str(method).upper() == "GET":
        resp = client.get(path, timeout=float(timeout))
    else:
        resp = client.post(path, dict(body or {}), timeout=float(timeout))
    return _check(resp, f"HTTP {port}{path}") if raise_on_error else resp


def command_port_call(port: int, code: str, *, timeout: float = 60.0) -> str:
    """Python code to a Maya commandPort, its raw answer (str)."""
    from dcc.maya.maya_connection import send_command_direct

    resp = send_command_direct(str(code), timeout=float(timeout), port=int(port))
    if resp is None:
        raise BridgeError(f"commandPort {port} : pas de reponse (Maya ferme ou commandPort inactif)")
    return str(resp).strip().strip("\x00")


def file_mailbox_call(payload: Dict[str, Any], *, mailbox_dir: Optional[str] = None, timeout: float = 60.0,
                      raise_on_error: bool = True) -> Dict[str, Any]:
    """One request through a file mailbox (Marvelous protocol). mailbox_dir None = Marvelous'."""
    from dcc.marvelous.client import call

    box = Path(mailbox_dir) if mailbox_dir else None
    resp = call(dict(payload), float(timeout), box=box)
    return _check(resp, "boite a fichiers") if raise_on_error else resp


def com_call(prog_id: str, method: str, args: Optional[Dict[str, Any]] = None) -> Any:
    """Call *method* of the running COM object *prog_id* (never starts the application)."""
    try:
        import pythoncom  # noqa: F401  (pywin32)
        import win32com.client
    except ImportError:
        raise BridgeError("COM indisponible : Windows et pywin32 requis") from None
    pythoncom.CoInitialize()
    try:
        try:
            app = win32com.client.GetActiveObject(prog_id)
        except Exception as exc:  # noqa: BLE001 - pywintypes.com_error
            raise BridgeError(f"{prog_id} n'est pas ouvert : {exc}") from None
        target = getattr(app, method, None)
        if target is None:
            raise BridgeError(f"{prog_id} n'a pas de methode `{method}`")
        return target(**(args or {})) if callable(target) else target
    finally:
        pythoncom.CoUninitialize()


def scan_ports(soft: str) -> List[Dict[str, Any]]:
    """Running instances of *soft*: {id, dcc, port, connected, pid, ...}. An extension bridge
    (P6c) is not in DCC_PORT_RANGES: each port of its range is pinged."""
    spec = softs.get(soft)
    if spec.extension:
        if spec.transport == "file_mailbox":
            got = ping(spec.soft)
            return [{"id": f"{spec.soft}:mailbox", "dcc": spec.soft, "port": None, "pid": got.get("pid")}] \
                if got.get("ok") else []
        found = []
        for p in softs.port_range(spec.soft):
            if ping(spec.soft, p).get("ok"):
                found.append({"id": f"{spec.soft}:{p}", "dcc": spec.soft, "port": p, "pid": None})
        return found
    from core.dcc_instances import scan_instances

    return list(scan_instances(spec.dcc_key))


def launch(soft: str, scene: Optional[str] = None) -> bool:
    """Start *soft* detached from FLUX (optionally on *scene*). False when no exe is found."""
    spec = softs.get(soft)
    if spec.extension:
        from features.launcher.launcher_core import launch_exe
        from flux_flows.bridges import extension

        exe = extension.find_exe(extension.get(spec.soft))
        return bool(exe) and bool(launch_exe(exe, scene or None, label=spec.label))
    from features.launcher.launcher_core import launch_dcc

    return bool(launch_dcc(spec.launcher_key, scene or None))


def ping(soft: str, port: Optional[int] = None) -> Dict[str, Any]:
    """{ok, version} of the bridge of *soft* on *port* (default: base port). Never raises."""
    spec = softs.get(soft)
    port = int(port) if port else softs.port_range(soft).start
    try:
        if spec.transport == "http":
            resp = http_call(port, "/ping", method="GET", timeout=3.0, raise_on_error=False)
            return {"ok": resp.get("ok") is True, "version": str(resp.get("version") or ""), "port": port}
        if spec.transport == "command_port":
            out = command_port_call(port, "__import__('maya.cmds', fromlist=['cmds']).about(version=True)",
                                    timeout=3.0)
            return {"ok": True, "version": out, "port": port}
        if spec.transport == "tcp_json":
            resp = tcp_json_call(port, spec.ping, timeout=0.5 if spec.extension else 2.0, raise_on_error=False)
            ok = resp.get("ok") is True or resp.get("status") == "ok" or resp.get("pong") is True
            return {"ok": bool(ok), "version": str(resp.get("version") or ""), "port": port}
        if spec.transport == "file_mailbox":
            from dcc.marvelous.client import heartbeat, mailbox_dir

            beat = heartbeat(mailbox_dir(spec.mailbox) if spec.mailbox else None)
            return {"ok": beat is not None, "version": str((beat or {}).get("version") or ""), "port": port,
                    "pid": (beat or {}).get("pid")}
    except BridgeError as exc:
        return {"ok": False, "version": "", "port": port, "error": str(exc)}
    return {"ok": False, "version": "", "port": port, "error": f"transport {spec.transport} sans ping"}


def wait_ready(soft: str, port: Optional[int] = None, *, timeout: float = 60.0, poll: float = 1.0,
               cancelled: Optional[threading.Event] = None, ping_fn: Callable[..., Dict[str, Any]] = None,
               sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
               any_port: bool = False) -> Dict[str, Any]:
    """Ping until the bridge answers (backoff from *poll* to 5 s). *any_port*: the first
    port of the soft's range that answers (a soft just launched picks a free port)."""
    ping_fn = ping_fn or ping
    end = clock() + float(timeout)
    delay = max(0.05, float(poll))
    ports = list(softs.port_range(soft)) if any_port or not port else [int(port)]
    last: Dict[str, Any] = {}
    while True:
        if cancelled is not None and cancelled.is_set():
            raise BridgeError("annule")
        for p in ports:
            last = ping_fn(soft, p)
            if last.get("ok"):
                return last
        if clock() >= end:
            raise BridgeError(f"{softs.get(soft).label} ne repond pas apres {timeout:g} s"
                              + (f" ({last.get('error')})" if last.get("error") else ""))
        sleep(min(delay, max(0.0, end - clock())))
        delay = min(delay * 1.5, 5.0)
