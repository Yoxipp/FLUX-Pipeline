# session.py — the ``session[<soft>]`` value of the Flows (02_NODES §8, A12).
#
# A session is ONE instance of a soft a flow talks to. Contract shared by every kind:
#   run(code, timeout) -> {"ok": True, "result": <value of `result`>} | {"ok": False, "error"}
#   close()            only a headless worker is really closed (FLUX never closes a live soft)
# The dcc.* nodes only see this contract: the same flow works live and headless.
#
#   HoudiniLiveSession  HoudiniClient(port) of flux_houdini_server (HTTP /run, hou.ui thread)
#   MayaLiveSession     commandPort: the code runs in a namespace with `cmds`, its `result`
#                       comes back through a JSON file (the commandPort answer is truncated
#                       to 64 KB and decoded with the system locale: base64 both ways)
#   TcpJsonSession      Nuke style bridges {"cmd": "run", "code"} (P6b)
#   headless.WorkerSession  hython / mayapy worker (headless.py)
#
# connect_live() implements the Instance node of 02 §8: pick (active, scene, pid), then
# live_connect_only (error) or live_connect_or_open (launch then wait_ready).

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from flux_flows.bridges import primitives, softs
from flux_flows.bridges.primitives import BridgeError

MODES = ("live_connect_or_open", "live_connect_only", "headless", "farm")
PICKS = ("active", "scene", "pid")
DEFAULT_WAIT_S = 60.0


class Session:
    soft: str = ""
    mode: str = "live"          # live | headless
    port: Optional[int] = None
    pid: Optional[int] = None
    scene: str = ""
    version: str = ""

    def run(self, code: str, timeout: float = 600.0) -> Dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        """A live soft is never closed by FLUX."""

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @property
    def label(self) -> str:
        where = f":{self.port}" if self.port else (f" pid {self.pid}" if self.pid else "")
        return f"{softs.get(self.soft).label}{where} ({'Live' if self.live else 'Headless'})"

    def to_dict(self) -> Dict[str, Any]:
        return {"soft": self.soft, "mode": self.mode, "port": self.port, "pid": self.pid, "scene": self.scene,
                "version": self.version}

    def __repr__(self) -> str:   # what a link preview shows
        return f"<session {self.label}{' ' + self.scene if self.scene else ''}>"

    def call(self, code: str, timeout: float = 600.0) -> Any:
        """run() that raises BridgeError on failure and returns ``result``."""
        resp = self.run(code, timeout)
        if not isinstance(resp, dict) or not resp.get("ok"):
            raise BridgeError(str((resp or {}).get("error") or "le logiciel a refuse le code"))
        return resp.get("result")


class HoudiniLiveSession(Session):
    soft = "houdini"

    def __init__(self, port: int, *, pid: Optional[int] = None, client: Any = None) -> None:
        from dcc.houdini.client import HoudiniClient

        self.port, self.pid = int(port), pid
        self.client = client or HoudiniClient(port=self.port)

    def run(self, code: str, timeout: float = 600.0) -> Dict[str, Any]:
        return self.client.run(code, timeout=timeout)

    def state(self) -> Dict[str, Any]:
        return self.client.state()


_MAYA_WRAPPER = '''
import json as _json, traceback as _tb
_flux_ns = {"__name__": "__flux_flows__", "cmds": __import__("maya.cmds", fromlist=["cmds"])}
try:
    exec(compile(%(code)r, "<flux flow>", "exec"), _flux_ns)
    _flux_out = {"ok": True, "result": _flux_ns.get("result")}
except Exception as _exc:
    _flux_out = {"ok": False, "error": "%%s: %%s" %% (type(_exc).__name__, _exc), "trace": _tb.format_exc()}
try:
    _flux_text = _json.dumps(_flux_out)
except (TypeError, ValueError):
    _flux_text = _json.dumps({"ok": _flux_out["ok"], "result": repr(_flux_out.get("result")),
                              "error": _flux_out.get("error")})
with open(%(out)r, "w", encoding="utf-8") as _fh:
    _fh.write(_flux_text)
'''


def maya_wrapped(code: str, out_path: str) -> str:
    """One commandPort line that runs *code* in Maya and writes {ok, result | error} to *out_path*."""
    body = _MAYA_WRAPPER % {"code": str(code), "out": str(out_path).replace("\\", "/")}
    b64 = base64.b64encode(body.encode("utf-8")).decode("ascii")
    return f"import base64 as _b64; exec(_b64.b64decode('{b64}').decode('utf-8'))"


