"""
FLUX Substance 3D Designer bridge plugin (SKELETON — verify live).

Installed by autostart.py as a plugin package in Designer's user plugin dir
(python/sduserplugins/flux_designer_bridge/__init__.py): Designer loads every
package of that dir at launch and calls initializeSDPlugin(). This starts a small
local TCP server (newline-JSON) so the FLUX backend can ping Designer, list the
graphs of the open packages and export them through the `sd` API.

Protocol:
  {"action": "ping"}                   -> {"status": "ok", "version": "..."}
  {"action": "info"}                   -> {"status": "ok", "packages": [...], "current": ...}
  {"action": "export", "config": {...}} -> {"status": "ok", "files": [...]}
  Flows verbs (P6b step 9, 2026-10-24, sd.api per the Adobe docs, TO VALIDATE LIVE):
  {"action": "open", "path": ".sbs"}                 -> {"status": "ok", "project"} (one more package)
  {"action": "save"} / {"action": "save_as", "path": ".sbs"} -> the current graph's package
  {"action": "import", "kind": "bitmap"|"mesh", "path"} -> linked into the current package
  {"action": "run", "code", "secret"}  -> {"ok": true, "result", "trace"} (machine secret)

config:
  {"exportPath": dir, "graphs": [{"package": file path, "graph": identifier,
   "outputs": [identifier, ...] | null}], "fileFormat": "png", "size": 2048 | null,
   "bitDepth": "8" | "16" | "16f" | "32f" | null, "maps": bool, "sbsar": bool, "sbs": bool}

Maps are written as <exportPath>/<graph>/<graph>_<output>.<ext>, the .sbsar as
<exportPath>/<package>.sbsar, the source as <exportPath>/<package>.sbs.

NOTE: the SBSAR exporter class and the $format values are version-specific; the
calls below are defensive and must be verified against the installed Designer.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading

try:
    import sd as _sd
    _SD_AVAILABLE = True
except Exception:  # noqa: BLE001 - importable from the backend for a syntax check
    _sd = None
    _SD_AVAILABLE = False

HOST = "127.0.0.1"
# Base of Designer's assigned range (DCC_PORT_RANGES["SubstanceD"]); env override
# for multi-instance. Must match the backend client / status scan port.
PORT = int(os.environ.get("FLUX_DESIGNER_PORT", "7040"))

_server_sock: "socket.socket | None" = None


# ── main-thread execution + diagnostic log (same as the Painter bridge) ──────
# The sd API is not thread-safe: socket threads hand the work to the Qt main thread
# through a queue polled by a QTimer (created at startup, on the main thread).
# Every step is appended to %TEMP%/flux_designer_bridge.log.
import queue as _queue
import tempfile as _tempfile
import time as _time

_LOG_PATH = os.path.join(_tempfile.gettempdir(), "flux_designer_bridge.log")
_jobs: "_queue.Queue" = _queue.Queue()
_timer = None


def _diag(msg: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(_time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass
    print("[FLUX] " + msg)


_draining = False


def _drain() -> None:
    # The app pumps Qt events while it exports, so this timer fires again in the
    # middle of a job: never start another API call inside one (Mari crashed that
    # way, 2026-09-26). A job whose caller gave up waiting is skipped.
    global _draining
    if _draining:
        return
    _draining = True
    try:
        while True:
            try:
                fn, box, done = _jobs.get_nowait()
            except _queue.Empty:
                return
            if box.get("abandoned"):
                done.set()
                continue
            name = getattr(fn, "__name__", "job")
            _diag(f"main thread: {name} start")
            try:
                box["result"] = fn()
            except Exception as exc:  # noqa: BLE001 - reported to the backend
                box["result"] = {"status": "error", "msg": str(exc)}
            _diag(f"main thread: {name} done")
            done.set()
    finally:
        _draining = False


def _start_main_thread_pump() -> None:
    global _timer
    if _timer is not None:
        return
    QtCore = None
    for mod in ("PySide6", "PySide2"):
        try:
            QtCore = __import__(mod + ".QtCore", fromlist=["QtCore"])
            break
        except Exception:  # noqa: BLE001
            continue
    if QtCore is None:
        _diag("Qt not found: DCC calls run in the socket thread")
        return
    _timer = QtCore.QTimer()
    _timer.timeout.connect(_drain)
    _timer.start(50)


def _on_main_thread(fn, timeout: float = 600.0) -> dict:
    """Run fn() on the DCC main thread and return its result."""
    if _timer is None:
        return fn()
    box: dict = {}
    done = threading.Event()
    _jobs.put((fn, box, done))
    if not done.wait(timeout):
        box["abandoned"] = True
        return {"status": "error", "msg": "DCC busy: no answer from the main thread"}
    return box["result"]


# ── sd helpers ────────────────────────────────────────────────────────────────


def _app():
    return _sd.getContext().getSDApplication()


def _iter(sd_array) -> list:
    """An SDArray (or a plain list) as a Python list."""
    if sd_array is None:
        return []
    try:
        return list(sd_array)
    except TypeError:
        return [sd_array.getItem(i) for i in range(sd_array.getSize())]


def _value(v):
    """The Python value of an SDValue (None stays None)."""
    try:
        return v.get() if v is not None else None
    except Exception:  # noqa: BLE001
        return None


def _is_comp_graph(res) -> bool:
    try:
        from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
        return isinstance(res, SDSBSCompGraph)
    except Exception:  # noqa: BLE001 - older API: judge by class name
        return type(res).__name__ == "SDSBSCompGraph"


def _user_packages() -> list:
    return _iter(_app().getPackageMgr().getUserPackages())


def _package_graphs(pkg) -> list:
    try:
        resources = _iter(pkg.getChildrenResources(True))
    except Exception:  # noqa: BLE001
        resources = []
    return [r for r in resources if _is_comp_graph(r)]


def _output_id(node) -> str:
    for key in ("identifier", "label"):
        try:
            val = _value(node.getAnnotationPropertyValueFromId(key))
            if val:
                return str(val)
        except Exception:  # noqa: BLE001
            continue
    return str(node.getIdentifier())


def _output_label(node) -> str:
    try:
        val = _value(node.getAnnotationPropertyValueFromId("label"))
        if val:
            return str(val)
    except Exception:  # noqa: BLE001
        pass
    return _output_id(node)


def _graph_outputs(graph) -> list[dict]:
    out = []
    for node in _iter(graph.getOutputNodes()):
        out.append({"id": _output_id(node), "label": _output_label(node)})
    return out


def _current_graph():
    try:
        return _app().getQtForPythonUIMgr().getCurrentGraph()
    except Exception:  # noqa: BLE001
        return None


# ── actions ──────────────────────────────────────────────────────────────────


def _do_info() -> dict:
    """Open packages, their graphs and each graph's outputs (Publisher options)."""
    if not _SD_AVAILABLE:
        return {"status": "error", "msg": "sd module not available"}
    current = _current_graph()
    cur_id = ""
    try:
        cur_id = current.getIdentifier() if current is not None else ""
    except Exception:  # noqa: BLE001
        cur_id = ""
    packages = []
    for pkg in _user_packages():
        path = str(pkg.getFilePath() or "")
        graphs = []
        for g in _package_graphs(pkg):
            gid = str(g.getIdentifier())
            graphs.append({"id": gid, "outputs": _graph_outputs(g),
                           "current": current is not None and gid == cur_id})
        if graphs:
            packages.append({"path": path, "name": os.path.splitext(os.path.basename(path))[0] or "Untitled",
                             "graphs": graphs})
    return {"status": "ok", "packages": packages, "current": cur_id}


