"""
FLUX - Houdini "FLUX Anim" HDA for Solaris (2026-09-18, v2 2026-09-26).

Plugged after a FLUX Import / FLUX Shot (anything that puts characters on the stage),
it applies animations to SEVERAL characters at once:
  * one row per character: the animation (a shot animation SEQ_SHOT_ANIM_<NAME> or an
    asset clip CLASS_ANIM_<NAME>_<CLIP>), its version (LAST / vNNN) and the prim that
    receives it (auto: the character's prim in the input);
  * "Persos du plan" fills one row per animation published in the chosen sequence / shot;
  * optional rotation noise (amplitude in degrees, speed, seed), baked per frame, its own
    per character (the crowd's noise, root joint left alone);
  * frame range + fps of the scene follow the animations (toggle "Plage auto");
  * each row says what it plays: joints, smooth / step, root motion, range, and whether
    the character's skeleton knows the animated joints.
The backend writes one layer ($HIP/flux_anim/<node>_<stamp>.usda, POST
/dcc/houdini/anim/build) that the inner Sublayer LOP puts on the input.

Same bootstrap pattern as the importer: the HDA holds a few lines that fetch the real
module from GET /dcc/houdini/anim/module, so fixing the module needs no HDA rebuild.
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_anim"
LABEL = "FLUX Anim"

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/anim/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _dead_menu(*a, **kw): return ["", "FLUX offline"]
    for _n in ("menu_project", "menu_seq", "menu_shot", "menu_anim", "menu_version",
               "menu_target"):
        globals()[_n] = _dead_menu
    def _offline(fn_name, node):
        try:
            _load()
            globals()[fn_name](node)
        except Exception:
            node = node["node"] if isinstance(node, dict) else node
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis clique Resolve")
    def resolve_path(node): _offline("resolve_path", node)
    def fill_from_shot(node): _offline("fill_from_shot", node)
    def on_row_change(kwargs): _offline("on_row_change", kwargs)
    def apply_frame_range(node): _offline("apply_frame_range", node)
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Served by GET /dcc/houdini/anim/module, exec()'d by the bootstrap (runs inside Houdini).
MODULE_FUNCTIONS: str = '''
import json, os, re, threading, time, urllib.parse, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _get(path, _timeout=5, **params):
    url = f"http://127.0.0.1:{_flux_port()}" + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    try:
        with urllib.request.urlopen(url, timeout=_timeout) as r:
            return json.loads(r.read())
    except Exception as exc:
        # "_offline": FLUX not reachable (not started, busy): never cached, never read
        # as "nothing published".
        return {"ok": False, "error": str(exc), "_offline": True}

def _post(path, payload, _timeout=120):
    req = urllib.request.Request(f"http://127.0.0.1:{_flux_port()}" + path,
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_timeout) as r:
            return json.loads(r.read())
    except Exception as exc:
        return {"ok": False, "error": str(exc), "_offline": True}

_TTL = 30.0
_cache = {}

def _cached(key, fetch):
    # fetch() -> (data, ok). Only good answers are cached: an error is retried.
    now = time.monotonic()
    if key in _cache and now < _cache[key][0]:
        return _cache[key][1]
    data, ok = fetch()
    if ok:
        _cache[key] = (now + _TTL, data)
    return data

def _fetch_items(project):
    r = _get("/dcc/houdini/anim/publishes", _timeout=20, project=project)
    return r.get("items", []), not r.get("_offline")

def _node_of(k):
    return k["node"] if isinstance(k, dict) else k

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

def _row(kwargs):
    # Multiparm row of a menu / callback: its index, else the digits ending the parm name.
    i = kwargs.get("script_multiparm_index")
    if i not in (None, ""):
        return int(i)
    parm = kwargs.get("parm")
    m = re.search(r"(\\d+)$", parm.name()) if parm is not None else None
    return int(m.group(1)) if m else 1

def _items(node, fresh=False):
    project = _pval(node, "project")
    if not project:
        return []
    key = "anims:" + project
    if fresh:
        _cache.pop(key, None)
    return _cached(key, lambda: _fetch_items(project))

def _shot_items(node):
    items = [i for i in _items(node) if i.get("kind", "shot") == "shot"]
    for f in ("seq", "shot"):
        v = _pval(node, f)
        if v:
            items = [i for i in items if i.get(f) == v]
    return items

def _by_key(node, key):
    return next((i for i in _items(node) if i.get("key") == key), None)

def menu_project(k):
    def _fetch():
        r = _get("/dcc/houdini/importer/tokens")
        return r.get("projects", []), not r.get("_offline")
    projects = _cached("projects", _fetch)
    return _flat(projects) if projects else ["", "FLUX injoignable ou aucun projet"]

def menu_seq(k):
    node = _node_of(k)
    seqs = sorted({i["seq"] for i in _items(node) if i.get("kind", "shot") == "shot"})
    return ["", "(toutes)"] + _flat(seqs)

def menu_shot(k):
    node = _node_of(k)
    seq = _pval(node, "seq")
    shots = sorted({i["shot"] for i in _items(node) if i.get("kind", "shot") == "shot"
                    and (not seq or i.get("seq") == seq)})
    return ["", "(tous)"] + _flat(shots)

def menu_anim(k):
    node = _node_of(k)
    out = ["", "(choisir une anim)"]
    for it in _shot_items(node):
        out += [it["key"], it.get("label") or it["key"]]
    for it in _items(node):
        if it.get("kind") == "clip":
            out += [it["key"], it.get("label") or it["key"]]
    return out

def menu_version(k):
    node = _node_of(k)
    item = _by_key(node, _pval(node, "anim_key%d" % _row(k)))
    return _flat(["LAST"] + list((item or {}).get("versions", {})))

def _input_stage(node):
    ins = node.inputs()
    try:
        return ins[0].stage() if ins and ins[0] is not None else None
    except Exception:
        return None

def _asset_prims(stage):
    # Character / asset prims of the input: components and SkelRoots, top-most only.
    out = []
    if stage is None:
        return out
    from pxr import Usd, UsdSkel
    it = iter(Usd.PrimRange(stage.GetPseudoRoot()))
    for prim in it:
        if prim.IsPseudoRoot():
            continue
        if prim.IsA(UsdSkel.Root) or Usd.ModelAPI(prim).GetKind() == "component":
            out.append(str(prim.GetPath()))
            it.PruneChildren()
    return out

def menu_target(k):
    prims = _asset_prims(_input_stage(_node_of(k)))
    return (["", "(aucune)"] + _flat(prims)) if prims else ["", "rien en entree"]

def _auto_target(prims, item, taken):
    # Casting prim of the animated character in the input (DINGO_02 -> .../DINGO_02,
    # DINGO -> .../DINGO or .../DINGO_01), not already used by another row, or "":
    # never a made-up path (the reference would create a ghost prim). A clip plays on
    # the first free instance of its asset.
    char = item.get("character") or ""
    name = item.get("name") or ""
    for w in [w for w in (char, name, name + "_01") if w]:
        for p in prims:
            if p.rsplit("/", 1)[-1] == w and p not in taken:
                return p
    if item.get("kind") == "clip" and name:
        for p in prims:
            leaf = p.rsplit("/", 1)[-1]
            if (leaf == name or re.match(re.escape(name) + r"_\\d+$", leaf)) and p not in taken:
                return p
    return ""

def _reload(node):
    sub = node.node("anim_layer")
    btn = sub.parm("reload") if sub is not None else None
    if btn is not None:
        try:
            btn.pressButton()
        except Exception:
            pass

def _check(node, target):
    # Does the animation drive the target's skeleton? "" when fine, else why not.
    try:
        from pxr import Usd, UsdSkel
        stage = node.stage()
        prim = stage.GetPrimAtPath(target) if stage is not None else None
        if not prim:
            return "prim absent"
        cache = UsdSkel.Cache()
        if prim.IsA(UsdSkel.Root):
            cache.Populate(UsdSkel.Root(prim), Usd.PrimDefaultPredicate)
        for p in Usd.PrimRange(prim):
            if p.IsA(UsdSkel.Skeleton):
                q = cache.GetSkelQuery(UsdSkel.Skeleton(p))
                if not (q and q.GetAnimQuery()):
                    return "squelette pas anime"
                order = list(q.GetAnimQuery().GetJointOrder())
                joints = set(UsdSkel.Skeleton(p).GetJointsAttr().Get() or [])
                missing = [j for j in order if j not in joints]
                if missing:
                    return "%d joint(s) inconnus du rig : %s" % (len(missing), ", ".join(missing[:3]))
                return ""
        return "pas de squelette (publie le RIG)"
    except Exception as exc:
        return "verification impossible : %s" % exc

def _info_text(r):
    info = r.get("info") or {}
    if r.get("error") and not info.get("joints"):
        return "ERREUR : " + r["error"]
    parts = ["%d joints" % info.get("joints", 0), info.get("interpolation", "smooth"),
             "root motion" if info.get("root_motion") else "sur place",
             "%d-%d @ %g fps" % (info.get("start", 0), info.get("end", 0), info.get("fps", 24))]
    if r.get("noise"):
        parts.append("noise")
    text = "  ".join(parts)
    if r.get("error"):
        text += "  (" + r["error"] + ")"
    return text

def _layer_out(node):
    import hou
    hip = hou.expandString("$HIP") or hou.expandString("$HOUDINI_TEMP_DIR")
    folder = os.path.join(hip, "flux_anim")
    # A new file per build: Houdini keeps a layer it already read under the same path.
    return os.path.join(folder, "%s_%d.usda" % (node.name(), int(time.time() * 1000))).replace(chr(92), "/")

def _json(text):
    try:
        return json.loads(text) if text else None
    except Exception:
        return None

def _apply_range(node, rng):
    import hou
    start, end, fps = int(rng["start"]), int(rng["end"]), float(rng.get("fps") or 24.0)
    if abs(hou.fps() - fps) > 1e-6:
        hou.setFps(fps)
    hou.playbar.setFrameRange(start, end)
    hou.playbar.setPlaybackRange(start, end)
    return "images %d-%d a %g fps" % (start, end, fps)

def apply_frame_range(node):
    # Button "Appliquer la plage": playbar range + fps = those of the animations.
    node = _node_of(node)
    rng = _json(_pval(node, "anim_range"))
    if not rng:
        _status(node, "Pas de plage : clique Resolve d'abord"); return
    _status(node, "Plage appliquee : " + _apply_range(node, rng))

def fill_from_shot(node):
    # One row per animation published in the chosen sequence / shot.
    node = _node_of(node)
    _items(node, fresh=True)
    if not _pval(node, "seq") or not _pval(node, "shot"):
        _status(node, "Choisis la sequence et le shot"); return
    rows = _shot_items(node)
    if not rows:
        _status(node, "Aucune anim publiee dans ce plan"); return
    _set(node, "anims", len(rows))
    for i, it in enumerate(rows, 1):
        _set(node, "anim_on%d" % i, 1)
        _set(node, "anim_key%d" % i, it["key"])
        _set(node, "anim_version%d" % i, "LAST")
        _set(node, "target_auto%d" % i, 1)
    resolve_path(node)

def on_row_change(kwargs):
    resolve_path(kwargs["node"])

def resolve_path(node, check=True):
    node = _node_of(node)
    project = _pval(node, "project")
    if not project:
        _status(node, "Choisis un projet"); return
    _cache.pop("anims:" + project, None)
    items, ok = _fetch_items(project)
    if not ok:
        # Keep the current layer: the scene stays as it was until FLUX answers again.
        _status(node, "FLUX injoignable : couche actuelle gardee. Demarre FLUX puis clique Resolve"); return
    _cache["anims:" + project] = (time.monotonic() + _TTL, items)
    prims = _asset_prims(_input_stage(node))
    count = node.parm("anims")
    n = count.eval() if count is not None else 0
    rows, where, taken = [], [], []
    for i in range(1, n + 1):
        key = _pval(node, "anim_key%d" % i)
        if not key or not node.parm("anim_on%d" % i).eval():
            _set(node, "anim_info%d" % i, "" if key else "choisis une anim")
            continue
        item = _by_key(node, key)
        if item is None:
            _set(node, "anim_info%d" % i, "ERREUR : anim plus publiee (" + key + ")")
            continue
        version = _pval(node, "anim_version%d" % i) or "LAST"
        if version != "LAST" and version not in (item.get("versions") or {}):
            version = "LAST"            # another anim was picked: follow its LAST
            _set(node, "anim_version%d" % i, "LAST")
        target = _pval(node, "target_prim%d" % i)
        if node.parm("target_auto%d" % i).eval():
            target = _auto_target(prims, item, taken)
            _set(node, "target_prim%d" % i, target)
        if not target:
            _set(node, "anim_info%d" % i, "ERREUR : aucun perso %s dans l'entree (branche le FLUX Import)"
                 % (item.get("character") or item.get("name") or "?"))
            continue
        taken.append(target)
        rows.append({"key": key, "version": version, "target": target})
        where.append(i)
    noise = None
    amp = node.parm("noise_amp")
    if amp is not None and amp.eval() > 0:
        noise = {"amplitude": amp.eval(), "frequency": node.parm("noise_freq").eval(),
                 "seed": node.parm("noise_seed").eval()}
    old = _pval(node, "layer_path")
    r = _post("/dcc/houdini/anim/build", {"project": project, "out": _layer_out(node),
                                          "rows": rows, "noise": noise})
    if not r.get("ok"):
        _status(node, "Echec : " + str(r.get("error") or r.get("detail") or "?")); return
    _set(node, "layer_path", r["layer"])
    _set(node, "anim_range", json.dumps(r.get("range") or {}))
    if old and old != r["layer"] and os.path.basename(os.path.dirname(old)) == "flux_anim":
        try:
            os.remove(old)
        except OSError:
            pass
    _reload(node)
    if check:
        try:
            node.cook(force=True)
        except Exception:
            pass
    bad = 0
    for i, res in zip(where, r.get("rows", [])):
        text = _info_text(res)
        if check and not res.get("error"):
            why = _check(node, res.get("target", ""))
            if why:
                text = "ATTENTION : " + why + "  |  " + text
        if text.startswith(("ERREUR", "ATTENTION")):
            bad += 1
        _set(node, "anim_info%d" % i, text)
    msg = "%d anim(s) appliquee(s)" % (len(rows) - bad)
    if bad:
        msg += ", %d a verifier" % bad
    rng = r.get("range")
    auto = node.parm("auto_range")
    if rng and (auto is None or auto.eval()):
        msg += "  |  " + _apply_range(node, rng)
    _status(node, msg)

def on_created(node):
    threading.Thread(target=lambda: _items(node), daemon=True).start()

def on_loaded(node):
    # No forced cook while a scene opens (slow with several nodes): Resolve checks.
    resolve_path(node, check=False)
'''


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
_ROW_CB = "hou.phm().on_row_change(kwargs)"

def _menu(name, label, default, fn, help_txt):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    t.setScriptCallback(_CB)
    t.setScriptCallbackLanguage(_PY)
    return t

def _row_menu(name, label, default, fn, help_txt):
    # Menu inside the multiparm: the generator gets kwargs (the row comes from the parm).
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs)")
    t.setItemGeneratorScriptLanguage(_PY)
    t.setScriptCallback(_ROW_CB)
    t.setScriptCallbackLanguage(_PY)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Projet", "", "menu_project", "FLUX project"))
_ptg.append(_menu("seq", "Sequence", "", "menu_seq", "SEQ token (filters the shot animations)"))
_ptg.append(_menu("shot", "Shot", "", "menu_shot", "SHOT token (filters the shot animations)"))
_ptg.append(hou.ButtonParmTemplate("btn_fill", "Persos du plan",
                                   script_callback="hou.phm().fill_from_shot(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="One row per animation published in this sequence / shot"))

# One row per character: animation, version, target prim, what it plays.
_rows = hou.FolderParmTemplate("anims", "Anims", folder_type=hou.folderType.MultiparmBlock,
                               default_value=1)
_rows.setScriptCallback(_ROW_CB)
_rows.setScriptCallbackLanguage(_PY)
_on = hou.ToggleParmTemplate("anim_on#", "Actif", default_value=True,
                             script_callback=_ROW_CB, script_callback_language=_PY)
_on.setJoinWithNext(True)
_rows.addParmTemplate(_on)
_rows.addParmTemplate(_row_menu("anim_key#", "Anim", "", "menu_anim",
                                "Shot animation (PLAN) or asset clip (CLIP)"))
_rows.addParmTemplate(_row_menu("anim_version#", "Version", "LAST", "menu_version",
                                "LAST follows new publishes, vNNN is frozen"))
_auto = hou.ToggleParmTemplate("target_auto#", "Auto", default_value=True,
                               script_callback=_ROW_CB, script_callback_language=_PY,
                               help="Target = the character's prim found in the input")
_auto.setJoinWithNext(True)
_rows.addParmTemplate(_auto)
_tgt = _row_menu("target_prim#", "Prim cible", "", "menu_target", "Prim that receives the animation")
_tgt.setConditional(hou.parmCondType.DisableWhen, "{{ target_auto# == 1 }}")
_rows.addParmTemplate(_tgt)
_rows.addParmTemplate(hou.StringParmTemplate("anim_info#", "Infos", 1, default_value=("",),
                                             help="Joints, smooth / step, root motion, range, rig check"))
_ptg.append(_rows)

# Rotation noise on top of the animations, its own per character.
_nf = hou.FolderParmTemplate("noise_folder", "Noise des rotations", folder_type=hou.folderType.Collapsible)
_nf.addParmTemplate(hou.FloatParmTemplate("noise_amp", "Amplitude (deg)", 1, default_value=(0.0,),
                                          min=0.0, max=30.0, script_callback=_CB, script_callback_language=_PY,
                                          help="0 = no noise. A rotation per joint (root excluded), its own per character"))
_nf.addParmTemplate(hou.FloatParmTemplate("noise_freq", "Vitesse (Hz)", 1, default_value=(0.5,),
                                          min=0.0, max=5.0, script_callback=_CB, script_callback_language=_PY,
                                          help="Cycles per second; 0 = a still offset"))
_nf.addParmTemplate(hou.IntParmTemplate("noise_seed", "Graine", 1, default_value=(1,),
                                        min=0, max=100, script_callback=_CB, script_callback_language=_PY))
_ptg.append(_nf)

_ptg.append(hou.SeparatorParmTemplate("sep_resolved"))
_ptg.append(hou.ToggleParmTemplate("auto_range", "Plage auto", default_value=True,
                                   help="Timeline and fps of the scene follow the animations at each Resolve"))
_ptg.append(hou.ButtonParmTemplate("btn_resolve", "Resolve / Recharger", script_callback=_CB,
                                   script_callback_language=_PY,
                                   help="Re-read the published animations and rebuild the layer"))
_ptg.append(hou.ButtonParmTemplate("btn_frame_range", "Appliquer la plage",
                                   script_callback="hou.phm().apply_frame_range(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Timeline and fps of the scene = those of the animations"))
_ptg.append(hou.StringParmTemplate("layer_path", "Couche", 1, default_value=("",),
                                   help="Layer written by FLUX ($HIP/flux_anim)"))
_ptg.append(hou.StringParmTemplate("anim_range", "range", 1, default_value=("",), is_hidden=True))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_anim_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_anim_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
# The layer FLUX writes (references + noise) goes on top of the input.
_lay = _sub.createNode("sublayer", "anim_layer")
_lay.setInput(0, _sub.indirectInputs()[0])
_fp = _lay.parm("filepath1")
if _fp is None and _lay.parm("num_files") is not None:
    _lay.parm("num_files").set(1)
    _fp = _lay.parm("filepath1")
_fp.setExpression('chs("../layer_path")', hou.exprLanguage.Hscript)
_out.setInput(0, _lay)
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=1, max_num_inputs=1, version="2.0")
{_finalize}
{_restore}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Anim LOP HDA in the running Houdini."""
    log.info("Building FLUX Anim HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Anim HDA built: %s", hda_path)
    else:
        log.error("FLUX Anim HDA build failed: %s", resp.get("error"))
    return resp
