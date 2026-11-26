"""
bench_export.py - where does a Mari export spend its time? (2026-09-26)

Standalone: the maintainer runs it in Mari's Python console, FLUX closed, no bridge call. It
times the same channel exported several ways and writes everything to
%TEMP%/flux_mari_bench.txt (written line by line: a crash still leaves the numbers).

    exec(open(r"<FLUX>/backend/dcc/mari/bench_export.py", encoding="utf-8").read())
    flux_bench()                      # current channel
    flux_bench(["BCOL", "ROUG"])      # named channels (as in the Channels palette)

Hypotheses measured:
  1. Mari's flatten itself       -> direct exportImagesFlattened, time to 1st tile / per tile
  2. called from a QTimer slot   -> same call via QTimer.singleShot, FLUX bridge timer paused / running
  3. GIL contention              -> % of the time a Python thread gets the GIL during the export,
                                    and the export with a thread spinning in Python
  4. Export Manager API          -> mari.ExportItem / mari.exports at full size then 512 (if it
                                    works without touching the project), API help dumped
  5. format / cache              -> tif vs jpg, top layer "cache up to here" (removed after)
  6. crash                       -> tails of the bridge log and MariLog.txt

Nothing is left changed in the scene: exports go to a temp dir deleted after each
run, a cache made for the test is removed, the bridge timer is restarted. Importable
without Mari (backend syntax test); nothing runs on import.
"""

from __future__ import annotations

import glob
import os
import shutil
import tempfile
import threading
import time
import traceback

try:
    import mari
except Exception:  # noqa: BLE001 - importable from the backend
    mari = None

REPORT_PATH = os.path.join(tempfile.gettempdir(), "flux_mari_bench.txt")
BRIDGE_LOG = os.path.join(tempfile.gettempdir(), "flux_mari_bridge.log")


# ── report ────────────────────────────────────────────────────────────────────

