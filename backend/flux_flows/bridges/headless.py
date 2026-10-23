# headless.py — persistent hython / mayapy workers (02_NODES §8, A12). P6a.
#
# The Houdini server cannot run under hython (its /run goes through hou.ui) and
# _run_offline starts one process per script: the scene would be lost between two
# nodes. A headless Instance therefore starts ONE worker for the run:
#   * WORKER_SOURCE (below, stdlib only, Python 3.10 = Maya 2024) is written to a temp
#     file and started with hython / mayapy, environment cleaned like a launched soft
#     (launcher_core._child_env: no PYTHONPATH, so FLUX's usd-core never reaches
#     Houdini's Python; NOTES.md §6). No file is added to the FLUX bundle.
#   * protocol: one JSON line per request on stdin {"id", "code"} -> one JSON line on
#     the worker's real stdout {"id", "ok", "result" | "error"}; the code's prints go
#     to stderr (kept in a log). First line = {"ready": true, "version", "scene"}.
#   * same contract as the live bridges: run(code, timeout) -> {"ok", "result" | "error"}.
#   * closed at the end of the run (Run.add_cleanup): "quit", then terminate, then kill.
# A licence is taken for the whole life of the worker (W_LICENCE). A request over its
# timeout kills the worker (Python cannot stop a running statement): the session is
# then dead and says so.

from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from flux_flows.bridges import softs
from flux_flows.bridges.primitives import BridgeError
from flux_flows.bridges.session import Session

READY_TIMEOUT_S = 180.0