def _find_graph(package_path: str, graph_id: str):
    for pkg in _user_packages():
        if package_path and os.path.normcase(str(pkg.getFilePath() or "")) != os.path.normcase(package_path):
            continue
        for g in _package_graphs(pkg):
            if str(g.getIdentifier()) == graph_id:
                return pkg, g
    return None, None


# Designer graph output format ($format): 8 bits, 16 bits, 16 bits float, 32 bits float.
_FORMAT_VALUES = {"8": 0, "16": 1, "16f": 2, "32f": 3}


def _set_graph_param(graph, pid: str, value) -> object:
    """Set a graph input parameter; returns the previous SDValue (None if unreadable)."""
    try:
        prev = graph.getInputPropertyValueFromId(pid)
    except Exception:  # noqa: BLE001
        prev = None
    graph.setInputPropertyValueFromId(pid, value)
    return prev


def _export_graph_maps(graph, out_dir: str, ext: str, outputs: list | None,
                       size: int | None, bit_depth: str | None) -> list[str]:
    """Compute *graph* and save each output node's texture; graph params restored after."""
    from sd.api.sdproperty import SDPropertyCategory

    restore: list[tuple[str, object]] = []
    try:
        if size:
            from sd.api.sdbasetypes import int2
            from sd.api.sdvalueint2 import SDValueInt2
            log2 = max(0, int(size).bit_length() - 1)
            restore.append(("$outputsize", _set_graph_param(graph, "$outputsize", SDValueInt2.sNew(int2(log2, log2)))))
        if bit_depth in _FORMAT_VALUES:
            from sd.api.sdvalueint import SDValueInt
            restore.append(("$format", _set_graph_param(graph, "$format", SDValueInt.sNew(_FORMAT_VALUES[bit_depth]))))
    except Exception as exc:  # noqa: BLE001 - a graph without the param still exports
        _diag(f"graph params not set on {graph.getIdentifier()}: {exc!r}")

    files: list[str] = []
    try:
        graph.compute()
        gid = str(graph.getIdentifier())
        os.makedirs(out_dir, exist_ok=True)
        wanted = set(outputs) if outputs is not None else None   # [] = no map of this graph
        for node in _iter(graph.getOutputNodes()):
            oid = _output_id(node)
            if wanted is not None and oid not in wanted:
                continue
            # Same walk as sd.tools.export.exportSDGraphOutputs.
            try:
                props = node.getDefinition().getProperties(SDPropertyCategory.Output)
            except Exception:  # noqa: BLE001
                props = node.getProperties(SDPropertyCategory.Output)
            for prop in _iter(props):
                tex = _value(node.getPropertyValue(prop))
                if tex is None or not hasattr(tex, "save"):
                    continue
                path = os.path.join(out_dir, f"{gid}_{oid}.{ext}")
                tex.save(path)
                files.append(path)
                break
    finally:
        for pid, prev in reversed(restore):
            if prev is not None:
                try:
                    graph.setInputPropertyValueFromId(pid, prev)
                except Exception:  # noqa: BLE001
                    pass
    return files


