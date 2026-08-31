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
import select
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
    scope = options.get("scope", "selected")
    if scope == "all":
        try:
            zbc.press("Tool:Export:All")
        except Exception:
            pass
    elif scope == "visible":
        try:
            zbc.press("Tool:Export:Visible")
        except Exception:
            pass
    # "selected" is ZBrush's default — no button press needed


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
    scope = options.get("scope", "all")
    _FBX_SCOPE_BUTTONS = {
        "all":      "FBXExportImport:ExportGrp:AllMeshes",
        "selected": "FBXExportImport:ExportGrp:SelMesh",
        "visible":  "FBXExportImport:ExportGrp:VisMeshes",
    }
    btn = _FBX_SCOPE_BUTTONS.get(scope)
    if btn:
        try:
            zbc.press(btn)
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


# ── Server socket singleton ───────────────────────────────────────────────────
# Bound once on the main thread at plugin init. Reused across ZBrush sessions
# without rebinding (prevents WSAEADDRINUSE / CLOSE_WAIT accumulation).

_server_sock: "socket.socket | None" = None
FREEZE_TIMEOUT = int(os.environ.get("FLUX_ZBRUSH_TIMEOUT", "300"))  # 5 min default


def _init_server_socket() -> bool:
    """Bind and listen on the main thread. Reuse existing socket if alive."""
    global _server_sock
    existing: "socket.socket | None" = getattr(sys, "_flux_zbrush_sock", None)
    if existing is not None:
        try:
            existing.fileno()  # raises OSError if socket is closed
            _server_sock = existing
            _log(f"Reusing existing socket fileno={existing.fileno()}")
            return True
        except OSError:
            _log("Existing socket dead — recreating")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((HOST, PORT))
        sock.listen(32)
        sock.setblocking(False)  # required for select.select(timeout=0)
        sys._flux_zbrush_sock = sock
        _server_sock = sock
        _log(f"Socket bound and listening on {HOST}:{PORT}")
        return True
    except OSError as exc:
        _log(f"Bind failed: {exc!r}")
        return False


# ── Connection handler ────────────────────────────────────────────────────────

def _recv_and_dispatch(conn: socket.socket) -> bool:
    """Read one JSON command, dispatch it, send response.

    Returns True if the action was 'stop' (caller should break the freeze loop).
    SO_LINGER {1,0} forces RST on close to avoid CLOSE_WAIT zombies.

    Struct layout differs per OS:
      Windows : u_short l_onoff + u_short l_linger = 4 bytes → "HH"
      Linux   : int     l_onoff + int     l_linger = 8 bytes → "ii"
    """
    import struct as _struct
    _linger = _struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0)
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _linger)
    except OSError as _le:
        _log(f"SO_LINGER failed: {_le!r}")
    conn.settimeout(3.0)
    buf = b""
    try:
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return False  # probe-only connection (connected then immediately closed)
            buf += chunk
        cmd = json.loads(buf.split(b"\n")[0].decode("utf-8"))
        if cmd.get("action") in ("stop", "cancel"):
            conn.sendall(b'{"status":"ok"}\n')
            conn.close()
            return True
        resp = _dispatch(cmd)
        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        try:
            conn.sendall((json.dumps({"status": "error", "msg": str(exc)}) + "\n").encode("utf-8"))
        except OSError:
            pass
    except OSError:
        pass
    finally:
        conn.close()
    return False


# ── Freeze loop (T3) ──────────────────────────────────────────────────────────

def _listen_loop() -> None:
    """Runs on ZBrush main thread inside zbc.freeze().

    Uses select.select(timeout=0) — non-blocking poll — so ZBrush's event loop
    stays responsive between iterations. Exits on 'stop' command or global timeout.
    """
    _log("Freeze loop started")
    deadline = time.time() + FREEZE_TIMEOUT
    while time.time() < deadline:
        try:
            ready, _, _ = select.select([_server_sock], [], [], 0)
            if ready:
                conn, addr = _server_sock.accept()
                _log(f"Connection from {addr}")
                if _recv_and_dispatch(conn):
                    _log("Stop received — exiting freeze loop")
                    break
        except Exception as exc:
            _log(f"Freeze loop error: {exc!r}")
            _log(traceback.format_exc())
        time.sleep(0.05)
    _log("Freeze loop exited")


# ── ZBrush UI (T2) ───────────────────────────────────────────────────────────

_in_freeze = False


