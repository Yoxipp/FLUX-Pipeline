"""
FLUX Marvelous Designer bridge script (SKELETON — verify live).

Marvelous has no startup-plugin folder FLUX can rely on: autostart.py copies this
script to a fixed place and the artist runs it once per session from Marvelous
(Script > Python Script: open the file, Run). It starts a small local TCP server
(newline-JSON) so the FLUX backend can ping Marvelous and trigger an export through
the Marvelous Python API (export_api). Running it twice keeps the first server.

Protocol:
  {"action": "ping"}                    -> {"status": "ok", "version": "..."}
  {"action": "info"}                    -> {"status": "ok", "project": ..., "formats": [...]}
  {"action": "export", "config": {...}} -> {"status": "ok", "files": [...]}

config:
  {"exportPath": dir, "name": file stem, "format": "abc" | "obj" | "fbx" | "zprj" |
   "usd" | "glb", "options": {"garment": bool, "avatar": bool, "single_object": bool,
   "thick": bool, "unified_uv": bool, "scale": float}, "zprj": bool}

NOTE: export_api function names and ImportExportOption fields changed across
Marvelous versions; they are looked up defensively and must be verified live.
"""

from __future__ import annotations

import builtins
import json
import os
import socket
import threading

try:
    import export_api as _export_api
    _MD_AVAILABLE = True
except Exception:  # noqa: BLE001 - importable from the backend for a syntax check
    _export_api = None
    _MD_AVAILABLE = False

HOST = "127.0.0.1"
# Base of Marvelous' assigned range (DCC_PORT_RANGES["Marvelous"]); env override
# for multi-instance. Must match the backend client / status scan port.
PORT = int(os.environ.get("FLUX_MARVELOUS_PORT", "7050"))

# Survives a second Run of the script (Marvelous re-executes it in fresh globals).
_STATE_KEY = "_flux_marvelous_bridge"


# ── main-thread execution + diagnostic log (same as the Painter bridge) ──────
import queue as _queue
import tempfile as _tempfile
import time as _time

_LOG_PATH = os.path.join(_tempfile.gettempdir(), "flux_marvelous_bridge.log")


def _state() -> dict:
    st = getattr(builtins, _STATE_KEY, None)
    if st is None:
        st = {"sock": None, "timer": None, "jobs": _queue.Queue()}
        setattr(builtins, _STATE_KEY, st)
    return st


