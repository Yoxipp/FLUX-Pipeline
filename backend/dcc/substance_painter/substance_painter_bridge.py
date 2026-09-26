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


def _flatten_export_result(result) -> list[str]:
    """Best-effort: pull every written file path out of an export result."""
    files: list[str] = []
    textures = getattr(result, "textures", None)
    if isinstance(textures, dict):
        for paths in textures.values():
            for p in (paths or []):
                files.append(str(p))
    return files


def _complete_config(config: dict) -> dict:
    """Fill what only Painter knows: every texture set of the open project when the
    backend sent no exportList (Painter exports nothing without one), and a preset
    given by name turned into its starter-assets resource URL."""
    import substance_painter.resource as _res
    import substance_painter.textureset as _ts

    cfg = dict(config)
    # Only the maps ticked in FLUX (their fileName in the preset), on every set, plus the
    # shader channels added on top (inline FLUX preset).
    maps = cfg.pop("fluxOutputMaps", None)
    skip_preset = cfg.pop("fluxSkipPreset", False)
    extra = cfg.pop("fluxExtraMaps", None)
    inline = {str(p.get("name")) for p in cfg.get("exportPresets") or []}
    if not cfg.get("exportList"):
        entries = []
        for ts in _ts.all_texture_sets():
            if not skip_preset:
                entry = {"rootPath": ts.name()}
                if maps:
                    entry["filter"] = {"outputMaps": list(maps)}
                entries.append(entry)
            if extra and inline:
                entries.append({"rootPath": ts.name(), "exportPreset": sorted(inline)[0],
                                "filter": {"outputMaps": list(extra)}})
        cfg["exportList"] = entries

    def _url(name: str) -> str:
        if not name or "://" in name or name in inline:
            return name
        # A studio preset installed by FLUX sits in the user's assets, a shipped one in
        # Painter's starter assets.
        for ctx in ("your_assets", "starter_assets"):
            try:
                for p in _sp_export.list_resource_export_presets():
                    rid = p.resource_id
                    if getattr(rid, "name", "") == name and getattr(rid, "context", ctx) == ctx:
                        return rid.url()
            except Exception:  # noqa: BLE001
                break
        return _res.ResourceID(context="starter_assets", name=name).url()

    cfg["defaultExportPreset"] = _url(str(cfg.get("defaultExportPreset") or ""))
    for entry in cfg["exportList"]:
        if entry.get("exportPreset"):
            entry["exportPreset"] = _url(str(entry["exportPreset"]))
    return cfg


def _do_export(config: dict) -> dict:
    if not _SP_AVAILABLE:
        return {"status": "error", "msg": "substance_painter module not available"}
    try:
        import substance_painter.project as _project

        if not _project.is_open():
            return {"status": "error", "msg": "Aucun projet ouvert dans Painter"}
        cfg = _complete_config(config)
        if not cfg["exportList"]:
            return {"status": "error", "msg": "Le projet Painter n'a aucun texture set"}
        _diag(f"export: sets={[e['rootPath'] for e in cfg['exportList']]} preset={cfg.get('defaultExportPreset')}")
        result = _sp_export.export_project_textures(cfg)
        files = _flatten_export_result(result)
        status = str(getattr(result, "status", ""))
        if not files:
            msg = str(getattr(result, "message", "") or status or "aucune map ecrite")
            _diag(f"export produced no file: {msg}")
            return {"status": "error", "msg": f"Export Painter vide : {msg}"}
        _diag(f"export ok: {len(files)} file(s)")
        return {"status": "ok", "files": files}
    except Exception as exc:  # noqa: BLE001
        _diag(f"export failed: {exc!r}")
        return {"status": "error", "msg": str(exc)}


def _do_info() -> dict:
    """Texture sets of the open project (Publisher: choose what to export)."""
    if not _SP_AVAILABLE:
        return {"status": "error", "msg": "substance_painter module not available"}
    try:
        import substance_painter.project as _project
        import substance_painter.textureset as _ts

        if not _project.is_open():
            return {"status": "ok", "project": "", "texture_sets": []}
        sets = []
        for ts in _ts.all_texture_sets():
            item = {"name": ts.name()}
            try:
                item["udim"] = bool(ts.has_uv_tiles())
            except Exception:  # noqa: BLE001 - older API
                item["udim"] = False
            try:
                item["resolution"] = int(ts.get_resolution().width)
            except Exception:  # noqa: BLE001
                item["resolution"] = 0
            sets.append(item)
        name = ""
        try:
            name = os.path.basename(_project.file_path() or "")
        except Exception:  # noqa: BLE001
            pass
        return {"status": "ok", "project": name, "texture_sets": sets, "presets": _presets(),
                "channels": _channels(_ts)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "msg": str(exc)}