def _focus_flux_window() -> None:
    """Bring the FLUX Electron window to the foreground (Windows only).

    Matches windows with "FLUX" in the title, then filters by process name so that
    VSCode (which shows the repo folder "Flux_Pipeline_dev" in its title) is excluded.
    Prefers windows owned by electron.exe or any process name containing "flux".
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import ctypes.wintypes as _wt
        _u32 = ctypes.windll.user32
        _k32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        candidates: list[tuple[int, int, str, str]] = []  # (score, hwnd, title, proc_path)

        @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def _enum(hwnd: int, _: int) -> bool:
            if not _u32.IsWindowVisible(hwnd):
                return True
            title_buf = ctypes.create_unicode_buffer(512)
            _u32.GetWindowTextW(hwnd, title_buf, 512)
            title = title_buf.value
            if not title or "FLUX" not in title.upper():
                return True
            # Get owner process path to distinguish Electron from Code.exe
            pid = _wt.DWORD(0)
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc_path = ""
            hproc = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if hproc:
                pbuf  = ctypes.create_unicode_buffer(1024)
                psize = _wt.DWORD(1024)
                _k32.QueryFullProcessImageNameW(hproc, 0, pbuf, ctypes.byref(psize))
                _k32.CloseHandle(hproc)
                proc_path = pbuf.value
            proc_upper = proc_path.upper()
            # Skip known non-targets (editors whose titles show the repo folder name)
            if any(x in proc_upper for x in ("CODE.EXE", "DEVENV.EXE", "RIDER64.EXE")):
                return True
            score = 10 if ("ELECTRON" in proc_upper or "FLUX" in proc_upper) else 0
            candidates.append((score, hwnd, title, proc_path))
            return True

        _u32.EnumWindows(_enum, 0)
        if candidates:
            candidates.sort(reverse=True)
            _, hwnd, title, proc_path = candidates[0]
            _u32.ShowWindow(hwnd, 9)        # SW_RESTORE
            _u32.SetForegroundWindow(hwnd)
            _log(f"FLUX window focused hwnd={hwnd} title={title!r} proc={proc_path!r}")
        else:
            _log("FLUX window not found — is FLUX running?")
    except Exception as exc:
        _log(f"_focus_flux_window error: {exc!r}")


def _focus_zbrush_window() -> None:
    """Bring ZBrush's own main window to the foreground (Windows only).
    Runs inside ZBrush's process so we locate the window by matching our own PID."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import ctypes.wintypes as _wt
        _u32 = ctypes.windll.user32

        cur_pid = os.getpid()
        found: "list[int]" = []  # [hwnd] — mutable container avoids nonlocal in callback

        @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def _enum(hwnd: int, _: int) -> bool:
            if not _u32.IsWindowVisible(hwnd):
                return True
            pid = _wt.DWORD(0)
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != cur_pid:
                return True
            buf = ctypes.create_unicode_buffer(512)
            _u32.GetWindowTextW(hwnd, buf, 512)
            if buf.value:
                found.append(hwnd)
            return True

        _u32.EnumWindows(_enum, 0)
        if found:
            hwnd = found[0]
            _u32.ShowWindow(hwnd, 9)   # SW_RESTORE
            _u32.SetForegroundWindow(hwnd)
            _log(f"ZBrush window refocused hwnd={hwnd}")
        else:
            _log("ZBrush main window not found")
    except Exception as exc:
        _log(f"_focus_zbrush_window error: {exc!r}")


def _on_publish_click(*args: object, **kwargs: object) -> None:
    """Callback for the 'Publish to FLUX' button in ZPlugin:FLUX.
    *args/**kwargs accepted — ZBrush may pass positional arguments to button callbacks."""
    global _in_freeze
    # Direct write bypasses _log() threading guard — confirms callback fires
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as _f:
            _f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] _on_publish_click ENTERED args={args!r}\n")
    except Exception:
        pass
    if _in_freeze:
        if _ZBRUSH_AVAILABLE:
            zbc.show_note("Publication en cours, FLUX est en train de publier.")
        return
    if _server_sock is None:
        if _ZBRUSH_AVAILABLE:
            zbc.show_note("Erreur : bridge FLUX non initialisé.\nRedémarre ZBrush.")
        return
    _in_freeze = True
    _focus_flux_window()
    _log("Entering zbc.freeze()")
    try:
        zbc.freeze(_listen_loop)
    finally:
        _in_freeze = False
        _log("zbc.freeze() returned — ZBrush UI restored")
        _focus_zbrush_window()


def _register_zbrush_ui() -> None:
    """Register 'Publish to FLUX' button in ZPlugin:FLUX Bridge (2026.1+ API)."""
    if not _ZBRUSH_AVAILABLE:
        _log("ZBrush module not available — skipping UI registration")
        return
    try:
        ok1 = zbc.add_subpalette("ZPlugin:FLUX Bridge", title_mode=0)
        _log(f"add_subpalette → {ok1}")
        ok2 = zbc.add_button(
            "ZPlugin:FLUX Bridge:Publish to FLUX",
            "Publier le tool actif via FLUX Pipeline",
            _on_publish_click,
        )
        _log(f"add_button → {ok2}")
    except Exception as exc:
        _log(f"UI registration failed (non-critical): {exc!r}")


# ── Module-level init ─────────────────────────────────────────────────────────
# This block runs once at plugin load (ZBrush main thread).
# Singleton guards prevent double-bind if the plugin is reloaded.

try:
    if _init_server_socket():
        _register_zbrush_ui()
        _log("=== PLUGIN INIT COMPLETE ===")
    else:
        _log("=== SOCKET INIT FAILED — plugin disabled ===")
except Exception as _e:
    _log(f"!!! PLUGIN INIT FAILED: {_e!r}")
    _log(traceback.format_exc())
    raise