def _sbscooker() -> str | None:
    """sbscooker next to the Designer executable (fallback .sbsar export)."""
    exe = "sbscooker.exe" if os.name == "nt" else "sbscooker"
    start = os.path.dirname(sys.executable)
    for d in (start, os.path.dirname(start), os.path.join(os.path.dirname(start), "bin")):
        cand = os.path.join(d, exe)
        if os.path.isfile(cand):
            return cand
    return shutil.which(exe)


def _export_sbsar(pkg, dest: str) -> str:
    """Cook the package to *dest* (.sbsar): the sd exporter, else sbscooker on the saved file."""
    try:
        from sd.api.sbs.sdsbsarexporter import SDSBSARExporter
        exporter = SDSBSARExporter.sNew()
        for meth in ("exportPackageToSBSAR", "exportSDPackageToSBSAR"):
            fn = getattr(exporter, meth, None)
            if fn is not None:
                fn(pkg, dest)
                if os.path.isfile(dest):
                    return dest
    except Exception as exc:  # noqa: BLE001 - fall back to sbscooker
        _diag(f"SDSBSARExporter failed: {exc!r}")
    src = str(pkg.getFilePath() or "")
    cooker = _sbscooker()
    if not src or not os.path.isfile(src):
        raise RuntimeError("package jamais sauve : sauve le .sbs avant d'exporter le .sbsar")
    if cooker is None:
        raise RuntimeError("export .sbsar impossible (ni SDSBSARExporter ni sbscooker)")
    out_dir = os.path.dirname(dest)
    subprocess.run([cooker, "--inputs", src, "--output-path", out_dir,
                    "--output-name", os.path.splitext(os.path.basename(dest))[0]],
                   check=True, capture_output=True, timeout=600)
    if not os.path.isfile(dest):
        raise RuntimeError("sbscooker n'a rien ecrit")
    return dest


def _do_export(config: dict) -> dict:
    if not _SD_AVAILABLE:
        return {"status": "error", "msg": "sd module not available"}
    out_root = str(config.get("exportPath") or "")
    if not out_root:
        return {"status": "error", "msg": "exportPath manquant"}
    ext = str(config.get("fileFormat") or "png").lstrip(".")
    want_maps = bool(config.get("maps", True))
    files: list[str] = []
    done_pkgs: set[str] = set()
    errors: list[str] = []
    targets = config.get("graphs") or []
    if not targets:
        cur = _current_graph()
        if cur is None:
            return {"status": "error", "msg": "Aucun graph ouvert dans Designer"}
        pkg = cur.getPackage() if hasattr(cur, "getPackage") else None
        targets = [{"package": str(pkg.getFilePath() or "") if pkg else "", "graph": str(cur.getIdentifier())}]
    for t in targets:
        pkg, graph = _find_graph(str(t.get("package") or ""), str(t.get("graph") or ""))
        if graph is None:
            errors.append(f"graph introuvable : {t.get('graph')}")
            continue
        gid = str(graph.getIdentifier())
        if want_maps:
            try:
                got = _export_graph_maps(graph, os.path.join(out_root, gid), ext, t.get("outputs"),
                                         config.get("size"), config.get("bitDepth"))
                _diag(f"export {gid}: {len(got)} map(s)")
                files.extend(got)
            except Exception as exc:  # noqa: BLE001
                _diag(f"export {gid} failed: {exc!r}")
                errors.append(f"{gid} : {exc}")
        pkg_path = str(pkg.getFilePath() or "")
        if pkg_path in done_pkgs:
            continue
        done_pkgs.add(pkg_path)
        name = os.path.splitext(os.path.basename(pkg_path))[0] or gid
        if config.get("sbsar"):
            try:
                files.append(_export_sbsar(pkg, os.path.join(out_root, f"{name}.sbsar")))
            except Exception as exc:  # noqa: BLE001
                errors.append(f".sbsar {name} : {exc}")
        if config.get("sbs"):
            if pkg_path and os.path.isfile(pkg_path):
                dest = os.path.join(out_root, f"{name}.sbs")
                shutil.copyfile(pkg_path, dest)
                files.append(dest)
            else:
                errors.append(f".sbs {name} : package jamais sauve")
    if not files:
        return {"status": "error", "msg": "Export Designer vide" + (f" : {'; '.join(errors)}" if errors else "")}
    return {"status": "ok", "files": files, "warnings": errors}


