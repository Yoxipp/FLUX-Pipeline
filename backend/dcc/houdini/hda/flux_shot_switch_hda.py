"""
FLUX - Houdini "FLUX Shot" HDA for Solaris (A5, 2026-09-18).

The shot selector of the sequence scene: one node that loads the stage of the chosen
shot (ADR 0020: casting, animation per character, layout, sequence light rig...) and
drives the scene from it:
  * menus: project, sequence, shot, version (LAST / vNNN);
  * the shot stage is sublayered; "Geometrie" shows the proxy or the render meshes;
  * frame range + fps of the shot applied to the timeline when the shot changes
    ("Suivre la plage du shot"), camera found in the stage (menu, auto = first one);
  * a Layer Break at the output: everything authored downstream (the shot lights) is
    a new layer. "Publier le light rig du shot" writes those layers (USD ROP, strip
    layers above layer breaks) to a temp file inside Houdini, then FLUX publishes it
    as SEQ_SHOT_LIGHT (vNNN + LAST) and regenerates the shot stage.
Several FLUX Shot nodes can sit side by side in one sequence scene (ADR 0023, the
template is made by the team): common lights upstream feed every shot (the node's
input), each shot has its own branch (its lights after its Layer Break, published with
"Publier le light rig du shot") and its own render ROP ("Creer le ROP du shot"), which
follows this node: frame range, camera, output ``render_picture``. "Rendre ce shot"
renders one shot, "Rendre la sequence" every FLUX Shot of the same sequence, one after
the other, each with its own range and camera.

2026-09-27: shown as "FLUX Shot Import" (the node type stays ``flux_shot``: the scenes
already made keep their nodes). The render buttons moved to FLUX Render, at the bottom of
the branch under the Render Settings (flux_render_hda.py); ``render_picture`` /
``render_rop`` stay hidden here so the scenes that read them keep working. New section
"Assets et variantes": every asset of the shot (on / off) and each of its variant sets
(shaders, geo / groom files, anim sub-task, ADR 0024), chosen per node; the inner
``apply_variants`` Python LOP authors the choices (self-contained), above the Layer Break (never in the
shot light publish).

Same bootstrap pattern as FLUX Anim: the HDA holds a few lines that fetch the real
module from GET /dcc/houdini/shot_switch/module, so a fix needs no HDA rebuild.
"""

from __future__ import annotations


