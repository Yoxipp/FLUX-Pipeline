# unreal_bridge.py — FLUX bridge running INSIDE the Unreal editor (ADR 0052).
#
# Copied by dcc/unreal/autostart.py into the FluxBridge content plugin of the FLUX host
# project (Plugins/FluxBridge/Content/Python/). init_unreal.py of that folder imports it
# at editor startup. Stdlib + `unreal` (+ Unreal's own `pxr` when present) only.
#
# Protocol shared with the other bridges (dcc/json_bridge.py): one JSON object per line
# over a local TCP socket, one request per connection. Unreal's Python must stay on the
# game thread, so the socket is non-blocking and polled from a Slate post-tick callback:
# no thread ever touches the `unreal` module.

from __future__ import annotations

import json
import os
import socket
import tempfile
import time

import unreal

HOST = "127.0.0.1"
PORT_BASE = 7080               # core/constants.py DCC_PORT_RANGES["Unreal"]
PORT_COUNT = 8
STAGE_ACTOR_LABEL = "FLUX_Stage"
LOG_PATH = os.path.join(tempfile.gettempdir(), "flux_unreal_bridge.log")
# EUsdPurpose bitmask: Default=1, Proxy=2, Render=4, Guide=8
PURPOSES = {"proxy": 1 | 2, "render": 1 | 4}
_MAX_REQUEST = 1 << 20


def _log(msg: str) -> None:
    unreal.log(f"[FLUX] {msg}")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


# ── stage actor helpers ───────────────────────────────────────────────────────

def _actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _find_stage_actor():
    for actor in _actors().get_all_level_actors():
        if isinstance(actor, unreal.UsdStageActor) and actor.get_actor_label() == STAGE_ACTOR_LABEL:
            return actor
    return None


def _stage_actor():
    actor = _find_stage_actor()
    if actor is None:
        actor = _actors().spawn_actor_from_class(unreal.UsdStageActor, unreal.Vector(0, 0, 0))
        actor.set_actor_label(STAGE_ACTOR_LABEL)
    return actor


def _root_layer(actor) -> str:
    try:
        return str(actor.get_editor_property("root_layer").file_path or "")
    except Exception:  # noqa: BLE001 - property name may change between versions
        return ""


def _set_purposes(actor, mask: int) -> None:
    if hasattr(actor, "set_purposes_to_load"):
        actor.set_purposes_to_load(mask)
    else:
        actor.set_editor_property("purposes_to_load", mask)


def _set_root_layer(actor, path: str) -> None:
    if hasattr(actor, "set_root_layer"):
        actor.set_root_layer(path)
    else:
        actor.set_editor_property("root_layer", unreal.FilePath(path))


# Layer file times seen at the last (re)load: reload only re-reads what changed.
_layer_mtimes: dict[str, float] = {}


def _scan_layer_mtimes(path: str) -> dict[str, float]:
    try:
        from pxr import Usd  # Unreal's own USD bindings (USD plugins)
    except Exception:  # noqa: BLE001
        return {}
    stage = Usd.Stage.Open(path, Usd.Stage.LoadNone)
    out = {}
    for layer in stage.GetUsedLayers():
        real = layer.realPath
        if real and os.path.isfile(real):
            out[real] = os.path.getmtime(real)
    return out


# ── commands ──────────────────────────────────────────────────────────────────

def _cmd_ping(_req: dict) -> dict:
    return {"status": "ok", "version": f"Unreal {unreal.SystemLibrary.get_engine_version()}"}


def _cmd_info(_req: dict) -> dict:
    actor = _find_stage_actor()
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    return {
        "status": "ok",
        "version": unreal.SystemLibrary.get_engine_version(),
        "project": unreal.Paths.get_project_file_path(),
        "level": world.get_path_name() if world else None,
        "stage": _root_layer(actor) if actor else None,
    }


