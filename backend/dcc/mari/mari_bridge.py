"""
FLUX Mari bridge plugin (V6 B7, verify live).

Runs inside Mari (the `mari` module). Starts a local TCP server (newline-JSON) so
the FLUX backend can ping Mari and trigger a channel export.

Protocol:
  {"action": "ping"}                                    -> {"status": "ok", "version": "..."}
  {"action": "export", "export_path": "...", "file_format": "tif"} -> {"status": "ok", "files": [...]}

NOTE: Mari's export API is version-specific; the export below (current geo channels
-> exportImages) is defensive and must be verified against the installed Mari.
"""

from __future__ import annotations

import json
import os
import socket
import threading

try:
    import mari
    _MARI_AVAILABLE = True
except Exception:  # noqa: BLE001 - importable from the backend for a syntax check
    mari = None
    _MARI_AVAILABLE = False

HOST = "127.0.0.1"
# Base of Mari's assigned range (DCC_PORT_RANGES["Mari"]); env override for
# multi-instance. Must match the backend client / status scan port.
PORT = int(os.environ.get("FLUX_MARI_PORT", "7070"))

_server_sock: "socket.socket | None" = None


# ── main-thread execution + diagnostic log (2026-09-24) ──────────────────────
# The DCC API is not thread-safe: socket threads hand the work to the Qt main
# thread through a queue polled by a QTimer (created at startup, on the main
# thread). Without Qt the work runs inline. Every step is appended to
# %TEMP%/flux_mari_bridge.log so "bridge ne repond pas" can be diagnosed without the DCC console.
import queue as _queue
import tempfile as _tempfile
import time as _time

_LOG_PATH = os.path.join(_tempfile.gettempdir(), "flux_mari_bridge.log")
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


def _channel_ids(channels) -> list:
    """[(id, channel)]: a geo can hold two channels of one name (2026-09-26: two
    "Ambient Occlusion"); the second one is "Ambient Occlusion (2)", in the Publisher
    list and in its file name, so they never overwrite each other."""
    seen: dict = {}
    out = []
    for ch in channels:
        name = ch.name()
        seen[name] = seen.get(name, 0) + 1
        out.append((name if seen[name] == 1 else f"{name} ({seen[name]})", ch))
    return out


def _do_info() -> dict:
    """Channels of the current geo (Publisher: choose what to export)."""
    if not _MARI_AVAILABLE:
        return {"status": "error", "msg": "mari module not available"}
    try:
        geo = mari.geo.current()
        if geo is None:
            return {"status": "ok", "geo": "", "channels": []}
        chans = []
        for cid, channel in _channel_ids(geo.channelList()):
            item = {"name": cid, "depth": _depth(channel)}
            try:
                item["size"] = int(channel.width())
            except Exception:  # noqa: BLE001 - optional detail
                item["size"] = 0
            chans.append(item)
        return {"status": "ok", "geo": geo.name(), "channels": chans}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "msg": str(exc)}


def _depth(channel) -> int:
    """Bit depth of a channel: 8 (byte), 16 (half) or 32 (float)."""
    try:
        return int(channel.depth())
    except Exception:  # noqa: BLE001
        return 8


def _container(channel, file_format: str) -> str:
    """"auto": a lossless file that holds the channel's depth (FLUX converts it after to
    the format / depth / size picked for the map): tif for 8 bits, exr for float."""
    if file_format != "auto":
        return file_format
    return "tif" if _depth(channel) <= 8 else "exr"


