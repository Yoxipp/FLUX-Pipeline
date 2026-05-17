"""
FLUX ZBrush Bridge Plugin — v1.2
=================================
Place this file in ZBrush's ZPlugs64 directory.
ZBrush auto-executes every .py in that folder at startup.

ZBrush 2024+ (Maxon): %APPDATA%\Maxon\Maxon ZBrush YYYY_HASH\ZStartup\ZPlugs64\
Classic path        : %USERPROFILE%\Documents\ZBrushData\ZStartup\ZPlugs64\
macOS               : ~/Library/Application Support/ZBrush/ZStartup/ZPlugs64/

The plugin starts a TCP server on 127.0.0.1:9876 that accepts JSON commands
from the FLUX desktop app and executes them using the zbrush.commands API.

Protocol (newline-framed JSON):
  Request  : {"action": "export_obj", "path": "C:/out/mesh.obj", "options": {...}}\n
  Response : {"status": "ok"}\n  or  {"status": "error", "msg": "..."}\n
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback

try:
    from zbrush import commands as zbc
    _ZBRUSH_AVAILABLE = True
    _ZBRUSH_IMPORT_ERR = None
except ImportError as _e:
    _ZBRUSH_AVAILABLE = False
    _ZBRUSH_IMPORT_ERR = repr(_e)

HOST = "127.0.0.1"
PORT = int(os.environ.get("FLUX_ZBRUSH_PORT", "9876"))

# ── Logging helper ────────────────────────────────────────────────────────────
# Writes to a file at %USERPROFILE%\flux_zbrush_bridge.log so the user can read
# the full output without relying on ZBrush's no-copy-paste Python console.

_LOG_FILE    = os.path.join(os.path.expanduser("~"), "flux_zbrush_bridge.log")
_BG_LOG_FILE = os.path.join(os.path.expanduser("~"), "flux_zbrush_bridge_bg.log")
_MAIN_THREAD = threading.current_thread()

# Raw file descriptor opened on the main thread, reused for write() syscalls
# from the background thread. open()/close() seem to block in ZBrush's
# embedded Python from non-main threads (file-lock contention with the host).
# A single os.write() syscall is the same kind of operation as socket I/O —
# which we've verified does work from background threads briefly.
try:
    _BG_LOG_FD: int | None = os.open(
        _BG_LOG_FILE,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
    )
except Exception:
    _BG_LOG_FD = None


def _log(msg: str) -> None:
    is_main = threading.current_thread() is _MAIN_THREAD
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    if not is_main:
        if _BG_LOG_FD is not None:
            try:
                os.write(_BG_LOG_FD, line.encode("utf-8"))
            except Exception:
                pass
        return
    try:
        print(line.rstrip("\n"), flush=True)
    except Exception:
        pass
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as _f:
            _f.write(line)
    except Exception:
        pass

# Reset log at every module load so we see a fresh trace
try:
    with open(_LOG_FILE, "w", encoding="utf-8") as _f:
        _f.write("")
except Exception:
    pass

_log(f"=== PLUGIN FILE LOAD ===")
_log(f"__name__={__name__!r}  __file__={globals().get('__file__', '<not set>')!r}")
_log(f"_ZBRUSH_AVAILABLE={_ZBRUSH_AVAILABLE}  import_err={_ZBRUSH_IMPORT_ERR}")
_log(f"HOST={HOST}  PORT={PORT}")
_log(f"sys.executable={sys.executable!r}")
_log(f"sys.version={sys.version!r}")
_log(f"current thread={threading.current_thread().name}  pid={os.getpid()}")


# ── OBJ export helpers ────────────────────────────────────────────────────────

def _apply_obj_options(options: dict) -> None:
    if "uvs" in options:
        try:
            zbc.set_slider("Tool:Export:Mrg", 1 if options["uvs"] else 0)
        except Exception:
            pass
    if "flip_v" in options:
        try:
            zbc.set_slider("Tool:Export:Flp", 1 if options["flip_v"] else 0)
        except Exception:
            pass
    if "groups" in options:
        try:
            zbc.set_slider("Tool:Export:Grp", 1 if options["groups"] else 0)
        except Exception:
            pass
    if "materials" in options:
        try:
            zbc.set_slider("Tool:Export:Mat", 1 if options["materials"] else 0)
        except Exception:
            pass


# ── FBX export helpers ────────────────────────────────────────────────────────

_FBX_VERSION_MAP = {"2019": 1, "2020": 2, "2022": 3}

def _apply_fbx_options(options: dict) -> None:
    if "fbx_version" in options:
        ver_idx = _FBX_VERSION_MAP.get(str(options["fbx_version"]), 1)
        try:
            zbc.set_slider("FBXExportImport:FBXVersion", ver_idx)
        except Exception:
            pass
    if "animation" in options:
        try:
            zbc.set_slider("FBXExportImport:AnimExportGrp:ExportAnim",
                           1 if options["animation"] else 0)
        except Exception:
            pass
    if "materials" in options:
        try:
            zbc.set_slider("FBXExportImport:MatExportGrp:ExportMat",
                           1 if options["materials"] else 0)
        except Exception:
            pass


# ── Command dispatcher ────────────────────────────────────────────────────────

def _dispatch(cmd: dict) -> dict:
    action = cmd.get("action", "")

    if action == "ping":
        # No zbc.* call — ping must NEVER block on ZBrush's main thread.
        return {"status": "ok", "version": "ZBrush 2026"}

    if not _ZBRUSH_AVAILABLE:
        return {"status": "error", "msg": "zbrush module not available"}

    elif action == "get_mesh_info":
        try:
            points = int(zbc.query_mesh3d(0)[0])
            polys  = int(zbc.query_mesh3d(1)[0])
            tool   = zbc.get_active_tool_path()
            return {"status": "ok", "data": {"points": points, "polys": polys, "tool": tool}}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    elif action == "export_ztl":
        path = cmd.get("path", "")
        if not path:
            return {"status": "error", "msg": "Missing path"}
        try:
            zbc.set_next_filename(path)
            zbc.press("Tool:Save")
            return {"status": "ok", "path": path}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    elif action == "export_obj":
        path    = cmd.get("path", "")
        options = cmd.get("options", {})
        if not path:
            return {"status": "error", "msg": "Missing path"}
        try:
            _apply_obj_options(options)
            zbc.set_next_filename(path)
            zbc.press("Tool:Export")
            return {"status": "ok", "path": path}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    elif action == "export_fbx":
        path    = cmd.get("path", "")
        options = cmd.get("options", {})
        if not path:
            return {"status": "error", "msg": "Missing path"}
        try:
            _apply_fbx_options(options)
            zbc.set_next_filename(path)
            zbc.press("FBXExportImport:Export")
            return {"status": "ok", "path": path}
        except Exception as exc:
            return {"status": "error", "msg": str(exc)}

    return {"status": "error", "msg": f"Unknown action: {action}"}


# ── Bridge class ─────────────────────────────────────────────────────────────

class _FluxBridge:
    def __init__(self) -> None:
        self._running  = False
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        _log(f"start() called  current _running={self._running}")
        if self._running:
            _log("start() returning early (already running)")
            return

        # CRITICAL: bind/listen on the MAIN thread during plugin init.
        # ZBrush's embedded Python seems to freeze background threads after
        # plugin init completes — so setting up the socket inside a thread
        # gets stuck mid-call. Doing it on the main thread (which is ZBrush's
        # actual main thread, kept alive forever) guarantees the port is
        # LISTENING before init returns.
        try:
            _log("[main] step 1: socket.socket()")
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _log(f"[main] step 2: socket created fileno={self._sock.fileno()}")
            _log(f"[main] step 3: about to bind({HOST!r}, {PORT})")
            self._sock.bind((HOST, PORT))
            _log("[main] step 4: bind OK, about to listen(5)")
            self._sock.listen(5)
            _log("[main] step 5: listen OK, settimeout(1.0)")
            self._sock.settimeout(1.0)
            _log(f"[main] step 6: Listening on {HOST}:{PORT}  fileno={self._sock.fileno()}")
        except Exception as exc:
            _log(f"!!! BIND/LISTEN FAILED on main thread: {exc!r}")
            _log(traceback.format_exc())
            self._running = False
            if self._sock is not None:
                try: self._sock.close()
                except OSError: pass
            return

        self._running = True
        # daemon=True: non-daemon threads observed to freeze in ZBrush's
        # embedded Python after plugin init completes.
        self._thread = threading.Thread(target=self._server_loop, daemon=True,
                                        name="flux-zbrush-bridge")
        _log(f"thread created daemon={self._thread.daemon}, calling thread.start()")
        try:
            self._thread.start()
        except Exception as exc:
            _log(f"!!! thread.start() failed: {exc!r}")
            _log(traceback.format_exc())
            self._running = False
            return
        _log(f"Server started on {HOST}:{PORT}  thread.is_alive()={self._thread.is_alive()}")

    def _handle_one(self, conn: socket.socket) -> None:
        """Receive one newline-framed JSON command, dispatch, send response.
        SO_LINGER {1, 0} forces RST on close so the connection dies immediately
        with no FIN handshake → no CLOSE_WAIT zombies."""
        import struct as _struct
        try:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                            _struct.pack("ii", 1, 0))
        except OSError:
            pass
        conn.settimeout(3.0)
        buf = b""
        try:
            while b"\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    return   # probe-only connection (backend just connected then closed)
                buf += chunk
            line     = buf.split(b"\n")[0]
            cmd      = json.loads(line.decode("utf-8"))
            response = _dispatch(cmd)
            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            try:
                conn.sendall((json.dumps({"status": "error", "msg": str(exc)}) + "\n").encode("utf-8"))
            except OSError:
                pass
        except OSError:
            pass
        finally:
            conn.close()   # SO_LINGER {1,0} above triggers immediate RST

    def _server_loop(self) -> None:
        # Socket already bound + listening (done on main thread in start()).
        # This thread only runs the accept loop.
        _log(f"_server_loop ENTERED (thread={threading.current_thread().name})")
        _log(f"socket fileno={self._sock.fileno() if self._sock else 'None'}")
        _log("Entering accept loop")
        _conn_count = 0
        while self._running:
            try:
                conn, addr = self._sock.accept()
                _conn_count += 1
                _log(f"accept #{_conn_count} from {addr}")
            except socket.timeout:
                continue
            except OSError as exc:
                if self._running:
                    _log(f"Socket error — server stopping: {exc!r}")
                break
            except Exception as exc:
                _log(f"Unexpected error in accept loop: {exc!r}")
                _log(traceback.format_exc())
                break
            self._handle_one(conn)
            _log(f"handled #{_conn_count} OK")

        _log("Server loop exited.")

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass


# ── Module-level singleton ────────────────────────────────────────────────────
# ZBrush loads this file via BOTH mechanisms (PYTHONPATH+init.py AND
# ZPlugs64/*.py) and may also reload it via the Python console. The singleton
# guard prevents double-binding port 9876 (which causes Windows to refuse all
# incoming connections even though the port shows LISTENING in netstat).

def _get_or_start_bridge() -> "_FluxBridge":
    _log("_get_or_start_bridge() entered")
    existing = getattr(sys, "_flux_zbrush_bridge_ref", None)
    _log(f"existing bridge ref = {existing!r}")
    if existing is not None:
        alive = (getattr(existing, "_running", False)
                 and existing._thread is not None
                 and existing._thread.is_alive())
        _log(f"existing alive check = {alive}")
        if alive:
            _log(f"Already running on {HOST}:{PORT} — skipping duplicate load")
            return existing
        _log("existing bridge is dead — cleaning up old socket")
        existing._running = False
        if existing._sock is not None:
            try:
                existing._sock.close()
            except OSError as exc:
                _log(f"old socket close failed: {exc!r}")
    _log("creating new _FluxBridge instance")
    b = _FluxBridge()
    sys._flux_zbrush_bridge_ref = b
    _log("calling b.start()")
    b.start()
    _log("_get_or_start_bridge() returning")
    return b


try:
    _bridge = _get_or_start_bridge()
    _log("=== PLUGIN INIT COMPLETE ===")
except Exception as _e:
    _log(f"!!! PLUGIN INIT FAILED: {_e!r}")
    _log(traceback.format_exc())
    raise
