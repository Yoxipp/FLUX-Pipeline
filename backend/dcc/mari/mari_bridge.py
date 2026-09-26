"""
FLUX Mari bridge plugin (V6 B7, verify live).

Runs inside Mari (the `mari` module). Starts a local TCP server (newline-JSON) so
the FLUX backend can ping Mari and trigger a channel export.

Protocol:
  {"action": "ping"}                                    -> {"status": "ok", "version": "..."}
  {"action": "export", "export_path": "...", "file_format": "tif"} -> {"status": "ok", "files": [...]}

FLUX Export node (2026-09-26): a pass-through custom node the bridge registers in
Mari (node palette category FLUX, and menu FLUX > FLUX Export). The artist plugs it
after a Bake Point (or any node) and picks the FLUX map in its "Map FLUX" list. When
the current geo holds FLUX Export nodes, FLUX lists and exports those nodes instead of
the channels: from the baked result when the node sits right after an up to date Bake
Point (nothing is evaluated), otherwise through the Export Manager with the node as
source. No FLUX Export node = the channels, as before.

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


_draining = False


def _drain() -> None:
    # Mari pumps Qt events while it flattens / writes a channel, so this timer fires
    # again in the middle of an export: never start another Mari call inside one (a
    # nested info / export during a flatten can crash Mari, 2026-09-26).
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
                # Its caller gave up waiting (Mari was busy): nobody reads the answer.
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


def _is_hidden(channel) -> bool:
    """Channels Mari keeps for itself (not in the Channels palette) are not offered."""
    for attr in ("isHidden", "hidden"):
        fn = getattr(channel, attr, None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:  # noqa: BLE001 - API differs between versions
                return False
    return False


def _channel_ids(channels) -> list:
    """[(id, channel)]: a geo can hold two channels of one name (2026-09-26: two
    "Ambient Occlusion"); the second one is "Ambient Occlusion (2)", in the Publisher
    list and in its file name, so they never overwrite each other."""
    seen: dict = {}
    out = []
    for ch in channels:
        if _is_hidden(ch):
            continue
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
        nodes = _flux_nodes(geo)
        if nodes:
            items = []
            for nid, node, _fmap in _node_ids(nodes):
                src = _input_of(node)
                item = {"name": nid, "node": _node_name(node),
                        "input": _node_name(src) if src is not None else ""}
                if src is not None and _is_bake_point(src):
                    item["baked"] = _baked_ok(src)
                items.append(item)
            return {"status": "ok", "geo": geo.name(), "channels": items, "mode": "nodes"}
        chans = []
        for cid, channel in _channel_ids(geo.channelList()):
            item = {"name": cid, "depth": _depth(channel)}
            try:
                item["size"] = int(channel.width())
            except Exception:  # noqa: BLE001 - optional detail
                item["size"] = 0
            try:
                item["layers"] = len(channel.layerList())
            except Exception:  # noqa: BLE001 - optional detail
                pass
            chans.append(item)
        return {"status": "ok", "geo": geo.name(), "channels": chans, "mode": "channels"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "msg": str(exc)}


def _depth(channel) -> int:
    """Bit depth of a channel: 8 (byte), 16 (half) or 32 (float)."""
    try:
        return int(channel.depth())
    except Exception:  # noqa: BLE001
        return 8


def _describe(geo, channel) -> str:
    """Tiles / size / layers of a channel, for the log (where a slow export spends time)."""
    bits = []
    for label, fn in (("tuiles", lambda: len(geo.patchList())), ("px", lambda: int(channel.width())),
                      ("calques", lambda: len(channel.layerList()))):
        try:
            bits.append(f"{fn()} {label}")
        except Exception:  # noqa: BLE001 - informative only
            pass
    return ", ".join(bits)


def _container(channel, file_format: str, wanted: str = "") -> str:
    """"auto": the map's own format (*wanted*) when it holds the channel's depth, so FLUX
    keeps the file as is (2026-09-26: publish too slow); otherwise a lossless file
    FLUX converts after: tif for 8 bits, exr for float."""
    if file_format != "auto":
        return file_format
    wanted = (wanted or "").lower().lstrip(".")
    wanted = {"tiff": "tif", "jpeg": "jpg"}.get(wanted, wanted)
    if _depth(channel) <= 8:
        return wanted if wanted in ("tif", "png", "tga", "jpg") else "tif"
    return "exr"


def _do_export(export_path: str, file_format: str, channels: list | None = None,
               formats: dict | None = None, sizes: dict | None = None) -> dict:
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
        if _flux_nodes(geo):
            return _do_export_nodes(geo, export_path, wanted, formats or {}, sizes or {})
        for name, channel in _channel_ids(geo.channelList()):
            if wanted and name not in wanted:
                continue
            # One file per channel named after the channel only (FLUX turns the name into
            # the MAP token); Mari fills $UDIM with each tile number.
            fmt = _container(channel, file_format, (formats or {}).get(name) or (formats or {}).get("*", ""))
            out = os.path.join(export_path, f"{name}.$UDIM.{fmt}")
            t0 = _time.time()
            _diag(f"Mari channel start {name} ({fmt}, {_depth(channel)} bits, {_describe(geo, channel)})")
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


# ── FLUX Export node (2026-09-26) ────────────────────────────────────────
# Canonical FLUX map tokens, in the order the list shows them. Must match the keys of
# backend/dcc/texture_publish.py MAP_ALIASES (test_mari_flux_node); the bridge runs
# inside Mari and cannot import the backend.
FLUX_MAPS = ["BCOL", "ROUGH", "METAL", "SPEC", "NORM", "BUMP", "DISP", "ZDISP", "AO", "OPACITY",
             "EMISS", "SSS", "GLOSS", "TRANS", "CAVITY", "CURV", "ISO"]
# A few aliases to guess the map from the node it is plugged after ("BAKE_COL" -> BCOL).
_MAP_HINTS = [("zdisp", "ZDISP"), ("disp", "DISP"), ("height", "DISP"), ("rough", "ROUGH"),
              ("metal", "METAL"), ("spec", "SPEC"), ("norm", "NORM"), ("nrm", "NORM"), ("bump", "BUMP"),
              ("occl", "AO"), ("opac", "OPACITY"), ("alpha", "OPACITY"), ("emi", "EMISS"),
              ("sss", "SSS"), ("subsurf", "SSS"), ("gloss", "GLOSS"), ("trans", "TRANS"),
              ("cavity", "CAVITY"), ("curv", "CURV"), ("iso", "ISO"), ("col", "BCOL"),
              ("albedo", "BCOL"), ("diff", "BCOL"), ("ao", "AO")]
NODE_ID = "FLUX_Export"
NODE_REG_NAME = "FLUX/FLUX Export"
META_MAP = "FLUX_MAP"

_NODE_XML = """<Node>
    <ID>FLUX_Export</ID>
    <DefaultName>FLUX Export</DefaultName>
    <Category>/FLUX/</Category>
    <Cost>0.001</Cost>
    <CostDescription>Pass-through: marks the map FLUX exports</CostDescription>
    <Inputs>
        <Input Name="Input"></Input>
    </Inputs>
    <Contexts>
        <Context Type="NodeGraphView">
            <Inputs>
                <Input Name="Input"><Pos>0,-50</Pos></Input>
            </Inputs>
        </Context>
        <Context Type="GLSL">
            <Shader>
                <Inputs>
                    <Input Name="Input"><Default>vec4(0.0,0.0,0.0,1.0)</Default></Input>
                </Inputs>
                <Body><![CDATA[
    Output = #Input;
                ]]></Body>
            </Shader>
        </Context>
    </Contexts>