def _cmd_open_stage(req: dict) -> dict:
    path = str(req.get("path") or "").replace("\\", "/")
    if not path or not os.path.isfile(path):
        return {"status": "error", "msg": f"stage introuvable : {path}"}
    purpose = str(req.get("purpose") or "proxy")
    actor = _stage_actor()
    _set_purposes(actor, PURPOSES.get(purpose, PURPOSES["proxy"]))
    start = time.perf_counter()
    _set_root_layer(actor, path)
    seconds = round(time.perf_counter() - start, 3)
    _layer_mtimes.clear()
    _layer_mtimes.update(_scan_layer_mtimes(path))
    _log(f"open_stage {path} ({purpose}) {seconds} s")
    return {"status": "ok", "path": path, "purpose": purpose, "seconds": seconds}


def _cmd_reload(_req: dict) -> dict:
    """Re-read only the layers whose file changed on disk since the last (re)load."""
    actor = _find_stage_actor()
    if actor is None or not _root_layer(actor):
        return {"status": "error", "msg": "aucun stage FLUX ouvert dans Unreal"}
    root = _root_layer(actor)
    try:
        from pxr import Sdf
    except Exception:  # noqa: BLE001 - no pxr: full reload of the root layer
        start = time.perf_counter()
        _set_root_layer(actor, root)
        return {"status": "ok", "mode": "full", "seconds": round(time.perf_counter() - start, 3)}
    changed = [p for p, m in _layer_mtimes.items() if os.path.isfile(p) and os.path.getmtime(p) != m]
    start = time.perf_counter()
    for path in changed:
        layer = Sdf.Layer.Find(path)
        if layer:
            layer.Reload(force=True)
    if hasattr(actor, "reload_animations"):
        actor.reload_animations()
    _layer_mtimes.update(_scan_layer_mtimes(root))
    seconds = round(time.perf_counter() - start, 3)
    _log(f"reload {len(changed)} layer(s) {seconds} s")
    return {"status": "ok", "mode": "targeted", "changed": changed, "seconds": seconds}


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a or "")) == os.path.normcase(os.path.normpath(b or ""))


# Houdini live (FLUX Unreal Live LOP): paused from the FLUX menu of Unreal.
_live = {"paused": False, "purpose": "proxy"}


def _cmd_live(req: dict) -> dict:
    """A Houdini live push: first push opens the live layer, the next ones reload what changed."""
    if _live["paused"]:
        return {"status": "ok", "paused": True}
    path = str(req.get("path") or "").replace("\\", "/")
    actor = _find_stage_actor()
    if actor is None or not _same_path(_root_layer(actor), path):
        answer = _cmd_open_stage({"path": path, "purpose": _live["purpose"]})
        answer["mode"] = "open"
        return answer
    return _cmd_reload(req)


def _cmd_live_pause(req: dict) -> dict:
    _live["paused"] = bool(req.get("paused", not _live["paused"]))
    return {"status": "ok", "paused": _live["paused"]}


_COMMANDS = {
    "ping": _cmd_ping,
    "info": _cmd_info,
    "open_stage": _cmd_open_stage,
    "reload": _cmd_reload,
    "live": _cmd_live,
    "live_pause": _cmd_live_pause,
}


# ── FLUX menu in the Unreal main menu bar (the Unreal "shelf") ───────────────

def menu_reload() -> None:
    _log(f"menu reload: {_cmd_reload({})}")


def menu_toggle_live() -> None:
    state = _cmd_live_pause({})
    unreal.log(f"[FLUX] Live Houdini {'en pause' if state['paused'] else 'actif'}")


def menu_quality(purpose: str) -> None:
    """Reload the open stage with proxy (interactive) or render geometry."""
    _live["purpose"] = purpose
    actor = _find_stage_actor()
    if actor is not None and _root_layer(actor):
        _log(f"menu quality: {_cmd_open_stage({'path': _root_layer(actor), 'purpose': purpose})}")


def menu_open_log() -> None:
    if os.path.isfile(LOG_PATH):
        os.startfile(LOG_PATH)  # noqa: S606 - local log file written by this bridge


_MENU_ENTRIES = (
    ("flux_reload", "Recharger le stage", "Relire les layers changes sur le disque", "menu_reload()"),
    ("flux_live", "Live Houdini : actif / pause", "Suivre ou ignorer les envois du node FLUX Unreal Live",
     "menu_toggle_live()"),
    ("flux_proxy", "Qualite : proxy", "Geometrie proxy (interactif)", "menu_quality('proxy')"),
    ("flux_render", "Qualite : rendu", "Geometrie complete (avant un rendu)", "menu_quality('render')"),
    ("flux_log", "Ouvrir le log FLUX", "Log du bridge FLUX", "menu_open_log()"),
)