def _diag(msg: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(_time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass
    print("[FLUX] " + msg)


def _drain() -> None:
    jobs = _state()["jobs"]
    while True:
        try:
            fn, box, done = jobs.get_nowait()
        except _queue.Empty:
            return
        try:
            box["result"] = fn()
        except Exception as exc:  # noqa: BLE001 - reported to the backend
            box["result"] = {"status": "error", "msg": str(exc)}
        done.set()


def _start_main_thread_pump() -> None:
    st = _state()
    if st["timer"] is not None:
        return
    QtCore = None
    for mod in ("PySide6", "PySide2"):
        try:
            QtCore = __import__(mod + ".QtCore", fromlist=["QtCore"])
            break
        except Exception:  # noqa: BLE001
            continue
    if QtCore is None or QtCore.QCoreApplication.instance() is None:
        _diag("Qt not found: Marvelous calls run in the socket thread")
        return
    timer = QtCore.QTimer()
    timer.timeout.connect(_drain)
    timer.start(50)
    st["timer"] = timer


def _on_main_thread(fn, timeout: float = 900.0) -> dict:
    """Run fn() on the Marvelous main thread when a Qt loop exists, else inline."""
    st = _state()
    if st["timer"] is None:
        return fn()
    box: dict = {}
    done = threading.Event()
    st["jobs"].put((fn, box, done))
    if not done.wait(timeout):
        return {"status": "error", "msg": "Marvelous occupe : pas de reponse du thread principal"}
    return box["result"]


# ── Marvelous API helpers ─────────────────────────────────────────────────────

# Words that name each format in export_api function names (ExportAlembic, ExportOBJ...).
_FORMAT_WORDS = {
    "abc":  ("alembic", "abc"),
    "obj":  ("obj",),
    "fbx":  ("fbx",),
    "zprj": ("zprj",),
    "usd":  ("usd",),
    "glb":  ("glb", "gltf"),
}

# FLUX option -> ImportExportOption fields that may carry it (by Marvelous version).
_OPTION_FIELDS = {
    "garment":       ("bExportGarment",),
    "avatar":        ("bExportAvatar",),
    "single_object": ("bSingleObject",),
    "thick":         ("bThick", "bThickness"),
    "unified_uv":    ("bUnifiedUVCoordinates", "bUnifiedUV"),
    "scale":         ("scale",),
}


def _module(name: str):
    try:
        return __import__(name)
    except Exception:  # noqa: BLE001
        return None


def _export_functions(fmt: str) -> list:
    """export_api functions that write *fmt*, plain names first (ExportOBJ before ExportOBJW)."""
    if _export_api is None:
        return []
    words = _FORMAT_WORDS.get(fmt, (fmt,))
    names = [n for n in dir(_export_api)
             if n.lower().startswith("export") and any(w in n.lower() for w in words)]
    # "zprj" must not pick ExportZPac, "obj" must not pick a "...Object..." helper.
    names = [n for n in names if not (fmt == "obj" and "object" in n.lower())]
    names.sort(key=lambda n: (len(n), n))
    return [getattr(_export_api, n) for n in names if callable(getattr(_export_api, n))]


def _formats() -> list[str]:
    return [f for f in _FORMAT_WORDS if _export_functions(f)]


def _make_options(opts: dict):
    """An ImportExportOption filled with the FLUX options (only the fields this
    Marvelous knows). None when the type is not exposed."""
    api_types = _module("ApiTypes")
    cls = getattr(api_types, "ImportExportOption", None) if api_types else None
    if cls is None:
        return None
    o = cls()
    for key, fields in _OPTION_FIELDS.items():
        if key not in opts or opts[key] is None:
            continue
        for field in fields:
            if hasattr(o, field):
                try:
                    setattr(o, field, float(opts[key]) if key == "scale" else bool(opts[key]))
                except Exception:  # noqa: BLE001
                    pass
                break
    return o


def _call_export(fmt: str, path: str, opts: dict) -> list[str]:
    """Call the first export_api function of *fmt* that accepts our arguments."""
    fns = _export_functions(fmt)
    if not fns:
        raise RuntimeError(f"export {fmt} absent de cette version de Marvelous")
    option = _make_options(opts) if fmt != "zprj" else None
    attempts = []
    if option is not None:
        attempts.append((path, option))
    attempts.append((path,))
    if fmt == "zprj":
        attempts.insert(0, (path, False))  # ExportZPrj(path, bSaveThumbnail)
    last = None
    for fn in fns:
        for args in attempts:
            try:
                res = fn(*args)
            except TypeError as exc:     # wrong signature for this version: next one
                last = exc
                continue
            out = [str(p) for p in res] if isinstance(res, (list, tuple)) else []
            return out or [path]
    raise RuntimeError(f"export {fmt} refuse par Marvelous : {last}")


def _project() -> tuple[str, str]:
    """(project name, project file path) of the open Marvelous project, best effort."""
    util = _module("utility_api")
    name, path = "", ""
    for attr in ("GetProjectName",):
        fn = getattr(util, attr, None) if util else None
        if fn:
            try:
                name = str(fn() or "")
            except Exception:  # noqa: BLE001
                pass
    for attr in ("GetProjectFilePath", "GetProjectPath"):
        fn = getattr(util, attr, None) if util else None
        if fn:
            try:
                path = str(fn() or "")
                break
            except Exception:  # noqa: BLE001
                pass
    if not name and path:
        name = os.path.splitext(os.path.basename(path))[0]
    return name, path


def _count(module_name: str, attrs: tuple[str, ...]) -> int | None:
    mod = _module(module_name)
    for attr in attrs:
        fn = getattr(mod, attr, None) if mod else None
        if fn:
            try:
                return int(fn())
            except Exception:  # noqa: BLE001
                continue
    return None


def _version() -> str:
    util = _module("utility_api")
    for attr in ("GetMDVersion", "GetVersion", "GetMajorVersion"):
        fn = getattr(util, attr, None) if util else None
        if fn:
            try:
                return f"Marvelous Designer {fn()}"
            except Exception:  # noqa: BLE001
                continue
    return "Marvelous Designer"


# ── actions ──────────────────────────────────────────────────────────────────


def _do_info() -> dict:
    if not _MD_AVAILABLE:
        return {"status": "error", "msg": "export_api non disponible (script lance hors de Marvelous ?)"}
    name, path = _project()
    return {
        "status": "ok",
        "project": name,
        "path": path,
        "formats": _formats(),
        "patterns": _count("pattern_api", ("GetPatternCount",)),
        "avatars": _count("utility_api", ("GetAvatarCount",)),
    }


def _do_export(config: dict) -> dict:
    if not _MD_AVAILABLE:
        return {"status": "error", "msg": "export_api non disponible (script lance hors de Marvelous ?)"}
    out_dir = str(config.get("exportPath") or "")
    if not out_dir:
        return {"status": "error", "msg": "exportPath manquant"}
    os.makedirs(out_dir, exist_ok=True)
    stem = str(config.get("name") or "flux_export")
    fmt = str(config.get("format") or "abc").lstrip(".").lower()
    opts = dict(config.get("options") or {})
    files: list[str] = []
    warnings: list[str] = []
    todo = [fmt] + (["zprj"] if config.get("zprj") and fmt != "zprj" else [])
    for f in todo:
        path = os.path.join(out_dir, f"{stem}.{f}").replace("\\", "/")
        try:
            got = _call_export(f, path, opts)
            _diag(f"export {f}: {got}")
            files.extend(got)
        except Exception as exc:  # noqa: BLE001
            _diag(f"export {f} failed: {exc!r}")
            if f == fmt:
                return {"status": "error", "msg": str(exc)}
            warnings.append(f".{f} : {exc}")
    return {"status": "ok", "files": files, "warnings": warnings}


def _dispatch(cmd: dict) -> dict:
    action = cmd.get("action", "")
    if action == "ping":
        return {"status": "ok", "version": _version() if _MD_AVAILABLE else "Marvelous Designer"}
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


def _serve(sock: socket.socket) -> None:
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            break
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


def start_bridge() -> None:
    st = _state()
    if st["sock"] is not None:
        _diag(f"Marvelous bridge already listening on {HOST}:{PORT}")
        return
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
        sock.listen(5)
        st["sock"] = sock
        threading.Thread(target=_serve, args=(sock,), daemon=True).start()
        _start_main_thread_pump()
        _diag(f"Marvelous bridge listening on {HOST}:{PORT} (api={_MD_AVAILABLE})")
    except OSError as exc:
        _diag(f"Marvelous bridge bind failed on {HOST}:{PORT}: {exc}")


def stop_bridge() -> None:
    st = _state()
    if st["timer"] is not None:
        st["timer"].stop()
        st["timer"] = None
    if st["sock"] is not None:
        try:
            st["sock"].close()
        except OSError:
            pass
        st["sock"] = None


# Run from Marvelous' Python Script editor: start at once (the API only imports there,
# so importing this file from the backend starts nothing).
if _MD_AVAILABLE:
    start_bridge()