class MayaLiveSession(Session):
    soft = "maya"

    def __init__(self, port: int, *, pid: Optional[int] = None,
                 send: Optional[Callable[..., Optional[str]]] = None) -> None:
        self.port, self.pid = int(port), pid
        self._send = send

    def run(self, code: str, timeout: float = 600.0) -> Dict[str, Any]:
        send = self._send
        if send is None:
            from dcc.maya.maya_connection import send_command_direct as send
        tmp = tempfile.mkdtemp(prefix="flux_flows_maya_")
        out = os.path.join(tmp, "result.json")
        try:
            answer = send(maya_wrapped(code, out), timeout=float(timeout), port=self.port)
            if answer is None:
                return {"ok": False, "error": f"Maya :{self.port} ne repond pas (commandPort)"}
            try:
                return json.loads(Path(out).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {"ok": False, "error": f"Maya n'a rendu aucun resultat ({str(answer)[:200]})"}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TcpJsonSession(Session):
    """Bridges that run code with {"cmd": "run", "code"} (Nuke). P6b."""

    def __init__(self, soft: str, port: int, *, pid: Optional[int] = None) -> None:
        self.soft, self.port, self.pid = soft, int(port), pid

    def run(self, code: str, timeout: float = 600.0) -> Dict[str, Any]:
        return primitives.tcp_json_call(self.port, {"cmd": "run", "code": code}, timeout=timeout,
                                        raise_on_error=False)


def _painter_client(port: Optional[int]):
    from dcc.substance_painter.client import SubstancePainterClient

    return SubstancePainterClient(port=port)


# Softs whose bridge got the `run` action ("bridge+", P6b step 9, gated by the machine secret).
_RUN_CLIENTS = {"painter": _painter_client}


class ClientSession(Session):
    """Bridges driven through their client (Painter, Designer, Mari, ZBrush, Marvelous): the
    nodes call their client on this port; run() goes through the bridge's `run` action where
    it exists (_RUN_CLIENTS), else it is refused (a "bridge+" verb, not invented, A17)."""

    def __init__(self, soft: str, port: Optional[int], *, pid: Optional[int] = None) -> None:
        self.soft, self.port, self.pid = soft, int(port) if port else None, pid

    def run(self, code: str, timeout: float = 600.0) -> Dict[str, Any]:
        make = _RUN_CLIENTS.get(self.soft)
        if make is not None:
            resp = make(self.port).run(code, timeout)
            if isinstance(resp, dict) and not resp.get("ok") and not resp.get("error"):
                resp = {**resp, "error": resp.get("msg") or "le logiciel a refuse le code"}
            return resp
        return {"ok": False, "error": f"{softs.get(self.soft).label} n'execute pas de code (commande a ajouter "
                                      "au bridge, a etudier)"}


class MailboxSession(Session):
    """An extension bridge on a file mailbox (P6c template file_mailbox_server.py)."""

    def __init__(self, soft: str, mailbox: str, *, pid: Optional[int] = None) -> None:
        self.soft, self.mailbox, self.port, self.pid = soft, mailbox, None, pid

    def run(self, code: str, timeout: float = 600.0) -> Dict[str, Any]:
        from dcc.marvelous.client import mailbox_dir

        return primitives.file_mailbox_call({"cmd": "run", "code": code}, mailbox_dir=str(mailbox_dir(self.mailbox)),
                                            timeout=timeout, raise_on_error=False)


class HttpRunSession(Session):
    """An extension bridge on HTTP (POST /run {"code"}, the Houdini server's protocol)."""

    def __init__(self, soft: str, port: int, *, pid: Optional[int] = None) -> None:
        self.soft, self.port, self.pid = soft, int(port), pid

    def run(self, code: str, timeout: float = 600.0) -> Dict[str, Any]:
        return primitives.http_call(self.port, "/run", {"code": code}, timeout=timeout, raise_on_error=False)


_LIVE = {"houdini": HoudiniLiveSession, "maya": MayaLiveSession}


def live_session(soft: str, port: Optional[int], pid: Optional[int] = None) -> Session:
    spec = softs.get(soft)
    cls = _LIVE.get(spec.soft)
    if cls is not None:
        return cls(port, pid=pid)
    if spec.soft == "nuke" or (spec.extension and spec.transport == "tcp_json"):
        return TcpJsonSession(spec.soft, port, pid=pid)
    if spec.extension and spec.transport == "file_mailbox":
        return MailboxSession(spec.soft, spec.mailbox or f"flux_{spec.soft}_bridge", pid=pid)
    if spec.extension and spec.transport == "http":
        return HttpRunSession(spec.soft, port, pid=pid)
    return ClientSession(spec.soft, port, pid=pid)


def _same_path(a: str, b: str) -> bool:
    if not a or not b:
        return False
    norm = lambda p: os.path.normcase(os.path.normpath(str(p).replace("\\", "/")))  # noqa: E731
    return norm(a) == norm(b)


def scene_of(soft: str, port: int) -> str:
    try:
        from core.dcc_context import instance_context

        return str(instance_context(softs.get(soft).dcc_key, int(port)).get("scene") or "")
    except Exception:  # noqa: BLE001 - a label is best effort
        return ""


def find_instance(soft: str, *, pick: str = "active", scene: str = "", pid: Any = None,
                  instances: Optional[List[Dict[str, Any]]] = None,
                  scene_fn: Callable[[str, int], str] = scene_of) -> Optional[Dict[str, Any]]:
    """The running instance a flow targets, or None. ``active`` = the one chosen in FLUX
    (resolve_port), ``scene`` = the one whose open scene is *scene*, ``pid``."""
    spec = softs.get(soft)
    if spec.transport == "file_mailbox" and instances is None and not spec.extension:
        # One mailbox, one instance: alive when the bridge beats (Marvelous).
        got = primitives.ping(spec.soft)
        return {"port": None, "pid": got.get("pid")} if got.get("ok") else None
    found = instances if instances is not None else primitives.scan_ports(spec.soft)
    if not found:
        return None
    if pick == "pid":
        try:
            wanted = int(pid)
        except (TypeError, ValueError):
            raise BridgeError("pick pid : renseigne `pid`") from None
        return next((i for i in found if i.get("pid") == wanted), None)
    if pick == "scene":
        if not scene:
            raise BridgeError("pick scene : relie ou saisis `scene`")
        return next((i for i in found if _same_path(scene_fn(spec.soft, int(i["port"])), scene)), None)
    if spec.extension:          # no instance chosen in FLUX for an extension: the first one
        return found[0]
    from core.dcc_instances import InstanceLostError, resolve_port

    try:
        port = resolve_port(spec.dcc_key, instances=found)
    except InstanceLostError as exc:
        raise BridgeError(str(exc)) from None
    return next((i for i in found if int(i["port"]) == int(port)), found[0])


def connect_live(soft: str, *, mode: str = "live_connect_or_open", pick: str = "active", scene: str = "",
                 pid: Any = None, wait_s: float = DEFAULT_WAIT_S, cancelled: Optional[threading.Event] = None,
                 log: Callable[[str], None] = lambda text: None) -> Session:
    """The Instance node, live modes (decision 24): connect to the instance if it exists,
    else open the soft (with *scene*) and wait for its bridge."""
    spec = softs.get(soft)
    inst = find_instance(spec.soft, pick=pick, scene=scene, pid=pid)
    if inst is None:
        if mode == "live_connect_only":
            raise BridgeError(f"aucune instance {spec.label} ouverte" + (f" (pick {pick})" if pick != "active" else ""))
        if pick == "pid":
            raise BridgeError(f"aucun {spec.label} avec le pid {pid}")
        log(f"ouvre {spec.label}" + (f" avec {scene}" if scene else ""))
        if not primitives.launch(spec.soft, scene or None):
            raise BridgeError(f"{spec.label} : executable introuvable (Parametres > Logiciels)")
        ready = primitives.wait_ready(spec.soft, None, timeout=wait_s, cancelled=cancelled, any_port=True)
        inst = {"port": ready["port"] if spec.transport != "file_mailbox" else None, "pid": None}
    session = live_session(spec.soft, inst.get("port"), inst.get("pid"))
    got = primitives.ping(spec.soft, session.port)
    if not got.get("ok"):
        raise BridgeError(f"{spec.label} :{session.port} ne repond pas ({got.get('error') or 'bridge absent'})")
    session.version = got.get("version") or ""
    session.scene = scene_of(spec.soft, session.port) if session.port else ""
    log(f"connecte a {session.label}")
    return session