</Node>
"""

_node_registered = False


def guess_map(name: str) -> str:
    """FLUX map token guessed from a node / channel name ("BAKE_COL" -> BCOL), BCOL when
    nothing matches. Exact tokens win ("ZDISP" is never DISP)."""
    low = (name or "").lower()
    for part in [p for p in low.replace("-", "_").replace(" ", "_").split("_") if p]:
        if part.upper() in FLUX_MAPS:
            return part.upper()
    for hint, token in _MAP_HINTS:
        if hint in low:
            return token
    return "BCOL"


def _node_name(node) -> str:
    try:
        return node.name()
    except Exception:  # noqa: BLE001
        return "?"


def _node_type(node) -> str:
    for attr in ("typeID", "nodeType", "type"):
        fn = getattr(node, attr, None)
        if callable(fn):
            try:
                return str(fn())
            except Exception:  # noqa: BLE001
                continue
    return type(node).__name__


def is_flux_node(type_id: str) -> bool:
    low = (type_id or "").lower().replace(" ", "_")
    return "flux_export" in low


def _input_of(node):
    """The node plugged into the FLUX Export node, or None."""
    for call in (lambda: node.inputNode("Input"), lambda: node.inputNode(0)):
        try:
            got = call()
        except Exception:  # noqa: BLE001 - API differs between versions
            continue
        if isinstance(got, (tuple, list)):
            got = got[0] if got else None
        if got is not None:
            return got
    try:
        got = node.inputNodes()
        got = list(got.values()) if isinstance(got, dict) else list(got)
        got = [g[0] if isinstance(g, (tuple, list)) and g else g for g in got]
        return next((g for g in got if g is not None), None)
    except Exception:  # noqa: BLE001
        return None


def _is_bake_point(node) -> bool:
    low = (_node_type(node) + " " + type(node).__name__).lower()
    return "bake" in low


def _baked_ok(node) -> bool:
    """A Bake Point holding an up to date baked result (export it as is, nothing evaluated)."""
    for name in ("isBakedResultUpToDate", "hasBakedResult"):
        fn = getattr(node, name, None)
        if callable(fn):
            try:
                if not fn():
                    return False
            except Exception:  # noqa: BLE001
                return False
        elif name == "hasBakedResult":
            return False
    return True


def _map_of(node) -> str:
    try:
        value = str(node.metadata(META_MAP) or "").strip().upper()
        if value in FLUX_MAPS:
            return value
    except Exception:  # noqa: BLE001 - no metadata yet
        pass
    return ""


def _ensure_map_meta(node, default: str = "") -> str:
    """Give the node its "Map FLUX" list when it has none (a node made from the
    palette); return its map."""
    current = _map_of(node)
    if current:
        return current
    src = _input_of(node)
    value = default or guess_map(_node_name(src) if src is not None else _node_name(node))
    try:
        node.setMetadata(META_MAP, value)
        node.setMetadataItemList(META_MAP, list(FLUX_MAPS))
        try:
            node.setMetadataDisplayName(META_MAP, "Map FLUX")
        except Exception:  # noqa: BLE001 - optional
            pass
    except Exception as exc:  # noqa: BLE001
        _diag(f"FLUX Export {_node_name(node)}: map list not set ({exc!r})")
    return value


def _flux_nodes(geo) -> list:
    try:
        nodes = list(geo.nodeGraph().nodeList())
    except Exception:  # noqa: BLE001 - no node graph API
        return []
    return [n for n in nodes if is_flux_node(_node_type(n))]


def _node_ids(nodes) -> list:
    """[(id, node, map)]: id = the map, "BCOL (2)" for a second node on the same map."""
    seen: dict = {}
    out = []
    for node in nodes:
        fmap = _ensure_map_meta(node)
        seen[fmap] = seen.get(fmap, 0) + 1
        out.append((fmap if seen[fmap] == 1 else f"{fmap} ({seen[fmap]})", node, fmap))
    return out


def _register_flux_node() -> None:
    """Register the FLUX Export node type and the FLUX menu (main thread, at startup)."""
    global _node_registered
    if _node_registered or not _MARI_AVAILABLE:
        return
    xml = os.path.join(_tempfile.gettempdir(), "flux_export_node.xml")
    try:
        with open(xml, "w", encoding="utf-8") as fh:
            fh.write(_NODE_XML)
        mari.gl_render.registerCustomNodeFromXMLFile(NODE_REG_NAME, xml)
        _node_registered = True
        _diag(f"FLUX Export node registered ({NODE_REG_NAME})")
    except Exception as exc:  # noqa: BLE001 - already registered in this session, or no API
        _diag(f"FLUX Export node registration: {exc!r}")
    try:
        import builtins
        builtins._flux_mari_new_export_node = new_export_node
        action = mari.actions.create(
            "FLUX Export", "import builtins; builtins._flux_mari_new_export_node()")
        mari.menus.addAction(action, "MainWindow/FLUX")
        _diag("FLUX menu added (FLUX > FLUX Export)")
    except Exception as exc:  # noqa: BLE001
        _diag(f"FLUX menu not added: {exc!r}")


def _create_flux_node(graph):
    errors = []
    for type_name in (NODE_REG_NAME, "Custom/" + NODE_REG_NAME, NODE_ID, "FLUX Export"):
        try:
            return graph.createNode(type_name)
        except Exception as exc:  # noqa: BLE001 - type naming differs between versions
            errors.append(f"{type_name}: {exc}")
    raise RuntimeError("creation du node FLUX Export impossible : " + " | ".join(errors[:4]))


def new_export_node() -> None:
    """Menu FLUX > FLUX Export: one FLUX Export node after each selected node (or a free
    one), its map guessed from the selected node's name, changeable in "Map FLUX"."""
    if not _MARI_AVAILABLE:
        return
    try:
        geo = mari.geo.current()
        if geo is None:
            _diag("FLUX Export: no current geo")
            return
        graph = geo.nodeGraph()
        try:
            selected = [n for n in graph.selectedNodeList() if not is_flux_node(_node_type(n))]
        except Exception:  # noqa: BLE001
            selected = []
        for src in selected or [None]:
            node = _create_flux_node(graph)
            if src is not None:
                try:
                    node.setInputNode("Input", src)
                except Exception as exc:  # noqa: BLE001
                    _diag(f"FLUX Export: not plugged after {_node_name(src)} ({exc!r})")
                try:
                    pos = src.nodeGraphPosition()
                    node.setNodeGraphPosition(type(pos)(pos.x(), pos.y() + 80))
                except Exception:  # noqa: BLE001 - cosmetic
                    pass
            fmap = _ensure_map_meta(node, guess_map(_node_name(src)) if src is not None else "BCOL")
            try:
                node.setName(f"FLUX_{fmap}")
            except Exception:  # noqa: BLE001 - cosmetic
                pass
            _diag(f"FLUX Export node created ({fmap}, after {_node_name(src) if src is not None else 'rien'})")
    except Exception as exc:  # noqa: BLE001
        _diag(f"FLUX Export: {exc!r}")