def _install_menu() -> None:
    """FLUX entry in the main menu bar. Best effort: the bridge works without it."""
    try:
        menus = unreal.ToolMenus.get()
        main = menus.find_menu("LevelEditor.MainMenu")
        flux = main.add_sub_menu(main.get_name(), "FLUX", "FLUX", "FLUX", "FLUX pipeline")
        for name, label, tip, call in _MENU_ENTRIES:
            entry = unreal.ToolMenuEntry(name=name, type=unreal.MultiBlockType.MENU_ENTRY)
            entry.set_label(label)
            entry.set_tool_tip(tip)
            entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, "",
                                     f"import flux_unreal_bridge as _f; _f.{call}")
            flux.add_menu_entry("FLUX", entry)
        menus.refresh_all_widgets()
    except Exception as exc:  # noqa: BLE001 - menu API differs between versions
        _log(f"FLUX menu not added: {exc}")


def handle(request: dict) -> dict:
    command = _COMMANDS.get(str(request.get("action")))
    if command is None:
        return {"status": "error", "msg": f"action inconnue : {request.get('action')}"}
    try:
        return command(request)
    except Exception as exc:  # noqa: BLE001 - every failure goes back to FLUX
        _log(f"{request.get('action')} failed: {exc}")
        return {"status": "error", "msg": str(exc)}


# ── non-blocking server polled on the editor tick ─────────────────────────────

class _Server:
    def __init__(self) -> None:
        self.sock: socket.socket | None = None
        self.port: int | None = None
        self.clients: dict[socket.socket, bytes] = {}
        self.tick_handle = None

    def start(self) -> None:
        for port in range(PORT_BASE, PORT_BASE + PORT_COUNT):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Windows: a port of our own, never shared with a SO_REUSEADDR socket (same as
            # the other bridges, 2026-09-26: shared ports answered "ne repond pas" at random).
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                sock.bind((HOST, port))
            except OSError:
                sock.close()
                continue
            sock.listen(8)
            sock.setblocking(False)
            self.sock, self.port = sock, port
            break
        if self.sock is None:
            _log(f"no free port in {PORT_BASE}..{PORT_BASE + PORT_COUNT - 1}")
            return
        self.tick_handle = unreal.register_slate_post_tick_callback(self.tick)
        _log(f"bridge listening on {HOST}:{self.port}")

    def tick(self, _delta: float) -> None:
        try:
            while True:
                conn, _addr = self.sock.accept()
                conn.setblocking(False)
                self.clients[conn] = b""
        except (BlockingIOError, OSError):
            pass
        for conn in list(self.clients):
            self._poll_client(conn)

    def _poll_client(self, conn: socket.socket) -> None:
        try:
            chunk = conn.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            self._drop(conn)
            return
        if not chunk:
            self._drop(conn)
            return
        buf = self.clients[conn] + chunk
        if b"\n" not in buf and len(buf) < _MAX_REQUEST:
            self.clients[conn] = buf
            return
        line = buf.split(b"\n", 1)[0]
        try:
            request = json.loads(line.decode("utf-8"))
            answer = handle(request) if isinstance(request, dict) else {"status": "error", "msg": "not an object"}
        except ValueError as exc:
            answer = {"status": "error", "msg": f"bad json: {exc}"}
        try:
            conn.setblocking(True)
            conn.sendall((json.dumps(answer) + "\n").encode("utf-8"))
        except OSError:
            pass
        self._drop(conn)

    def _drop(self, conn: socket.socket) -> None:
        self.clients.pop(conn, None)
        try:
            conn.close()
        except OSError:
            pass


_server: _Server | None = None


def start() -> None:
    """Start once per editor session (init_unreal.py may be imported twice)."""
    global _server
    if _server is not None:
        return
    _server = _Server()
    _server.start()
    _install_menu()