def _map_label(file_name: str) -> str:
    """"$textureSet_BaseColor(.$udim)" -> "BaseColor": the map part of an output name."""
    import re

    label = re.sub(r"\([^)]*\)", "", str(file_name))          # optional groups
    label = re.sub(r"\$[A-Za-z]+", "", label).strip("_.- ")
    return label or str(file_name)


def _channel_map_name(ctype) -> str:
    """Painter's export name of a channel type: BaseColor -> baseColor, IOR -> ior."""
    raw = getattr(ctype, "name", str(ctype)).split(".")[-1]
    if raw.isupper():
        return raw.lower()
    return raw[:1].lower() + raw[1:]


def _channels(_ts) -> list[dict]:
    """Every channel of every texture set's stack (2026-09-25: coat, anisotropy,
    user channels... were missing, the list only came from the export preset):
    [{"id": export map name, "label", "gray": one component}], deduplicated."""
    out: dict[str, dict] = {}
    for ts in _ts.all_texture_sets():
        try:
            stacks = ts.all_stacks() if hasattr(ts, "all_stacks") else [ts.get_stack()]
        except Exception:  # noqa: BLE001
            continue
        for stack in stacks:
            try:
                chans = stack.all_channels()
            except Exception:  # noqa: BLE001
                continue
            for ctype, ch in chans.items():
                cid = _channel_map_name(ctype)
                if cid in out:
                    continue
                label = ""
                try:
                    label = ch.label() if hasattr(ch, "label") else ""
                except Exception:  # noqa: BLE001
                    label = ""
                if not label:
                    import re as _re
                    label = _re.sub(r"(?<!^)(?=[A-Z])", " ", getattr(ctype, "name", cid)).strip()
                gray = False
                try:
                    gray = "L" in str(ch.format()).split(".")[-1] and "RGB" not in str(ch.format())
                except Exception:  # noqa: BLE001
                    gray = False
                out[cid] = {"id": cid, "label": str(label), "gray": bool(gray)}
    return sorted(out.values(), key=lambda c: c["label"].lower())


def _presets() -> list[dict]:
    """Export presets Painter really has (2026-09-25: "USD Preview Surface" was a
    guessed name Painter did not know), each with its output maps:
    [{"name", "url", "maps": [{"id": fileName, "label"}]}]."""
    out: list[dict] = []
    seen: set[str] = set()

    def _add(name, url, preset) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        maps = []
        try:
            for m in preset.list_output_maps() or []:
                fid = m.get("fileName") if isinstance(m, dict) else None
                if fid and all(x["id"] != fid for x in maps):
                    maps.append({"id": fid, "label": _map_label(fid)})
        except Exception:  # noqa: BLE001 - a preset without readable maps stays usable
            pass
        out.append({"name": str(name), "url": str(url or ""), "maps": maps})

    try:
        for p in _sp_export.list_resource_export_presets():
            rid = p.resource_id
            _add(getattr(rid, "name", ""), rid.url(), p)
    except Exception as exc:  # noqa: BLE001
        _diag(f"resource export presets unreadable: {exc!r}")
    try:
        for p in _sp_export.list_predefined_export_presets():
            _add(getattr(p, "name", ""), getattr(p, "url", ""), p)
    except Exception as exc:  # noqa: BLE001
        _diag(f"predefined export presets unreadable: {exc!r}")
    return sorted(out, key=lambda x: x["name"].lower())


def _dispatch(cmd: dict) -> dict:
    action = cmd.get("action", "")
    if action == "info":
        return _on_main_thread(_do_info, timeout=20.0)
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


def start_plugin() -> None:  # Painter entry point
    global _server_sock
    if _server_sock is not None:
        return
    try:
        sock = _listen(HOST, PORT)
        _server_sock = sock
        threading.Thread(target=_serve, args=(sock,), daemon=True).start()
        _start_main_thread_pump()
        _diag(f"Substance Painter bridge listening on {HOST}:{PORT} (api={_SP_AVAILABLE})")
    except OSError as exc:
        _diag(f"Substance Painter bridge bind failed on {HOST}:{PORT}: {exc} (port pris : un autre Painter ouvert ? netstat -ano | findstr {PORT})")


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