def _do_export(export_path: str, file_format: str, channels: list | None = None) -> dict:
    if not _MARI_AVAILABLE:
        return {"status": "error", "msg": "mari module not available"}
    try:
        import glob

        geo = mari.geo.current()
        if geo is None:
            return {"status": "error", "msg": "Aucune geo courante dans Mari"}
        files: list[str] = []
        errors: list[str] = []
        os.makedirs(export_path, exist_ok=True)
        wanted = set(channels or [])
        for name, channel in _channel_ids(geo.channelList()):
            if wanted and name not in wanted:
                continue
            # One file per channel named after the channel only (FLUX turns the name into
            # the MAP token); Mari fills $UDIM with each tile number.
            fmt = _container(channel, file_format)
            out = os.path.join(export_path, f"{name}.$UDIM.{fmt}")
            t0 = _time.time()
            try:
                # Flattened: every layer of the channel merged, as it shows in Mari.
                if hasattr(channel, "exportImagesFlattened"):
                    channel.exportImagesFlattened(out)
                else:
                    channel.exportImages(out)
            except Exception as exc:  # noqa: BLE001 - one bad channel never aborts all
                errors.append(f"{name} : {exc}")
                _diag(f"Mari channel export failed ({name}): {exc!r}")
                continue
            _diag(f"Mari channel {name}: {_time.time() - t0:.1f} s ({fmt}, {_depth(channel)} bits)")
            # What really reached the disk (a refused format may write nothing).
            written = sorted(glob.glob(os.path.join(glob.escape(export_path), f"{glob.escape(name)}.*.{fmt}")))
            literal = [w for w in written if "$UDIM" in w]
            if literal:
                errors.append(f"{name} : Mari n'a pas remplace $UDIM (une seule tuile ecrite)")
            if written:
                files.extend(written)
                try:
                    patches = len(geo.patchList())
                    tiles = len(written) - len(literal)
                    if not literal and tiles < patches:
                        errors.append(f"{name} : {tiles} tuile(s) ecrite(s) pour {patches} patch(s)")
                except Exception:  # noqa: BLE001 - informative only
                    pass
            else:
                errors.append(f"{name} : aucun fichier ecrit en .{fmt}")
        _diag(f"Mari export: {len(files)} file(s), errors={errors}")
        if not files:
            hint = " (un channel 16 / 32 bits flottant ne passe pas en .png / .jpg / .tga : essaie .exr ou .tif)" \
                if file_format.lower() in ("png", "jpg", "jpeg", "tga") else ""
            return {"status": "error", "msg": "Mari n'a ecrit aucun fichier : " + " ; ".join(errors[:4]) + hint}
        return {"status": "ok", "files": files, "errors": errors}
    except Exception as exc:  # noqa: BLE001
        _diag(f"Mari export failed: {exc!r}")
        return {"status": "error", "msg": str(exc)}


def _dispatch(cmd: dict) -> dict:
    action = cmd.get("action", "")
    if action == "ping":
        # No Mari API call here: this runs on a socket thread (the version is read once,
        # on the main thread, when the bridge starts).
        return {"status": "ok", "version": f"Mari {_VERSION}".strip()}
    if action == "info":
        return _on_main_thread(_do_info, timeout=20.0)
    if action == "export":
        path, fmt = cmd.get("export_path", ""), cmd.get("file_format", "tif")
        chans = cmd.get("channels") or None
        # A big UDIM export takes long: never answer "busy" while Mari is still writing.
        return _on_main_thread(lambda: _do_export(path, fmt, chans), timeout=4 * 3600.0)
    return {"status": "error", "msg": f"unknown action: {action}"}


def _handle(conn: socket.socket) -> None:
    try:
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
        resp = _dispatch(json.loads(buf.split(b"\n")[0].decode("utf-8")))
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


_VERSION = ""


def _read_version() -> str:
    try:
        ver = mari.app.version()
        # mari.app.version() is an AppVersion object: show "7.1v2", not its repr.
        return ver.string() if hasattr(ver, "string") else str(ver)
    except Exception:  # noqa: BLE001
        return ""


def start() -> None:
    global _server_sock, _VERSION
    if _server_sock is not None:
        return
    # FLUX installs the bridge in every folder Mari may read: when Mari runs two
    # copies, the second one must not try to bind the port again.
    import builtins
    if getattr(builtins, "_flux_mari_bridge_started", False):
        _diag(f"Mari bridge already running, copy ignored ({globals().get('__file__', '?')})")
        return
    # Mari may exec() the script without __file__.
    here = globals().get("__file__", "?")
    _diag(f"Mari bridge loaded by Mari ({here})")
    if _MARI_AVAILABLE:
        _VERSION = _read_version()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
        sock.listen(5)
        _server_sock = sock
        builtins._flux_mari_bridge_started = True
        threading.Thread(target=_serve, args=(sock,), daemon=True).start()
        _start_main_thread_pump()
        _diag(f"Mari bridge listening on {HOST}:{PORT} (api={_MARI_AVAILABLE}, file={here})")
    except OSError as exc:
        _diag(f"Mari bridge bind failed on {HOST}:{PORT}: {exc}")


# Mari imports every script of its Scripts folders at startup: start the server on
# import inside Mari, not only when run as __main__ (it never is there).
if __name__ == "__main__" or _MARI_AVAILABLE:
    start()