def _out(msg: str = "") -> None:
    """Append to the report (flushed to disk at once) and print to the console."""
    line = time.strftime("%H:%M:%S ") + msg
    try:
        with open(REPORT_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    print("[FLUX bench] " + msg)


def _try(label: str, fn, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - every probe is optional
        _out(f"  ({label} : {type(exc).__name__}: {exc})")
        return default


def _qtcore():
    for mod in ("PySide6", "PySide2"):
        try:
            return __import__(mod + ".QtCore", fromlist=["QtCore"])
        except Exception:  # noqa: BLE001
            continue
    return None


def _image_size(path: str) -> str:
    for mod in ("PySide6", "PySide2"):
        try:
            QtGui = __import__(mod + ".QtGui", fromlist=["QtGui"])
            img = QtGui.QImage(path)
            if not img.isNull():
                return f"{img.width()}x{img.height()}"
        except Exception:  # noqa: BLE001
            continue
    return "?"


# ── pure helpers (unit-tested in the backend) ────────────────────────────────

def tile_timeline(started_wall: float, files: list, mtimes: dict | None = None) -> dict:
    """Timing of the written tiles from their modification time: seconds from the call
    to the first tile (flatten / setup before any write), to the last one, and the
    largest gap between two tiles."""
    stamps = []
    for f in files:
        try:
            stamps.append((mtimes or {}).get(f) or os.path.getmtime(f))
        except OSError:
            continue
    stamps.sort()
    if not stamps:
        return {"tiles": 0}
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    return {"tiles": len(stamps), "first_s": stamps[0] - started_wall, "last_s": stamps[-1] - started_wall,
            "max_gap_s": max(gaps) if gaps else 0.0,
            "mean_gap_s": (sum(gaps) / len(gaps)) if gaps else 0.0}


def last_unfinished_job(lines: list) -> str:
    """The bridge's last "main thread: X start" without its "done" (call running at a crash)."""
    open_job = ""
    for line in lines:
        text = line[20:] if len(line) > 20 and line[4] == "-" else line
        if text.startswith("main thread: ") and text.endswith(" start"):
            open_job = text[len("main thread: "):-len(" start")]
        elif text.startswith("main thread: ") and text.endswith(" done"):
            open_job = ""
    return open_job


def gil_share(ticks: int, seconds: float, tick_s: float) -> float:
    """Share of the export during which a sleeping Python thread got the GIL back (0-1)."""
    if seconds <= 0 or tick_s <= 0:
        return 0.0
    return max(0.0, min(1.0, ticks * tick_s / seconds))


# ── FLUX bridge timer (hypothesis 2) ─────────────────────────────────────────

def _bridge_timer():
    """The FLUX bridge's 50 ms QTimer, found through its _drain function (Mari may
    exec() the bridge without a module entry)."""
    import gc
    for obj in gc.get_objects():
        try:
            if callable(obj) and getattr(obj, "__name__", "") == "_drain":
                g = getattr(obj, "__globals__", {})
                if "flux_mari_bridge.log" in str(g.get("_LOG_PATH", "")) and g.get("_timer") is not None:
                    return g["_timer"]
        except Exception:  # noqa: BLE001
            continue
    return None


_BRIDGE = {}


class _BridgePaused:
    def __init__(self, pause: bool):
        if "timer" not in _BRIDGE:
            _BRIDGE["timer"] = _bridge_timer()
        self.timer = _BRIDGE["timer"] if pause else None

    def __enter__(self):
        if self.timer is not None:
            self.timer.stop()
        return self

    def __exit__(self, *exc):
        if self.timer is not None:
            self.timer.start(50)
        return False


# ── probe threads (hypothesis 3) ─────────────────────────────────────────────

class _GilProbe:
    """"sleep": a thread ticking every 10 ms (it only runs when the GIL is free);
    "spin": a thread looping in Python (competes for the GIL all the time)."""

    TICK_S = 0.01

    def __init__(self, mode: str):
        self.mode = mode
        self.ticks = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        if self.mode == "spin":
            while not self._stop.is_set():
                self.ticks += 1
        else:
            while not self._stop.is_set():
                time.sleep(self.TICK_S)
                self.ticks += 1

    def __enter__(self):
        if self.mode:
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self.mode:
            self._thread.join(2.0)
        return False


# ── scene description ────────────────────────────────────────────────────────

def _walk_layers(layers, depth=0, acc=None):
    acc = acc if acc is not None else {"total": 0, "types": {}, "cached": 0, "hidden": 0, "max_depth": 0}
    for layer in layers or []:
        acc["total"] += 1
        acc["max_depth"] = max(acc["max_depth"], depth)
        kind = type(layer).__name__
        for attr, label in (("isProceduralLayer", "procedural"), ("isAdjustmentLayer", "adjustment"),
                            ("isGroupLayer", "group"), ("isPaintableLayer", "paint"),
                            ("isChannelLayer", "channel"), ("isShaderLayer", "shader")):
            try:
                if getattr(layer, attr)():
                    kind = label
                    break
            except Exception:  # noqa: BLE001
                continue
        acc["types"][kind] = acc["types"].get(kind, 0) + 1
        for attr, key in (("isCachedUpToHere", "cached"),):
            try:
                if getattr(layer, attr)():
                    acc[key] += 1
            except Exception:  # noqa: BLE001
                pass
        try:
            if not layer.isVisible():
                acc["hidden"] += 1
        except Exception:  # noqa: BLE001
            pass
        for sub in ("layerStack", "maskStack"):
            try:
                stack = getattr(layer, sub)()
                if stack is not None:
                    _walk_layers(stack.layerList(), depth + 1, acc)
            except Exception:  # noqa: BLE001
                continue
    return acc


def is_bake_node(type_id: str, class_name: str = "") -> bool:
    """A Bake Point node (typeID / class name contain "bake")."""
    return "bake" in (str(type_id) + " " + str(class_name)).lower()


def _node_type(node) -> str:
    for attr in ("typeID", "nodeType"):
        try:
            return str(getattr(node, attr)())
        except Exception:  # noqa: BLE001
            continue
    return type(node).__name__


def _node_name(node) -> str:
    for attr in ("nodeName", "name"):
        try:
            return str(getattr(node, attr)())
        except Exception:  # noqa: BLE001
            continue
    return "?"


def _upstream(node, seen=None, limit=2000, bakes=None) -> dict:
    """Node types feeding *node* in Mari's node graph (a channel with 0 layers may be a
    whole node network, evaluated at full size on every export). Bake Point nodes met on
    the way go to *bakes* (nearest first); the walk does not go above them."""
    seen = seen if seen is not None else {}
    stack = [node]
    visited = set()
    while stack and len(visited) < limit:
        cur = stack.pop(0)
        key = id(cur)
        try:
            key = cur.uuid()
        except Exception:  # noqa: BLE001
            pass
        if cur is None or key in visited:
            continue
        visited.add(key)
        kind = _node_type(cur)
        seen[kind] = seen.get(kind, 0) + 1
        if cur is not node and is_bake_node(kind, type(cur).__name__):
            if bakes is not None:
                bakes.append(cur)
            continue  # what is above a bake point is not evaluated when it is baked
        inputs = []
        try:
            got = cur.inputNodes()
            inputs = list(got.values()) if isinstance(got, dict) else list(got)
        except Exception:  # noqa: BLE001
            try:
                inputs = [cur.inputNode(n) for n in cur.inputPortNames()]
            except Exception:  # noqa: BLE001
                inputs = []
        for inp in inputs:
            if isinstance(inp, (tuple, list)) and inp:
                inp = inp[0]
            if inp is not None:
                stack.append(inp)
    return seen


def _describe(geo, channel) -> None:
    _out(f"channel {channel.name()}")
    for label, fn in (("profondeur", lambda: channel.depth()), ("largeur", lambda: channel.width()),
                      ("hauteur", lambda: channel.height()), ("patches", lambda: len(geo.patchList())),
                      ("colorspace", lambda: channel.colorspaceConfig()),
                      ("cache (channel)", lambda: channel.isCachedUpToHere())):
        val = _try(label, fn, "?")
        _out(f"  {label} : {val}")
    acc = _walk_layers(_try("calques", lambda: channel.layerList(), []))
    _out(f"  calques : {acc['total']} (profondeur max {acc['max_depth']}, caches {acc['cached']}, "
         f"masques/caches {acc['hidden']}) types {acc['types']}")
    node = _try("channelNode", channel.channelNode)
    if node is not None:
        bakes = []
        types = _try("graphe", lambda: _upstream(node, bakes=bakes), {}) or {}
        _out(f"  graphe en amont du channel (jusqu'aux bake points) : {sum(types.values())} node(s) {types}")
        _out(f"  bake points en amont : {[_node_name(b) for b in bakes] or 'aucun'}")
    _out(f"  graphe de la geo : {_try('nodeList', lambda: len(geo.nodeGraph().nodeList()), '?')} node(s)")
    sizes = {}
    for patch in _try("patchList", lambda: geo.patchList(), []) or []:
        try:
            img = channel.imageSet().image(patch.uvIndex()) if hasattr(channel, "imageSet") else None
            key = f"{img.width()}x{img.height()}" if img is not None else "?"
        except Exception:  # noqa: BLE001
            key = "?"
        sizes[key] = sizes.get(key, 0) + 1
    if sizes:
        _out(f"  taille des tuiles : {sizes}")


def _dump_api() -> None:
    """Help text of the export APIs (Foundry's docs are not reachable from the cloud)."""
    import pydoc
    _out("── API ──")
    targets = [("mari.Channel.exportImagesFlattened", lambda: mari.Channel.exportImagesFlattened),
               ("mari.ExportItem", lambda: mari.ExportItem), ("mari.exports", lambda: mari.exports)]
    for label, get in targets:
        obj = _try(label, get)
        if obj is None:
            _out(f"{label} : absent")
            continue
        text = _try(f"help {label}", lambda: pydoc.render_doc(obj, renderer=pydoc.plaintext), "") or ""
        _out(f"{label} :\n" + text[:6000])
    for label, get in (("mari.exports", lambda: mari.exports), ("mari.ExportItem", lambda: mari.ExportItem)):
        obj = _try(label, get)
        if obj is not None:
            _out(f"{label} methodes : {[n for n in dir(obj) if not n.startswith('_')]}")
    for label in ("depthList", "colorspaceList"):
        _out(f"mari.exports.{label}() : {_try(label, lambda: getattr(mari.exports, label)())}")
    consts = [n for n in dir(getattr(mari, "Image", object)) if n.isupper()]
    _out(f"mari.Image constantes : {consts}")


# ── the exports ──────────────────────────────────────────────────────────────

def _written(out_dir: str) -> list:
    return sorted(f for f in glob.glob(os.path.join(glob.escape(out_dir), "*")) if os.path.isfile(f))


def _record(results: list, label: str, seconds: float | None, out_dir: str, started_wall: float,
            extra: str = "") -> None:
    files = _written(out_dir)
    tl = tile_timeline(started_wall, files)
    size = _image_size(files[0]) if files else "-"
    mb = sum(os.path.getsize(f) for f in files) / 1e6 if files else 0.0
    if seconds is None:
        _out(f"[{label}] ECHEC {extra}")
    else:
        detail = (f"1re tuile {tl['first_s']:.1f} s, derniere {tl['last_s']:.1f} s, ecart max {tl['max_gap_s']:.1f} s, "
                  f"moyen {tl['mean_gap_s']:.2f} s") if tl["tiles"] else "aucun fichier"
        _out(f"[{label}] {seconds:.1f} s, {tl['tiles']} fichier(s) {size} {mb:.1f} Mo ; {detail} {extra}".rstrip())
    results.append((label, seconds, tl.get("tiles", 0), size, extra))
    shutil.rmtree(out_dir, ignore_errors=True)


def _flat(channel, fmt: str, label: str, results: list, pause_bridge=True, probe: str = "", tiles=None) -> None:
    out_dir = tempfile.mkdtemp(prefix="flux_mari_bench_")
    path = os.path.join(out_dir, f"{channel.name()}.$UDIM.{fmt}")
    seconds, extra = None, ""
    wall = time.time()
    try:
        with _BridgePaused(pause_bridge) as bp, _GilProbe(probe) as gp:
            wall = time.time()
            t0 = time.perf_counter()
            if tiles:
                channel.exportImagesFlattened(path, mari.Image.DEFAULT_OPTIONS, list(tiles))
            else:
                channel.exportImagesFlattened(path)
            seconds = time.perf_counter() - t0
        if pause_bridge and bp.timer is None:
            extra += "(timer du bridge introuvable) "
        if probe == "sleep":
            extra += f"GIL libre {100 * gil_share(gp.ticks, seconds, _GilProbe.TICK_S):.0f} % du temps"
        elif probe == "spin":
            extra += f"thread Python : {gp.ticks / max(seconds, 1e-6):.0f} tours/s"
    except Exception as exc:  # noqa: BLE001
        extra = f"{type(exc).__name__}: {exc}"
    _record(results, label, seconds, out_dir, wall, extra)


def _spin_rate() -> float:
    """Python loop speed with a free GIL (reference for the "spin" run)."""
    with _GilProbe("spin") as gp:
        time.sleep(1.0)
    return gp.ticks


def _cached(channel, fmt: str, results: list) -> None:
    """Export with the top layer cached ("cache up to here"), then the cache removed."""
    layers = _try("calques", lambda: channel.layerList(), []) or []
    top = layers[-1] if layers else None
    if top is None or not hasattr(top, "cacheUpToHere"):
        _out("[cache] ignore : pas de calque ou pas d'API cacheUpToHere")
        return
    if _try("isCachedUpToHere", lambda: top.isCachedUpToHere(), False):
        _out("[cache] ignore : le calque du haut est deja en cache (les autres mesures l'utilisent deja)")
        return
    t0 = time.perf_counter()
    try:
        with _BridgePaused(True):
            top.cacheUpToHere()
        _out(f"[cache] mise en cache : {time.perf_counter() - t0:.1f} s")
        _flat(channel, fmt, f"{channel.name()} direct {fmt}, calque du haut en cache", results)
    except Exception as exc:  # noqa: BLE001
        _out(f"[cache] ECHEC {type(exc).__name__}: {exc}")
    finally:
        _try("uncacheUpToHere", lambda: top.uncacheUpToHere())


def _call_first(obj, names: list, args_options: list) -> str:
    """Call the first method of *names* that accepts one of *args_options*; what worked."""
    errors = []
    for name in names:
        fn = getattr(obj, name, None)
        if not callable(fn):
            continue
        for args in args_options:
            try:
                fn(*args)
                return f"{name}{args!r}"
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}{args!r}: {exc}")
    raise RuntimeError(" | ".join(errors[:4]) or f"aucune de {names}")


def _em_remover():
    """(name, fn) of the Export Manager call that removes an item, or None."""
    for name in ("removeExportItem", "removeExportItems", "deleteExportItem", "deleteExportItems"):
        fn = getattr(mari.exports, name, None)
        if callable(fn):
            return name, fn
    return None


def _export_manager(geo, channel, fmt: str, size: int, results: list, tiles=None, depth: str = "",
                    keep_item: bool = False, source=None) -> None:
    """Export through the Export Manager (mari.exports.exportTextures). The item must be
    added to the geo first (run 1: not added = nothing written); it is removed after.
    Without a remove call in the API the item is added only when *keep_item* (it then
    stays in the Export Manager, named FLUX_BENCH, to delete by hand)."""
    src_name = _node_name(source) if source is not None else channel.name()
    label = f"{src_name}{' (bake point)' if source is not None else ''} Export Manager {fmt} {size or 'pleine taille'}" + (f" {depth}" if depth else "") \
        + (f" tuile(s) {[1001 + t for t in tiles]}" if tiles else "")
    if not (hasattr(mari, "ExportItem") and hasattr(mari, "exports")):
        _out(f"[{label}] ignore : mari.ExportItem / mari.exports absents")
        return
    remover = _em_remover()
    if remover is None and not keep_item:
        _out(f"[{label}] ignore : pas d'appel pour retirer l'item de l'Export Manager "
             f"(relancer avec keep_item=True : l'item FLUX_BENCH restera a supprimer a la main)")
        return
    out_dir = tempfile.mkdtemp(prefix="flux_mari_bench_")
    notes, added = [], False
    overrides = {}
    if size:
        overrides["RESOLUTION"] = f"{size} x {size}"
    if tiles:
        overrides["UV_INDICES"] = list(tiles)
    if depth:
        overrides["DEPTH"] = depth
    wall = time.time()
    try:
        item = mari.ExportItem()
        item.setSourceNode(source if source is not None else channel.channelNode())
        item.setFileTemplate(f"{src_name}.$UDIM.{fmt}".replace(" ", "_"))
        mari.exports.addExportItem(item, geo)
        added = True
        with _BridgePaused(True):
            wall = time.time()
            t0 = time.perf_counter()
            ret = mari.exports.exportTextures([item], out_dir, overrides or None, False) if overrides \
                else mari.exports.exportTextures([item], out_dir)
            seconds = time.perf_counter() - t0
        notes.append(f"retour {ret!r}")
        errs = _try("errorStringList", item.errorStringList, [])
        if errs:
            notes.append(f"erreurs {errs}")
        notes.append(f"overrides {overrides}")
        _record(results, label, seconds, out_dir, wall, "(" + "; ".join(notes) + ")")
    except Exception as exc:  # noqa: BLE001
        _record(results, label, None, out_dir, wall, f"{type(exc).__name__}: {exc} ({'; '.join(notes)})")
    finally:
        if added and remover is not None:
            name, fn = remover
            for args in ((item, geo), (item,), ([item], geo), ([item],)):
                try:
                    fn(*args)
                    break
                except Exception:  # noqa: BLE001
                    continue
            else:
                _out(f"  item FLUX_BENCH non retire ({name}) : a supprimer a la main dans l'Export Manager")


# ── logs (hypothesis 6) ──────────────────────────────────────────────────────

def _tail(path: str, n: int) -> list:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()[-n:]
    except OSError:
        return []


def _dump_logs() -> None:
    _out("── logs ──")
    lines = _tail(BRIDGE_LOG, 400)
    job = last_unfinished_job(lines)
    _out(f"bridge : appel commence sans fin (crash ?) : {job or 'aucun'}")
    _out("bridge (fin) :\n" + "\n".join(lines[-40:]))
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    for path in (os.path.join(docs, "Mari", "Logs", "MariLog.txt"),
                 os.path.join(os.path.expanduser("~"), "Mari", "Logs", "MariLog.txt")):
        if os.path.isfile(path):
            tail = _tail(path, 400)
            hits = [ln for ln in tail if any(k in ln.lower() for k in ("error", "fatal", "crash", "memory", "vram", "export"))]
            _out(f"{path} : lignes erreur / export (fin du log) :\n" + "\n".join(hits[-40:]))
            break
    else:
        _out("MariLog.txt introuvable (Documents/Mari/Logs)")


# ── entry point ──────────────────────────────────────────────────────────────

def _channels(geo, names):
    chans = list(geo.channelList())
    if not names:
        cur = _try("currentChannel", lambda: geo.currentChannel())
        return [cur] if cur is not None else chans[:1]
    by_name = {c.name(): c for c in chans}
    missing = [n for n in names if n not in by_name]
    if missing:
        _out(f"channels introuvables : {missing} (existants : {sorted(by_name)})")
    return [by_name[n] for n in names if n in by_name]


def _summary(results: list) -> None:
    _out("── resume ──")
    for label, seconds, tiles, size, _extra in results:
        _out(f"  {('%.1f s' % seconds) if seconds is not None else 'ECHEC':>9}  {tiles:>3} f {size:>11}  {label}")
    _out(f"rapport complet : {REPORT_PATH}")


def flux_bench(channels=None, fmt: str = "tif", alt_fmt: str = "jpg", sizes=(0, 512),
               cache: bool = True, export_manager: bool = True, slot: bool = True) -> None:
    """Time the export of *channels* (default: the current channel) every way listed at
    the top of this file. Results in REPORT_PATH, summary at the end."""
    if mari is None:
        print("flux_bench : a lancer dans la console Python de Mari")
        return
    _out("=" * 70)
    _out(f"FLUX bench export Mari, {_try('version', lambda: mari.app.version().string(), '?')}")
    geo = _try("geo courante", mari.geo.current)
    if geo is None:
        _out("aucune geo courante : ouvre le projet Mari a mesurer, puis relance flux_bench()")
        return
    _out(f"geo {geo.name()}, bridge FLUX {'trouve' if _bridge_timer() is not None else 'absent'}")
    _try("api", _dump_api)
    rate = _spin_rate()
    _out(f"reference : thread Python seul {rate:.0f} tours/s")
    results: list = []
    pending = []
    for channel in _channels(geo, channels):
        name = channel.name()
        try:
            _describe(geo, channel)
            _flat(channel, fmt, f"{name} chauffe (non compte)", results, pause_bridge=False)
            _flat(channel, fmt, f"{name} direct {fmt}, bridge en pause", results)
            _flat(channel, fmt, f"{name} direct {fmt}, bridge actif", results, pause_bridge=False)
            _flat(channel, fmt, f"{name} direct {fmt}, sonde GIL", results, probe="sleep")
            _flat(channel, fmt, f"{name} direct {fmt}, thread Python en boucle", results, probe="spin")
            # jpg / png / tga do not hold 16 / 32 bits: exr for a float channel.
            alt = alt_fmt if (_try("depth", channel.depth, 8) or 8) <= 8 or alt_fmt in ("tif", "exr") else "exr"
            if alt and alt != fmt:
                _flat(channel, alt, f"{name} direct {alt}, bridge en pause", results)
            if cache:
                _cached(channel, fmt, results)
            if export_manager:
                for size in sizes:
                    _export_manager(geo, channel, alt or fmt, size, results)
        except Exception:  # noqa: BLE001
            _out(f"{name} : erreur inattendue\n{traceback.format_exc()}")
        pending.append(channel)

    QtCore = _qtcore()
    if not (slot and QtCore and pending):
        _dump_logs()
        _summary(results)
        return

    # Hypothesis 2: the same call from a QTimer slot (as the bridge does), bridge timer
    # paused then running. Chained through the event loop, after this console call ends.
    steps = []
    for channel in pending:
        steps.append(lambda c=channel: _flat(c, fmt, f"{c.name()} QTimer slot {fmt}, bridge en pause", results))
        steps.append(lambda c=channel: _flat(c, fmt, f"{c.name()} QTimer slot {fmt}, bridge actif", results,
                                             pause_bridge=False))

    def next_step():
        if not steps:
            _dump_logs()
            _summary(results)
            return
        try:
            steps.pop(0)()
        except Exception:  # noqa: BLE001
            _out(traceback.format_exc())
        QtCore.QTimer.singleShot(0, next_step)

    _out("mesures depuis un slot QTimer : suite apres la fin de cette commande (ne pas toucher Mari)")
    flux_bench._next = next_step  # keep the callable alive
    QtCore.QTimer.singleShot(0, next_step)


def _inputs(node) -> list:
    try:
        got = node.inputNodes()
        got = list(got.values()) if isinstance(got, dict) else list(got)
    except Exception:  # noqa: BLE001
        try:
            got = [node.inputNode(n) for n in node.inputPortNames()]
        except Exception:  # noqa: BLE001
            got = []
    return [(g[0] if isinstance(g, (tuple, list)) and g else g) for g in got if g is not None]


def _uid(node):
    try:
        return node.uuid()
    except Exception:  # noqa: BLE001
        return id(node)


def feeds(node, target, limit=2000) -> bool:
    """True when *target* is upstream of *node* (a Bake Point placed after the channel)."""
    want, stack, seen = _uid(target), [node], set()
    while stack and len(seen) < limit:
        cur = stack.pop()
        uid = _uid(cur)
        if uid in seen:
            continue
        seen.add(uid)
        if cur is not node and uid == want:
            return True
        stack.extend(_inputs(cur))
    return False


def _bake_status(node) -> str:
    """Every no-argument query of a bake point that says if it is baked / up to date."""
    out = []
    for name in dir(node):
        low = name.lower()
        if name.startswith("_") or not any(k in low for k in ("dirty", "bake", "date", "stale", "valid", "resolution",
                                                                  "depth", "size")):
            continue
        if not (low.startswith("is") or low.startswith("has") or low.startswith("needs") or low in (
                "resolution", "depth", "size", "bakeresolution", "bakedepth")):
            continue
        fn = getattr(node, name, None)
        if callable(fn):
            try:
                out.append(f"{name}()={fn()}")
            except Exception:  # noqa: BLE001 - needs arguments, not a query
                continue
    return ", ".join(out) or "aucune info"


def _bake_inventory(geo) -> list:
    """Bake Point nodes of the geo's graph, their API (once) and status."""
    nodes = _try("nodeList", lambda: list(geo.nodeGraph().nodeList()), []) or []
    bakes = [n for n in nodes if is_bake_node(_node_type(n), type(n).__name__)]
    _out(f"── bake points : {len(bakes)} sur {len(nodes)} node(s) ──")
    if bakes:
        import pydoc
        first = bakes[0]
        _out(f"classe {type(first).__name__}, typeID {_node_type(first)}, methodes : "
             f"{[n for n in dir(first) if not n.startswith('_')]}")
        text = _try("help bake", lambda: pydoc.render_doc(type(first), renderer=pydoc.plaintext), "") or ""
        _out("aide :\n" + text[:8000])
    for b in bakes:
        _out(f"  {_node_name(b)} : {_bake_status(b)}")
    return bakes


def flux_bench_em(channels=None, tile: int = 0, fmt: str = "", keep_item: bool = False) -> None:
    """Short bench for a slow channel (B_COL: 5 min): ONE tile (*tile*, 0 = 1001) exported
    by exportImagesFlattened (twice: 1st warms up), by the Export Manager at full size,
    512 and 512 in 8 bits, and from the nearest Bake Point above the channel (full size,
    512). Lists every Bake Point of the geo with its API and status. Answers: is 512 at
    export time faster, and is exporting the bake points fast?"""
    if mari is None:
        print("flux_bench_em : a lancer dans la console Python de Mari")
        return
    _out("=" * 70)
    _out(f"FLUX bench Export Manager, {_try('version', lambda: mari.app.version().string(), '?')}")
    geo = _try("geo courante", mari.geo.current)
    if geo is None:
        _out("aucune geo courante : ouvre le projet Mari a mesurer, puis relance flux_bench_em()")
        return
    _out(f"geo {geo.name()}")
    _try("api", _dump_api)
    depths = _try("depthList", mari.exports.depthList, []) or []
    byte = next((d for d in depths if "8" in str(d) or "byte" in str(d).lower()), "")
    all_bakes = _try("bake points", lambda: _bake_inventory(geo), []) or []
    results: list = []
    tiles = [tile]
    for channel in _channels(geo, channels):
        name = channel.name()
        try:
            _describe(geo, channel)
            f = fmt or ("tif" if (_try("depth", channel.depth, 8) or 8) <= 8 else "exr")
            _flat(channel, f, f"{name} flatten {f} tuile {1001 + tile} (chauffe)", results, tiles=tiles)
            _flat(channel, f, f"{name} flatten {f} tuile {1001 + tile}", results, tiles=tiles)
            _export_manager(geo, channel, f, 0, results, tiles, keep_item=keep_item)
            _export_manager(geo, channel, f, 512, results, tiles, keep_item=keep_item)
            if byte:
                _export_manager(geo, channel, "tif", 512, results, tiles, depth=byte, keep_item=keep_item)
            # 2026-09-26: a Bake Point at the end of every map. Export it directly:
            # its images are already computed when it is up to date.
            bakes = []
            node = _try("channelNode", channel.channelNode)
            if node is not None:
                _try("graphe", lambda: _upstream(node, bakes=bakes))
            if not bakes and node is not None:
                # "au bout de chaque map": the Bake Point may sit after the channel.
                after = [b for b in all_bakes if _try("feeds", lambda b=b: feeds(b, node), False)]
                bakes = after
                _out(f"  bake point(s) apres {name} : {[_node_name(b) for b in after] or 'aucun'}")
            else:
                _out(f"  bake point le plus proche avant {name} : {[_node_name(b) for b in bakes[:1]] or 'aucun'}")
            for bake in bakes[:1]:
                _export_manager(geo, channel, f, 0, results, tiles, keep_item=keep_item, source=bake)
                _export_manager(geo, channel, f, 512, results, tiles, keep_item=keep_item, source=bake)
        except Exception:  # noqa: BLE001
            _out(f"{name} : erreur inattendue\n{traceback.format_exc()}")
    _summary(results)


def flux_probe_nodes() -> None:
    """API needed for a custom "FLUX Export" node (2026-09-26): custom node
    registration (XML), node creation, node metadata (dropdowns), Mari resource paths
    and a small node XML shipped with Mari as a model. Read only."""
    if mari is None:
        print("flux_probe_nodes : a lancer dans la console Python de Mari")
        return
    import pydoc
    import sys
    _out("=" * 70)
    _out(f"FLUX sonde nodes custom, {_try('version', lambda: mari.app.version().string(), '?')}")
    keys = ("register", "custom", "xml", "node", "library")
    for mod_name in ("gl_render", "nodes", "system", "resources", "utils"):
        mod = getattr(mari, mod_name, None)
        if mod is None:
            _out(f"mari.{mod_name} : absent")
            continue
        names = [n for n in dir(mod) if not n.startswith("_")]
        _out(f"mari.{mod_name} : {names}")
        for n in names:
            if any(k in n.lower() for k in keys) and callable(getattr(mod, n, None)):
                text = _try(n, lambda n=n: pydoc.render_doc(getattr(mod, n), renderer=pydoc.plaintext), "") or ""
                _out(f"-- mari.{mod_name}.{n} :\n{text[:2500]}")
    geo = _try("geo courante", mari.geo.current)
    graph = _try("nodeGraph", geo.nodeGraph) if geo is not None else None
    if graph is not None:
        names = [n for n in dir(graph) if not n.startswith("_")]
        _out(f"NodeGraph methodes : {names}")
        for n in names:
            if n.lower().startswith("create") or "library" in n.lower():
                text = _try(n, lambda n=n: pydoc.render_doc(getattr(graph, n), renderer=pydoc.plaintext), "") or ""
                _out(f"-- NodeGraph.{n} :\n{text[:2500]}")
        nodes = _try("nodeList", lambda: list(graph.nodeList()), []) or []
        if nodes:
            node = nodes[0]
            _out(f"Node methodes ({type(node).__name__}) : {[n for n in dir(node) if not n.startswith('_')]}")
            for n in ("setMetadata", "setMetadataItemList", "setMetadataFlags", "setMetadataDisplayName",
                      "setMetadataEnabled", "metadataNames"):
                if hasattr(node, n):
                    text = _try(n, lambda n=n: pydoc.render_doc(getattr(node, n), renderer=pydoc.plaintext), "") or ""
                    _out(f"-- Node.{n} :\n{text[:2000]}")
            ids = {}
            for nd in nodes:
                ids[_node_type(nd)] = ids.get(_node_type(nd), 0) + 1
            _out(f"types de nodes du projet : {ids}")
    res = getattr(mari, "resources", None)
    if res is not None:
        for n in dir(res):
            if n.isupper():
                path = _try(n, lambda n=n: res.path(getattr(res, n)))
                if path:
                    _out(f"resources {n} : {path}")
    # A small node XML shipped with Mari, as a model for ours.
    base = os.path.dirname(sys.executable)
    found = []
    for root, _dirs, files in os.walk(os.path.dirname(base)):
        for f in files:
            if f.lower().endswith(".xml") and ("node" in root.lower() or "shader" in root.lower()):
                found.append(os.path.join(root, f))
        if len(found) > 400:
            break
    _out(f"{len(found)} XML de nodes sous {os.path.dirname(base)} ; dossiers : "
         f"{sorted({os.path.dirname(f) for f in found})[:15]}")
    small = sorted(found, key=lambda f: os.path.getsize(f))[:40]
    for f in small:
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if "<Node" in text and "Input" in text:
            _out(f"exemple {f} :\n{text[:4000]}")
            break
    _out(f"rapport : {REPORT_PATH}")