from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_shot"
LABEL = "FLUX Shot Import"
# Rows of "Assets et variantes": one per asset (on / off) and per variant set of an asset.
MAX_VARIANT_ROWS = 96
# Pseudo variant set of a row that switches the asset itself on / off.
ACTIVE_ROW = "__active__"
# Output of the shot render (one folder per shot, beside the scene).
RENDER_PICTURE = '$HIP/render/`chs("seq")`_`chs("shot")`/`chs("seq")`_`chs("shot")`.$F4.exr'

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/shot_switch/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _dead_menu(*a, **kw): return ["", "FLUX offline"]
    for _n in ("menu_project", "menu_seq", "menu_shot", "menu_version", "menu_camera", "menu_variant"):
        globals()[_n] = _dead_menu
    def _offline(node, name):
        try:
            _load()
            globals()[name](node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis clique Resolve")
    def resolve_path(node): _offline(node, "resolve_path")
    def apply_frame_range(node): _offline(node, "apply_frame_range")
    def publish_light(node): _offline(node, "publish_light")
    def create_render_rop(node): _offline(node, "create_render_rop")
    def render_shot(node): _offline(node, "render_shot")
    def render_sequence(node): _offline(node, "render_sequence")
    def scan_variants(node): _offline(node, "scan_variants")
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Served by GET /dcc/houdini/shot_switch/module, exec()'d by the bootstrap (runs inside Houdini).
MODULE_FUNCTIONS: str = '''
import json, os, tempfile, threading, time, urllib.parse, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _get(path, **params):
    url = f"http://127.0.0.1:{_flux_port()}" + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())
    except Exception as exc:
        # "_offline": FLUX not reachable: never cached, never read as "no stage".
        return {"ok": False, "error": str(exc), "_offline": True}

def _post(path, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{_flux_port()}" + path,
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return {"ok": False, "error": json.loads(exc.read()).get("detail", str(exc))}
        except Exception:
            return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

_TTL = 30.0
_cache = {}

def _cached(key, fetch):
    """fetch() -> (data, ok). Only good answers are cached: an error is retried."""
    now = time.monotonic()
    if key in _cache and now < _cache[key][0]:
        return _cache[key][1]
    data, ok = fetch()
    if ok:
        _cache[key] = (now + _TTL, data)
    return data

def _fetch_shots(project):
    r = _get("/dcc/houdini/shot_switch/shots", project=project)
    return r.get("shots", []), not r.get("_offline")

def _pval(node, name):
    p = node.parm(name)
    return p.evalAsString() if p is not None else ""

def _set(node, name, value):
    p = node.parm(name)
    if p is not None:
        p.set(value)

def _status(node, msg):
    _set(node, "status_msg", msg)

def _flat(values):
    out = []
    for v in values:
        out += [v, v]
    return out

def _shots(node, fresh=False):
    project = _pval(node, "project")
    if not project:
        return []
    key = "shots:" + project
    if fresh:
        _cache.pop(key, None)
    # An empty list is never cached (2026-09-28: a sequence re-created a moment
    # before left the Shot menu on "-" while its shots existed): asked again next time.
    def _fetch():
        shots, ok = _fetch_shots(project)
        return shots, ok and bool(shots)
    return _cached(key, _fetch)

def _current(node):
    seq, shot = _pval(node, "seq"), _pval(node, "shot")
    return next((s for s in _shots(node) if s["seq"] == seq and s["shot"] == shot), None)

def menu_project(node):
    def _fetch():
        r = _get("/dcc/houdini/importer/tokens")
        return r.get("projects", []), not r.get("_offline")
    projects = _cached("projects", _fetch)
    return _flat(projects) if projects else ["", "FLUX injoignable ou aucun projet"]

def menu_seq(node):
    return _flat(sorted({s["seq"] for s in _shots(node)})) or ["", "aucun shot genere"]

def menu_shot(node):
    seq = _pval(node, "seq")
    return _flat(sorted(s["shot"] for s in _shots(node) if s["seq"] == seq)) or ["", "-"]

def menu_version(node):
    item = _current(node)
    return _flat(["LAST"] + list(reversed((item or {}).get("versions", []))))

def _stage_cameras(node):
    try:
        from pxr import UsdGeom
        stage = node.node("sublayer").stage()
        return [str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdGeom.Camera)]
    except Exception:
        return []

def menu_camera(node):
    cams = _stage_cameras(node)
    return _flat(cams) if cams else ["", "pas de camera (layout non publie)"]

def _reload(node):
    for inner in ("sublayer",):
        n = node.node(inner)
        btn = n.parm("reload") if n is not None else None
        if btn is not None:
            try:
                btn.pressButton()
            except Exception:
                pass

def apply_frame_range(node):
    """Timeline and fps of the scene = the shot's (frame range written on its stage)."""
    import hou
    try:
        start, end = int(node.evalParm("frame_rangex")), int(node.evalParm("frame_rangey"))
        fps = float(node.evalParm("fps"))
    except Exception:
        _status(node, "Plage illisible"); return
    if end < start:
        _status(node, "Pas de plage pour ce shot (Production)"); return
    if fps > 0 and abs(hou.fps() - fps) > 1e-6:
        hou.setFps(fps)
    hou.playbar.setFrameRange(start, end)
    hou.playbar.setPlaybackRange(start, end)
    hou.setFrame(start)

def resolve_path(node, opening=False):
    """Load the shot stage. *opening* (scene load): no timeline / fps / camera change and
    no forced cook: with several FLUX Shot the last one would silently win."""
    if not _pval(node, "project"):
        _status(node, "Choisis un projet"); return
    project = _pval(node, "project")
    shots, ok = _fetch_shots(project)
    if not ok:
        _status(node, "FLUX injoignable : stage actuel garde. Demarre FLUX puis clique Resolve"); return
    _cache["shots:" + project] = (time.monotonic() + _TTL, shots)
    item = _current(node)
    if item is None:
        _set(node, "resolved_path", "")
        _status(node, "Shot sans stage : genere-le depuis la page USD de FLUX"); return
    version = _pval(node, "version") or "LAST"
    if version != "LAST" and version not in (item.get("files") or {}):
        version = "LAST"                  # another shot picked: follow its LAST
        _set(node, "version", "LAST")
    path = item["last"] if version == "LAST" else item.get("files", {}).get(version, "")
    if not path:
        _set(node, "resolved_path", "")
        _status(node, "Version introuvable : " + version); return
    _set(node, "resolved_path", path.replace(chr(92), "/"))
    rng = item.get("range") or [1, 0]
    node.parmTuple("frame_range").set((int(rng[0]), int(rng[1])))
    _set(node, "fps", float(item.get("fps") or 24))
    _reload(node)
    if opening:
        _status(node, "Charge : %s %s %s" % (item["seq"], item["shot"], version)); return
    try:
        node.cook(force=True)
    except Exception:
        pass
    cams = _stage_cameras(node)
    auto = node.parm("camera_auto")
    if auto is None or auto.eval():
        _set(node, "camera", cams[0] if cams else "")
    follow = node.parm("follow_range")
    if follow is None or follow.eval():
        apply_frame_range(node)
    try:
        scan_variants(node, quiet=True)
    except Exception:
        pass
    msg = "OK  %s %s %s" % (item["seq"], item["shot"], version)
    if item.get("range"):
        msg += "  images %d-%d" % (int(rng[0]), int(rng[1]))
    msg += "  camera " + (_pval(node, "camera") or "aucune")
    _status(node, msg)

def refresh_from_flux(node, project, changed):
    """FLUX regenerated the stage of the *changed* [seq, shot] pairs (Production edit): follow
    it in the open scene. A pinned version is left alone, the camera never moves, and the
    timeline only follows when it still showed this node's old range (several FLUX Shot:
    no "last one wins"). Returns a short report or None when this node is not concerned."""
    import hou
    if _pval(node, "project") != project:
        return None
    key = [_pval(node, "seq").upper(), _pval(node, "shot").upper()]
    if key not in [[str(s).upper(), str(h).upper()] for s, h in changed]:
        return None
    _cache.pop("shots:" + project, None)
    if (_pval(node, "version") or "LAST") != "LAST":
        _status(node, "Stage regenere par FLUX : version epinglee gardee")
        return "pinned"
    try:
        old = (int(node.evalParm("frame_rangex")), int(node.evalParm("frame_rangey")))
    except Exception:
        old = None
    shots, ok = _fetch_shots(project)
    if not ok:
        _status(node, "FLUX injoignable : stage actuel garde"); return "offline"
    _cache["shots:" + project] = (time.monotonic() + _TTL, shots)
    item = _current(node)
    if item is None or not item.get("last"):
        return "missing"
    _set(node, "resolved_path", item["last"].replace(chr(92), "/"))
    rng = item.get("range") or [1, 0]
    node.parmTuple("frame_range").set((int(rng[0]), int(rng[1])))
    _set(node, "fps", float(item.get("fps") or 24))
    _reload(node)
    shown = tuple(int(round(v)) for v in hou.playbar.frameRange())
    follow = node.parm("follow_range")
    moved = bool(old) and shown == old and (follow is None or bool(follow.eval()))
    if moved:
        apply_frame_range(node)
    msg = "Mis a jour par FLUX : %s %s" % (item["seq"], item["shot"])
    if item.get("range"):
        msg += "  images %d-%d" % (int(rng[0]), int(rng[1]))
    _status(node, msg)
    return "timeline" if moved else "updated"

def _branch_end(node):
    """Last node of this shot's branch: follows single outputs, stops before a node that
    mixes several inputs (another shot, a merge) or a ROP. Several shots side by side
    each keep their own branch (ADR 0021, 0023, 0029)."""
    cur = node
    for _ in range(500):
        outs = [o for o in cur.outputs() if "rop" not in o.type().name().lower()]
        if len(outs) != 1 or len(outs[0].inputs()) > 1:
            return cur
        cur = outs[0]
    return cur

def _light_source(node):
    import hou
    path = _pval(node, "light_node")
    if path:
        n = hou.node(path)
        if n is not None:
            return n
    return _branch_end(node)

def _shot_tag(node):
    return "%s_%s" % (_pval(node, "seq"), _pval(node, "shot"))

def create_render_rop(node):
    """One USD Render ROP (Karma) per shot, following this node (range, camera, output)."""
    import hou
    if not (_pval(node, "seq") and _pval(node, "shot")):
        _status(node, "Choisis la sequence et le shot d'abord"); return
    # The whole branch (lights + render settings), not light_node: that one stops at the
    # lights so the light publish never carries the render settings.
    src = _branch_end(node)
    rop = hou.node(_pval(node, "render_rop")) if _pval(node, "render_rop") else None
    if rop is None:
        # Creating a render ROP in a live session crashed Houdini once (ADR 0021, 0029):
        # save first so nothing is lost.
        try:
            if hou.hipFile.hasUnsavedChanges() and not hou.hipFile.isNewFile():
                hou.hipFile.save()
        except Exception as exc:
            _status(node, "Sauvegarde impossible avant le ROP : %s" % exc); return
        out = hou.node("/out") or hou.node("/").createNode("ropnet", "out")
        rop = out.createNode("usdrender", "RENDER_" + _shot_tag(node))
    me = node.path()
    rop.parm("loppath").set(src.path())
    if rop.parm("renderer") is not None:
        rop.parm("renderer").set("BRAY_HdKarma")
    rop.parm("trange").set(1)
    rop.parm("f1").setExpression('ch("%s/frame_rangex")' % me, hou.exprLanguage.Hscript)
    rop.parm("f2").setExpression('ch("%s/frame_rangey")' % me, hou.exprLanguage.Hscript)
    if rop.parm("override_camera") is not None:
        rop.parm("override_camera").setExpression('chs("%s/camera")' % me, hou.exprLanguage.Hscript)
    rop.parm("outputimage").set('`chs("%s/render_picture")`' % me)
    _set(node, "render_rop", rop.path())
    _status(node, "ROP %s : rend %s" % (rop.path(), src.path()))

def _render(node):
    """Render one shot with its own ROP and range. "" when done, else why not."""
    import hou
    rop = hou.node(_pval(node, "render_rop")) if _pval(node, "render_rop") else None
    if rop is None:
        return "pas de ROP (bouton Creer le ROP du shot)"
    try:
        start, end = int(node.evalParm("frame_rangex")), int(node.evalParm("frame_rangey"))
    except Exception:
        return "plage illisible"
    if end < start:
        return "pas de plage (Production)"
    try:
        rop.render(frame_range=(start, end))
    except Exception as exc:
        return str(exc)
    return ""

def render_shot(node):
    err = _render(node)
    _status(node, ("Rendu %s termine" % _shot_tag(node)) if not err else "Rendu impossible : " + err)

def _sequence_shots(node):
    """Every FLUX Shot of the scene on the same project and sequence, in shot order."""
    same = [n for n in node.type().instances()
            if _pval(n, "project") == _pval(node, "project") and _pval(n, "seq") == _pval(node, "seq")]
    return sorted(same, key=lambda n: _pval(n, "shot"))

def render_sequence(node):
    """Each shot rendered on its own (its range, camera, lights): one failure never stops the others."""
    done, failed = [], []
    for shot in _sequence_shots(node):
        err = _render(shot)
        if err:
            failed.append("%s (%s)" % (_pval(shot, "shot"), err))
        else:
            done.append(_pval(shot, "shot"))
    msg = "Sequence %s : %d shot(s) rendu(s)" % (_pval(node, "seq"), len(done))
    if failed:
        msg += ", non rendus : " + ", ".join(failed)
    _status(node, msg)

def publish_light(node):
    """Write the layers authored after this node (the shot lights) and publish them."""
    import hou
    project, seq, shot = _pval(node, "project"), _pval(node, "seq"), _pval(node, "shot")
    if not (project and seq and shot):
        _status(node, "Choisis projet / sequence / shot d'abord"); return
    src = _light_source(node)
    if src is None or src.path() == node.path():
        _status(node, "Branche les lumieres apres ce node (ou remplis Light Node)"); return
    tmp_dir = tempfile.mkdtemp(prefix="flux_shot_light_")
    out = os.path.join(tmp_dir, "light.usda").replace(chr(92), "/")
    rop = node.parent().createNode("usd_rop", "__flux_light_export__")
    try:
        rop.parm("loppath").set(src.path())
        rop.parm("lopoutput").set(out)
        if rop.parm("striplayerbreaks") is not None:
            rop.parm("striplayerbreaks").set(1)
        if rop.parm("savestyle") is not None:
            rop.parm("savestyle").set("flattenimplicitlayers")
        rop.parm("execute").pressButton()
    finally:
        rop.destroy()
    if not os.path.isfile(out):
        _status(node, "Export des lumieres echoue"); return
    r = _post("/dcc/houdini/shot-light/publish", {"project": project, "seq": seq, "shot": shot, "file": out})
    try:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass
    if not r.get("ok"):
        _status(node, "Publish echoue : %s" % r.get("error", "?")); return
    msg = "Light rig publie : %s %s (stage %s)" % (r.get("base", ""), r.get("version", ""),
                                                  r.get("stage") or "inchange")
    if r.get("stage"):
        # The stage now sublayers the new light rig: reload it (version LAST).
        _cache.pop("shots:" + project, None)
        resolve_path(node, opening=True)
    warns = r.get("warnings") or []
    _status(node, msg + ("  |  " + " ; ".join(warns) if warns else ""))

# ── Assets et variantes (2026-09-27) ────────────────────────────────────
# Rows = [[prim, variant set]] in the hidden "var_rows_json"; row i shows its name in
# "var_name<i>" and its choice in "var_sel<i>" ("" = keep the stage's choice). A row
# whose set is ACTIVE_ROW switches the asset on / off.

def _var_rows(node):
    try:
        return json.loads(_pval(node, "var_rows_json") or "[]")
    except Exception:
        return []

def _source_stage(node):
    """The shot stage as loaded, before this node's own choices."""
    try:
        return node.node("sublayer").stage()
    except Exception:
        return None

def _asset_prims(stage):
    """Casting of the shot: the models under /assets, /sets, /crowd (not inside them)."""
    from pxr import Usd
    out = []
    for root in ("/assets", "/sets", "/crowd"):
        top = stage.GetPrimAtPath(root)
        if not top:
            continue
        todo = list(top.GetAllChildren())
        while todo:
            prim = todo.pop(0)
            kind = Usd.ModelAPI(prim).GetKind()
            if kind in ("component", "assembly", "subcomponent") or prim.GetVariantSets().GetNames():
                out.append(prim)
            elif prim.GetPath().pathElementCount < 4:
                todo.extend(prim.GetAllChildren())
    return out

def scan_variants(node, quiet=False):
    """List the assets of the shot and their variant sets. A choice already made on a row
    (same asset, same set) is kept."""
    stage = _source_stage(node)
    if stage is None:
        if not quiet:
            _status(node, "Pas de stage charge : Resolve d'abord")
        return
    old = {}
    for i, row in enumerate(_var_rows(node)):
        sel = _pval(node, "var_sel%d" % (i + 1))
        if sel:
            old[tuple(row)] = sel
    rows = []
    for prim in _asset_prims(stage):
        path = str(prim.GetPath())
        rows.append([path, ACTIVE_ROW])
        rows += [[path, name] for name in prim.GetVariantSets().GetNames()]
    cut = len(rows) > MAX_VARIANT_ROWS
    rows = rows[:MAX_VARIANT_ROWS]
    _set(node, "var_rows_json", json.dumps(rows))
    for i in range(1, MAX_VARIANT_ROWS + 1):
        if i <= len(rows):
            path, vset = rows[i - 1]
            name = path.rsplit("/", 1)[-1]
            _set(node, "var_name%d" % i, name + "  |  " + ("actif" if vset == ACTIVE_ROW else vset))
            _set(node, "var_sel%d" % i, old.get((path, vset), ""))
        else:
            _set(node, "var_name%d" % i, "")
            _set(node, "var_sel%d" % i, "")
    if not quiet:
        n_assets = sum(1 for r in rows if r[1] == ACTIVE_ROW)
        msg = "%d asset(s), %d variante(s)" % (n_assets, len(rows) - n_assets)
        _status(node, msg + ("  (liste coupee a %d lignes)" % MAX_VARIANT_ROWS if cut else ""))

def menu_variant(node, parm=None):
    """Choices of a row: "" (the stage's) then on / off or the variants of its set."""
    try:
        idx = int("".join(c for c in parm.name() if c.isdigit()))
        path, vset = _var_rows(node)[idx - 1]
    except Exception:
        return ["", "-"]
    stage = _source_stage(node)
    prim = stage.GetPrimAtPath(path) if stage is not None else None
    if vset == ACTIVE_ROW:
        cur = "on" if (prim is None or prim.IsActive()) else "off"
        return ["", "(stage : %s)" % cur, "on", "actif", "off", "desactive"]
    if not prim:
        return ["", "(asset absent)"]
    vs = prim.GetVariantSets().GetVariantSet(vset)
    out = ["", "(stage : %s)" % (vs.GetVariantSelection() or "-")]
    for name in vs.GetVariantNames():
        out += [name, name]
    return out

def on_created(node):
    threading.Thread(target=lambda: _shots(node), daemon=True).start()

def on_loaded(node):
    resolve_path(node, opening=True)
'''

# The served module reads the same constants as the parm interface.
MODULE_FUNCTIONS = f"ACTIVE_ROW = {ACTIVE_ROW!r}\nMAX_VARIANT_ROWS = {MAX_VARIANT_ROWS}\n" + MODULE_FUNCTIONS

# Body of the inner apply_variants Python LOP: the choices of "Assets et variantes",
# authored on the active layer (above the Layer Break: never in the shot light publish).
# Self-contained, no FLUX call: a render with FLUX closed keeps the choices.
APPLY_VARIANTS = f"""import json
node = hou.pwd()
top = node.parent()
stage = node.editableStage()
# Contenu (2026-09-28): one import per backdrop of the render scene, ENV = decors,
# CHAR = characters. The other top-level prims are deactivated.
_keep = {{1: ("/sets",), 2: ("/assets", "/crowd")}}.get(int(top.evalParm("content") or 0))
if _keep:
    for _root in stage.GetPseudoRoot().GetAllChildren():
        _path = str(_root.GetPath())
        if _path not in _keep and _path != "/HoudiniLayerInfo":
            _root.SetActive(False)
try:
    rows = json.loads(top.evalParm("var_rows_json") or "[]")
except Exception:
    rows = []
for i, (path, vset) in enumerate(rows):
    p = top.parm("var_sel%d" % (i + 1))
    sel = p.evalAsString() if p is not None else ""
    if not sel:
        continue
    prim = stage.GetPrimAtPath(path)
    if not prim:
        continue
    if vset == {ACTIVE_ROW!r}:
        prim.SetActive(sel == "on")
        continue
    sets = prim.GetVariantSets()
    if sets.HasVariantSet(vset):
        sets.GetVariantSet(vset).SetVariantSelection(sel)
"""


def _build_code(hda_path: str) -> str:
    from dcc.houdini.hda.preserve_instances import RESTORE, snapshot

    _snapshot = snapshot('hou.lopNodeTypeCategory()', NODE_NAME).replace("{{", "{").replace("}}", "}")
    _restore = RESTORE
    from dcc.houdini.hda.hda_common import FINALIZE as _finalize, ICON_PATH as icon_path

    return f'''
import hou
{_snapshot}

_HDA_PATH = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NAME = {NODE_NAME!r}
_PY = hou.scriptLanguage.Python
_PM_CODE = {BOOTSTRAP!r}
_CB = "hou.phm().resolve_path(kwargs['node'])"

def _menu(name, label, default, fn, help_txt, cb=_CB):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    if cb:
        t.setScriptCallback(cb)
        t.setScriptCallbackLanguage(_PY)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Projet", "", "menu_project", "FLUX project"))
_ptg.append(_menu("seq", "Sequence", "", "menu_seq", "Sequence of the scene"))
_ptg.append(_menu("shot", "Shot", "", "menu_shot", "Shot loaded in the scene"))
_ptg.append(_menu("version", "Version", "LAST", "menu_version", "LAST follows new publishes, vNNN is frozen"))
_ptg.append(hou.MenuParmTemplate("content", "Contenu", ("all", "sets", "assets"),
                                 menu_labels=("Tout le shot", "Decors (/sets)", "Persos (/assets, /crowd)"),
                                 default_value=0,
                                 help="Tout, or only the decors / only the characters of the shot stage"))
_ptg.append(hou.MenuParmTemplate("geo_display", "Geometrie", ("proxy", "render"),
                                 menu_labels=("Proxy (leger)", "Geo complete"), default_value=0,
                                 help="Proxy: purpose=proxy meshes in the viewport. Geo complete: render meshes."))
_ptg.append(hou.SeparatorParmTemplate("sep_time"))
_follow = hou.ToggleParmTemplate("follow_range", "Suivre la plage du shot", default_value=True,
                                 help="Changing the shot sets the timeline and fps of the scene")
_ptg.append(_follow)
# Read-only: filled by Resolve from the shot stage (Production), an edit would be lost.
_ptg.append(hou.ToggleParmTemplate("range_locked", "locked", default_value=True, is_hidden=True))
_rng = hou.IntParmTemplate("frame_range", "Plage", 2, default_value=(1, 0),
                           help="Plage du shot (Production), lue dans son stage")
_rng.setConditional(hou.parmCondType.DisableWhen, "{{ range_locked == 1 }}")
_ptg.append(_rng)
_fps = hou.FloatParmTemplate("fps", "FPS", 1, default_value=(24.0,), help="FPS du shot, lu dans son stage")
_fps.setConditional(hou.parmCondType.DisableWhen, "{{ range_locked == 1 }}")
_ptg.append(_fps)
_ptg.append(hou.ButtonParmTemplate("btn_frame_range", "Appliquer la plage",
                                   script_callback="hou.phm().apply_frame_range(kwargs['node'])",
                                   script_callback_language=_PY))
_cauto = hou.ToggleParmTemplate("camera_auto", "Auto", default_value=True,
                                help="Camera = the first camera of the shot stage (layout)")
_cauto.setJoinWithNext(True)
_ptg.append(_cauto)
_cam = _menu("camera", "Camera", "", "menu_camera", "Render camera of the shot", cb=None)
_cam.setConditional(hou.parmCondType.DisableWhen, "{{ camera_auto == 1 }}")
_ptg.append(_cam)
_ptg.append(hou.SeparatorParmTemplate("sep_light"))
_ptg.append(hou.StringParmTemplate("light_node", "Light Node", 1, default_value=("",),
                                   string_type=hou.stringParmType.NodeReference,
                                   help="LOP holding the shot lights (empty = end of this shot's branch)"))
_ptg.append(hou.ButtonParmTemplate("btn_publish_light", "Publier le light rig du shot",
                                   script_callback="hou.phm().publish_light(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Publishes the layers authored after this node as SEQ_SHOT_LIGHT"))
# Rendering moved to FLUX Render (under the Render Settings). Kept hidden: scenes made
# before read render_picture / render_rop by expression.
_ptg.append(hou.StringParmTemplate("render_picture", "Images du shot", 1, default_value=({RENDER_PICTURE!r},),
                                   string_type=hou.stringParmType.FileReference, is_hidden=True))
_ptg.append(hou.StringParmTemplate("render_rop", "ROP du shot", 1, default_value=("",),
                                   string_type=hou.stringParmType.NodeReference, is_hidden=True))
# Assets et variantes: one row per asset (on / off) and per variant set of an asset.
_vf = hou.FolderParmTemplate("fold_variants", "Assets et variantes", folder_type=hou.folderType.Collapsible)
_vf.addParmTemplate(hou.ButtonParmTemplate("btn_scan_variants", "Lister les assets et variantes",
                                           script_callback="hou.phm().scan_variants(kwargs['node'])",
                                           script_callback_language=_PY,
                                           help="Re-read the assets of the shot stage and their variant sets"))
_vf.addParmTemplate(hou.StringParmTemplate("var_rows_json", "rows", 1, default_value=("[]",), is_hidden=True))
for _i in range(1, {MAX_VARIANT_ROWS} + 1):
    _hide = '{{ var_name%d == "" }}' % _i
    _nm = hou.StringParmTemplate("var_name%d" % _i, "", 1, default_value=("",), is_label_hidden=True)
    _nm.setConditional(hou.parmCondType.DisableWhen, '{{ var_name%d != "~" }}' % _i)
    _nm.setConditional(hou.parmCondType.HideWhen, _hide)
    _nm.setJoinWithNext(True)
    _vf.addParmTemplate(_nm)
    _sel = hou.StringParmTemplate("var_sel%d" % _i, "", 1, default_value=("",), is_label_hidden=True,
                                  menu_type=hou.menuType.Normal)
    _sel.setItemGeneratorScript("hou.phm().menu_variant(kwargs['node'], kwargs['parm'])")
    _sel.setItemGeneratorScriptLanguage(_PY)
    _sel.setConditional(hou.parmCondType.HideWhen, _hide)
    _vf.addParmTemplate(_sel)
_ptg.append(_vf)
_ptg.append(hou.SeparatorParmTemplate("sep_resolved"))
_ptg.append(hou.StringParmTemplate("resolved_path", "Fichier charge", 1, default_value=("",)))
_ptg.append(hou.ButtonParmTemplate("btn_resolve", "Resolve / Recharger", script_callback=_CB,
                                   script_callback_language=_PY,
                                   help="Re-read the shot stage from disk"))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_shot_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_shot_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
_subl = _sub.createNode("sublayer", "sublayer")
_subl.setInput(0, _sub.indirectInputs()[0])
_subl.parm("filepath1").setExpression('chs("../resolved_path")', hou.exprLanguage.Hscript)
# The artist's choices of "Assets et variantes" (on / off, variant selections).
_apply = _sub.createNode("pythonscript", "apply_variants")
_apply.setInput(0, _subl)
_apply.parm("python").set({APPLY_VARIANTS!r})
_full = _sub.createNode("configureprimitive", "show_render_geo")
_full.setInput(0, _apply)
_full.parm("primpattern").set("/assets/**/geo/render/** /sets/**/geo/render/** /crowd/**/geo/render/**")
_full.parm("setpurpose").set(1)
_full.parm("purpose").set("default")
_hide = _sub.createNode("configureprimitive", "hide_proxy")
_hide.setInput(0, _full)
_hide.parm("primpattern").set("/assets/**/geo/proxy /sets/**/geo/proxy /crowd/**/geo/proxy")
# Grooms (ADR 0026): "Geo complete" shows the full curves, hides the thinned "*_proxy".
_gfull = _sub.createNode("configureprimitive", "show_full_groom")
_gfull.setInput(0, _hide)
_gfull.parm("primpattern").set("/assets/**/groom/** ^/assets/**/groom/**/*_proxy")
_gfull.parm("setpurpose").set(1)
_gfull.parm("purpose").set("default")
_ghide = _sub.createNode("configureprimitive", "hide_groom_proxy")
_ghide.setInput(0, _gfull)
_ghide.parm("primpattern").set("/assets/**/groom/**/*_proxy")
_ghide.parm("setvisibility").set(1)
_ghide.parm("visibility").set("invisible")
_hide.parm("setvisibility").set(1)
_hide.parm("visibility").set("invisible")
_sw = _sub.createNode("switch", "geo_display")
_sw.setInput(0, _apply)
_sw.setInput(1, _ghide)
_sw.parm("input").setExpression('ch("../geo_display")', hou.exprLanguage.Hscript)
# Everything authored after this node is a new layer: the shot light rig publish.
_lb = _sub.createNode("layerbreak", "layerbreak")
_lb.setInput(0, _sw)
# Decors / Persos (a branch of the render scene, merged then grafted): no Layer Break, a
# merge strips every layer above one and the branch came out empty (2026-09-28).
_lbsw = _sub.createNode("switch", "layer_break_if_all")
_lbsw.setInput(0, _lb)
_lbsw.setInput(1, _sw)
_lbsw.parm("input").setExpression('ch("../content") > 0', hou.exprLanguage.Hscript)
_out.setInput(0, _lbsw)
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=0, max_num_inputs=1, version="1.0")
{_finalize}
{_restore}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Shot LOP HDA in the running Houdini."""
    log.info("Building FLUX Shot HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Shot HDA built: %s", hda_path)
    else:
        log.error("FLUX Shot HDA build failed: %s", resp.get("error"))
    return resp