WORKER_SOURCE = r'''# flux_worker.py — FLUX Flows headless worker (written by flux_flows/bridges/headless.py).
import json, os, sys, traceback

_OUT = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr          # prints of the flow code never break the protocol


def _send(data):
    try:
        text = json.dumps(data)
    except (TypeError, ValueError):
        data = {k: (v if k != "result" else repr(v)) for k, v in data.items()}
        text = json.dumps(data)
    _OUT.write(text + "\n")
    _OUT.flush()


def _boot(soft, scene):
    ns = {"__name__": "__flux_flows__"}
    if soft == "houdini":
        import hou
        ns["hou"] = hou
        if scene:
            hou.hipFile.load(scene, suppress_save_prompt=True, ignore_load_warnings=True)
        return ns, hou.applicationVersionString(), hou.hipFile.path()
    if soft == "maya":
        import maya.standalone
        maya.standalone.initialize(name="python")
        import maya.cmds as cmds
        ns["cmds"] = cmds
        if scene:
            cmds.file(scene, open=True, force=True)
        return ns, cmds.about(version=True), cmds.file(q=True, sceneName=True) or ""
    raise RuntimeError("logiciel headless inconnu: %s" % soft)


def main():
    soft, scene = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
    try:
        ns, version, current = _boot(soft, scene)
    except Exception as exc:
        _send({"ready": False, "error": "%s: %s" % (type(exc).__name__, exc), "trace": traceback.format_exc()})
        return 1
    _send({"ready": True, "version": str(version), "scene": str(current), "pid": os.getpid()})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        if req.get("cmd") == "quit":
            break
        ns.pop("result", None)
        try:
            exec(compile(req.get("code") or "", "<flux flow>", "exec"), ns)
            _send({"id": req.get("id"), "ok": True, "result": ns.get("result")})
        except Exception as exc:
            _send({"id": req.get("id"), "ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                   "trace": traceback.format_exc()})
    if soft == "maya":
        try:
            import maya.standalone
            maya.standalone.uninitialize()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def worker_script() -> Path:
    """WORKER_SOURCE written once per content in the temp folder."""
    digest = hashlib.sha1(WORKER_SOURCE.encode("utf-8")).hexdigest()[:10]
    path = Path(tempfile.gettempdir()) / f"flux_flows_worker_{digest}.py"
    if not path.is_file():
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(WORKER_SOURCE, encoding="utf-8")
        os.replace(tmp, path)
    return path


def find_hython() -> Optional[Path]:
    from features.folder_manager.houdini_scene_template import _find_hython

    return _find_hython()


def find_mayapy() -> Optional[Path]:
    """mayapy next to maya(.exe): the configured / detected Maya first, then the install globs."""
    name = "mayapy.exe" if platform.system() == "Windows" else "mayapy"
    candidates = []
    try:
        from features.launcher.launcher_core import _resolve_exe

        exe = _resolve_exe("maya")
        if exe:
            candidates.append(Path(exe).parent / name)
    except Exception:  # noqa: BLE001 - no config yet
        pass
    from core.constants import DCC_EXE_PATTERNS

    for pattern in DCC_EXE_PATTERNS.get("Maya", []):
        for exe in sorted(glob.glob(pattern), reverse=True):
            candidates.append(Path(exe).parent / name)
    return next((c for c in candidates if c.is_file()), None)


def find_exe(soft: str) -> Optional[Path]:
    kind = softs.get(soft).headless
    if kind == "hython":
        return find_hython()
    if kind == "mayapy":
        return find_mayapy()
    return None


def _child_env() -> Dict[str, str]:
    from features.launcher.launcher_core import _child_env as child_env

    return child_env()


class WorkerSession(Session):
    """One hython / mayapy process for one run."""

    mode = "headless"

    def __init__(self, soft: str, command: list, *, env: Optional[Dict[str, str]] = None,
                 ready_timeout: float = READY_TIMEOUT_S, cancelled: Optional[threading.Event] = None) -> None:
        self.soft = softs.get(soft).soft
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self._lock = threading.Lock()
        self._ids = 0
        self.dead: Optional[str] = None
        self.log_path = Path(tempfile.mkstemp(prefix=f"flux_flows_{self.soft}_", suffix=".log")[1])
        self._log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        try:
            self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                                         env=env, text=True, encoding="utf-8", bufsize=1)
        except OSError as exc:
            self._log.close()
            raise BridgeError(f"worker {self.soft} non lance : {exc}") from None
        self.pid = self.proc.pid
        threading.Thread(target=self._reader, daemon=True, name=f"flux-worker-{self.pid}").start()
        ready = self._next(ready_timeout, cancelled)
        if ready is None or not ready.get("ready"):
            why = (ready or {}).get("error") or self.dead or "pas de reponse"
            self.close()
            raise BridgeError(f"worker {softs.get(soft).label} : {why} (journal : {self.log_path})")
        self.version = str(ready.get("version") or "")
        self.scene = str(ready.get("scene") or "")

    def _reader(self) -> None:
        try:
            for line in self.proc.stdout:
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        self._lines.put(None)

    def _next(self, timeout: float, cancelled: Optional[threading.Event] = None) -> Optional[Dict[str, Any]]:
        end = time.monotonic() + timeout
        while True:
            if cancelled is not None and cancelled.is_set():
                self._kill("annule")
                return None
            left = end - time.monotonic()
            if left <= 0:
                return None
            try:
                line = self._lines.get(timeout=min(left, 0.5))
            except queue.Empty:
                continue
            if line is None:
                self.dead = self.dead or f"le worker s'est arrete (code {self.proc.poll()})"
                return None
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict):
                return data

    def run(self, code: str, timeout: float = 600.0) -> Dict[str, Any]:
        with self._lock:
            if self.dead:
                return {"ok": False, "error": f"session headless morte : {self.dead}"}
            self._ids += 1
            rid = self._ids
            try:
                self.proc.stdin.write(json.dumps({"id": rid, "code": str(code)}) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self.dead = str(exc)
                return {"ok": False, "error": f"session headless morte : {exc}"}
            while True:
                data = self._next(float(timeout))
                if data is None:
                    if not self.dead:
                        self._kill(f"timeout ({timeout:g} s)")
                    return {"ok": False, "error": f"session headless : {self.dead}"}
                if data.get("id") == rid:
                    return data

    def _kill(self, why: str) -> None:
        self.dead = self.dead or why
        if self.proc.poll() is None:
            self.proc.kill()

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        self.dead = self.dead or "fermee"
        try:
            self._log.close()
        except OSError:
            pass


def start_worker(soft: str, scene: str = "", *, cancelled: Optional[threading.Event] = None,
                 exe_fn: Callable[[str], Optional[Path]] = find_exe,
                 ready_timeout: float = READY_TIMEOUT_S) -> WorkerSession:
    """A headless session of *soft* (hython / mayapy), optionally on *scene*."""
    spec = softs.get(soft)
    if not spec.headless:
        raise BridgeError(f"{spec.label} n'a pas de mode headless")
    exe = exe_fn(spec.soft)
    if exe is None:
        raise BridgeError(f"{spec.headless} introuvable (installe {spec.label} ou regle son chemin)")
    command = [str(exe), str(worker_script()), spec.soft] + ([str(scene)] if scene else [])
    return WorkerSession(spec.soft, command, env=_child_env(), ready_timeout=ready_timeout, cancelled=cancelled)