def _node_container(wanted: str) -> str:
    """Mari writes the node at its own depth: exr when the map wants exr, tif otherwise
    (tif holds 8, 16 and 32 bits; FLUX converts after when the map wants another format)."""
    wanted = (wanted or "").lower().lstrip(".")
    return "exr" if wanted == "exr" else "tif"


def _export_baked(bake, out_template: str) -> None:
    """exportBakedResult of a Bake Point into *out_template*; its own Export Path is
    restored after."""
    old = None
    try:
        old = bake.exportPath()
    except Exception:  # noqa: BLE001
        pass
    try:
        bake.setExportPath(out_template)
        errors = []
        opts = getattr(getattr(mari, "Image", None), "DEFAULT_OPTIONS", 0)
        for args in ((False, opts, []), (False, opts, [], {}), (False,), ()):
            try:
                bake.exportBakedResult(*args)
                return
            except TypeError as exc:
                errors.append(str(exc))
        raise RuntimeError("exportBakedResult : " + " | ".join(errors[:3]))
    finally:
        if old is not None:
            try:
                bake.setExportPath(old)
            except Exception:  # noqa: BLE001
                pass


def _em_remove(item, geo) -> None:
    for name in ("removeExportItem", "removeExportItems", "deleteExportItem", "deleteExportItems"):
        fn = getattr(mari.exports, name, None)
        if not callable(fn):
            continue
        for args in ((item, geo), (item,), ([item], geo), ([item],)):
            try:
                fn(*args)
                return
            except Exception:  # noqa: BLE001
                continue
    _diag("FLUX Export: Export Manager item not removed (FLUX_* item to delete by hand)")


