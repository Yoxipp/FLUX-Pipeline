"""
FLUX Substance Painter bridge plugin (V6 B2, SKELETON — finish/verify live).

Placed in Painter's python/startup dir (installed by autostart.py): Painter starts
every startup module and calls start_plugin() at launch (a python/plugins module only
runs once ticked in the Python menu, the cause of "bridge ne repond pas"). This starts a small local
TCP server (newline-JSON) so the FLUX backend can ping Painter and trigger an
export via the substance_painter API.

Protocol:
  {"action": "ping"}                       -> {"status": "ok", "version": "..."}
  {"action": "export", "config": {...}}    -> {"status": "ok", "files": [...]}

NOTE: export_project_textures' result shape is version-specific; the flattening
below is defensive and must be verified against the installed Painter version.
"""

from __future__ import annotations

import json
import os
import socket
import threading

try:
    import substance_painter.export as _sp_export
    import substance_painter as _sp
    _SP_AVAILABLE = True
except Exception:  # noqa: BLE001 - importable from the backend for a syntax check
    _sp_export = None
    _sp = None
    _SP_AVAILABLE = False

HOST = "127.0.0.1"
# Base of Painter's assigned range (DCC_PORT_RANGES["SubstanceP"]); env override
# for multi-instance. Must match the backend client / status scan port.
PORT = int(os.environ.get("FLUX_SUBSTANCE_PORT", "7030"))

_server_sock: "socket.socket | None" = None


# ── main-thread execution + diagnostic log (2026-09-24) ──────────────────────
# The DCC API is not thread-safe: socket threads hand the work to the Qt main
# thread through a queue polled by a QTimer (created at startup, on the main
# thread). Without Qt the work runs inline. Every step is appended to
# %TEMP%/flux_painter_bridge.log so "bridge ne repond pas" can be diagnosed without the DCC console.
import queue as _queue
import tempfile as _tempfile
import time as _time

_LOG_PATH = os.path.join(_tempfile.gettempdir(), "flux_painter_bridge.log")
_jobs: "_queue.Queue" = _queue.Queue()
_timer = None


def _diag(msg: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(_time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass
    print("[FLUX] " + msg)


def _drain() -> None:
    while True:
        try:
            fn, box, done = _jobs.get_nowait()
        except _queue.Empty:
            return
        try:
            box["result"] = fn()
        except Exception as exc:  # noqa: BLE001 - reported to the backend
            box["result"] = {"status": "error", "msg": str(exc)}
        done.set()


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
        return {"status": "error", "msg": "DCC busy: no answer from the main thread"}
    return box["result"]


def _flatten_export_result(result) -> list[str]:
    """Best-effort: pull every written file path out of an export result."""
    files: list[str] = []
    textures = getattr(result, "textures", None)
    if isinstance(textures, dict):
        for paths in textures.values():
            for p in (paths or []):
                files.append(str(p))
    return files


def _do_export(config: dict) -> dict:
    if not _SP_AVAILABLE:
        return {"status": "error", "msg": "substance_painter module not available"}
    try:
        result = _sp_export.export_project_textures(config)
        return {"status": "ok", "files": _flatten_export_result(result)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "msg": str(exc)}


def _dispatch(cmd: dict) -> dict:
    action = cmd.get("action", "")
    if action == "ping":
        ver = getattr(_sp, "__version__", "") if _sp else ""
        return {"status": "ok", "version": f"Substance Painter {ver}".strip()}
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


def start_plugin() -> None:  # Painter entry point
    global _server_sock
    if _server_sock is not None:
        return
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
        sock.listen(5)
        _server_sock = sock
        threading.Thread(target=_serve, args=(sock,), daemon=True).start()
        _start_main_thread_pump()
        _diag(f"Substance Painter bridge listening on {HOST}:{PORT} (api={_SP_AVAILABLE})")
    except OSError as exc:
        _diag(f"Substance Painter bridge bind failed on {HOST}:{PORT}: {exc}")


def close_plugin() -> None:  # Painter entry point
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
    start_plugin()