_VERSION = ""


def _version() -> str:
    """Read once at startup on the main thread: the ping runs on a socket thread and
    must never call the sd API (Designer is not thread-safe)."""
    return _VERSION or "Substance Designer"


def _read_version() -> str:
    try:
        return f"Substance Designer {_app().getVersion()}"
    except Exception:  # noqa: BLE001
        return "Substance Designer"




# ── Flows verbs (P6b step 9) ─────────────────────────────────────────────────

def _secret() -> str:
    """The machine secret: <script>.json written next to this script at install, else
    %APPDATA%/FluxPipeline/bridge_secret.txt (a bridge started by exec() has no __file__)."""
    try:
        with open(os.path.splitext(os.path.abspath(__file__))[0] + ".json", encoding="utf-8") as fh:
            value = str(json.load(fh).get("secret") or "")
            if value:
                return value
    except (OSError, ValueError, NameError):
        pass
    appdata = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    try:
        with open(os.path.join(appdata, "FluxPipeline", "bridge_secret.txt"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _run_code(cmd: dict, namespace: dict, soft: str) -> dict:
    """`run`: free Python in the soft, refused without the machine secret."""
    import hmac
    import traceback

    expected = _secret()
    if not expected or not hmac.compare_digest(str(cmd.get("secret") or ""), expected):
        return {"ok": False, "status": "error",
                "error": "secret du bridge refuse : reinstalle le bridge %s depuis FLUX" % soft}
    code = str(cmd.get("code") or "")

    def job():
        ns = dict(namespace, __name__="__flux_flow__")
        try:
            exec(compile(code, "<flux flow>", "exec"), ns)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "error", "error": str(exc), "trace": traceback.format_exc()}
        result = ns.get("result")
        try:
            json.dumps(result)
        except (TypeError, ValueError):
            result = repr(result)
        return {"ok": True, "status": "ok", "result": result, "trace": ""}

    return _on_main_thread(job, timeout=float(cmd.get("timeout") or 600.0))


def _verb(fn, timeout: float = 600.0) -> dict:
    """fn() on the main thread, errors as {"status": "error"}."""
    def job():
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            _diag("verb failed: %r" % (exc,))
            return {"status": "error", "msg": str(exc)}

    return _on_main_thread(job, timeout=timeout)


def _pkg_mgr():
    return _app().getPackageMgr()


def _current_package():
    graph = _current_graph()
    if graph is not None:
        try:
            return graph.getPackage()
        except Exception:  # noqa: BLE001
            pass
    pkgs = _user_packages()
    return pkgs[0] if len(pkgs) == 1 else None


def _pkg_path(pkg) -> str:
    try:
        return str(pkg.getFilePath() or "")
    except Exception:  # noqa: BLE001
        return ""


def _do_open(cmd: dict) -> dict:
    """Designer holds several packages: open = load one more .sbs (nothing is replaced)."""
    path = str(cmd.get("path") or "")
    if not path.lower().endswith(".sbs"):
        return {"status": "error", "msg": "open : un package .sbs attendu"}
    if not os.path.isfile(path):
        return {"status": "error", "msg": "fichier introuvable : %s" % path}

    def fn():
        mgr = _pkg_mgr()
        pkg = None
        find = getattr(mgr, "getUserPackageFromFilePath", None)
        if find is not None:
            pkg = find(path)
        if pkg is None:
            pkg = mgr.loadUserPackage(path)
        return {"status": "ok", "project": _pkg_path(pkg) or path}

    return _verb(fn)


def _do_save(cmd: dict) -> dict:
    def fn():
        pkg = _current_package()
        if pkg is None:
            return {"status": "error", "msg": "aucun package courant (ouvre un graphe du package a enregistrer)"}
        if not _pkg_path(pkg):
            return {"status": "error", "msg": "package jamais enregistre : utilise sdSaveAs"}
        _pkg_mgr().savePackage(pkg)
        return {"status": "ok", "project": _pkg_path(pkg)}

    return _verb(fn)


def _do_save_as(cmd: dict) -> dict:
    """The current package saved as a new .sbs, which becomes its file (no copy mode)."""
    path = str(cmd.get("path") or "")
    if not path.lower().endswith(".sbs"):
        return {"status": "error", "msg": "save_as : un package .sbs attendu"}

    def fn():
        pkg = _current_package()
        if pkg is None:
            return {"status": "error", "msg": "aucun package courant (ouvre un graphe du package a enregistrer)"}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        _pkg_mgr().savePackageAs(pkg, path)
        return {"status": "ok", "project": path}

    return _verb(fn)


def _do_import(cmd: dict) -> dict:
    """A bitmap or a mesh linked into the current package (Resources)."""
    kind, path = str(cmd.get("kind") or "bitmap"), str(cmd.get("path") or "")
    if not os.path.isfile(path):
        return {"status": "error", "msg": "fichier introuvable : %s" % path}
    if kind not in ("bitmap", "mesh"):
        return {"status": "error", "msg": "import : kind inconnu %s (bitmap, mesh)" % kind}

    def fn():
        from sd.api.sdresource import EmbedMethod

        pkg = _current_package()
        if pkg is None:
            return {"status": "error", "msg": "aucun package courant (ouvre un graphe du package cible)"}
        if kind == "bitmap":
            from sd.api.sdresourcebitmap import SDResourceBitmap as _Res
        else:
            from sd.api.sdresourcescene import SDResourceScene as _Res
        _Res.sNewFromFile(pkg, path, EmbedMethod.Linked)
        return {"status": "ok"}

    return _verb(fn)


_VERBS = {"open": _do_open, "save": _do_save, "save_as": _do_save_as, "import": _do_import,
          "run": lambda cmd: _run_code(cmd, {"sd": _sd, "app": _app()}, "Designer")}


def _dispatch(cmd: dict) -> dict:
    action = cmd.get("action", "")
    if action in _VERBS:
        if not _SD_AVAILABLE:
            return {"status": "error", "msg": "sd module not available"}
        return _VERBS[action](cmd)
    if action == "ping":
        return {"status": "ok", "version": _version()}
    if action == "info":
        return _on_main_thread(_do_info, timeout=20.0)
    if action == "export":
        config = cmd.get("config", {})
        return _on_main_thread(lambda: _do_export(config))
    return {"status": "error", "msg": f"unknown action: {action}"}


def _handle(conn: socket.socket) -> None:
    try:
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
        cmd = json.loads(buf.split(b"\n")[0].decode("utf-8"))
        resp = _dispatch(cmd)
        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _listen(host: str, port: int) -> socket.socket:
    """Listening socket that owns its port alone. On Windows SO_REUSEADDR lets a second
    app (another copy, a stale bridge) bind the SAME port without error and steal part
    of the connections ("ne repond pas" at random): exclusive use there instead."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen(5)
    except OSError:
        sock.close()
        raise
    return sock


def _serve(sock: socket.socket) -> None:
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            break
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


def initializeSDPlugin() -> None:  # noqa: N802 - Designer entry point
    global _server_sock, _VERSION
    if _server_sock is not None:
        return
    if _SD_AVAILABLE:
        _VERSION = _read_version()
    try:
        sock = _listen(HOST, PORT)
        _server_sock = sock
        threading.Thread(target=_serve, args=(sock,), daemon=True).start()
        _start_main_thread_pump()
        _diag(f"Substance Designer bridge listening on {HOST}:{PORT} (api={_SD_AVAILABLE})")
    except OSError as exc:
        _diag(f"Substance Designer bridge bind failed on {HOST}:{PORT}: {exc} (port pris : un autre Designer ouvert ? netstat -ano | findstr {PORT})")


def uninitializeSDPlugin() -> None:  # noqa: N802 - Designer entry point
    global _server_sock, _timer
    if _timer is not None:
        _timer.stop()
        _timer = None
    if _server_sock is not None:
        try:
            _server_sock.close()
        except OSError:
            pass
        _server_sock = None


if __name__ == "__main__":
    initializeSDPlugin()