def _export_manager(geo, node, template: str, out_dir: str, size: int = 0) -> None:
    """Export *node* through the Export Manager (item added to the geo, removed after).
    The size is asked to Mari when given; a refused override retries at full size
    (FLUX resizes after anyway)."""
    item = mari.ExportItem()
    item.setSourceNode(node)
    item.setFileTemplate(template)
    mari.exports.addExportItem(item, geo)
    try:
        done = False
        if size:
            try:
                mari.exports.exportTextures([item], out_dir, {"RESOLUTION": f"{size} x {size}"}, False)
                done = True
            except Exception as exc:  # noqa: BLE001
                _diag(f"FLUX Export: size {size} refused by Mari ({exc!r}), full size")
        if not done:
            mari.exports.exportTextures([item], out_dir)
        try:
            errs = list(item.errorStringList())
        except Exception:  # noqa: BLE001
            errs = []
        if errs:
            raise RuntimeError("; ".join(str(e) for e in errs[:3]))
    finally:
        _em_remove(item, geo)


def _do_export_nodes(geo, export_path: str, wanted: set, formats: dict, sizes: dict) -> dict:
    import glob

    files: list = []
    errors: list = []
    for nid, node, fmap in _node_ids(_flux_nodes(geo)):
        if wanted and nid not in wanted:
            continue
        stem = nid  # same file naming as a channel ("BCOL (2).1001.tif"), FLUX keys its params on it
        fmt = _node_container(formats.get(nid) or formats.get("*", ""))
        template = f"{stem}.$UDIM.{fmt}"
        src = _input_of(node)
        if src is None:
            errors.append(f"{nid} : rien n'est branche dans le node {_node_name(node)}")
            continue
        t0 = _time.time()
        baked = _is_bake_point(src) and _baked_ok(src)
        how = f"bake {_node_name(src)}" if baked else f"Export Manager depuis {_node_name(node)}"
        _diag(f"Mari channel start {nid} ({fmt}, {how})")
        try:
            if baked:
                _export_baked(src, os.path.join(export_path, template))
            else:
                _export_manager(geo, node, template, export_path, int(sizes.get(nid) or 0))
        except Exception as exc:  # noqa: BLE001 - one bad node never aborts all
            errors.append(f"{nid} : {exc}")
            _diag(f"Mari node export failed ({nid}): {exc!r}")
            continue
        _diag(f"Mari channel {nid}: {_time.time() - t0:.1f} s ({fmt}, {how})")
        written = sorted(glob.glob(os.path.join(glob.escape(export_path), f"{glob.escape(stem)}.*")))
        written = [w for w in written if "$UDIM" not in w]
        if written:
            files.extend(written)
        else:
            errors.append(f"{nid} : aucun fichier ecrit ({how})")
    _diag(f"Mari export (FLUX Export nodes): {len(files)} file(s), errors={errors}")
    if not files:
        return {"status": "error", "msg": "Mari n'a ecrit aucun fichier depuis les nodes FLUX Export : "
                + " ; ".join(errors[:4])}
    return {"status": "ok", "files": files, "errors": errors, "mode": "nodes"}


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
        fmts = cmd.get("formats") or None
        sizes = cmd.get("sizes") or None
        # A big UDIM export takes long: never answer "busy" while Mari is still writing.
        def export():
            return _do_export(path, fmt, chans, fmts, sizes)
        return _on_main_thread(export, timeout=4 * 3600.0)
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
        _register_flux_node()
    try:
        sock = _listen(HOST, PORT)
        _server_sock = sock
        builtins._flux_mari_bridge_started = True
        threading.Thread(target=_serve, args=(sock,), daemon=True).start()
        _start_main_thread_pump()
        _diag(f"Mari bridge listening on {HOST}:{PORT} (api={_MARI_AVAILABLE}, file={here})")
    except OSError as exc:
        _diag(f"Mari bridge bind failed on {HOST}:{PORT}: {exc} (port pris : un autre Mari ouvert ? netstat -ano | findstr {PORT})")


# Mari imports every script of its Scripts folders at startup: start the server on
# import inside Mari, not only when run as __main__ (it never is there).
if __name__ == "__main__" or _MARI_AVAILABLE:
    start()
