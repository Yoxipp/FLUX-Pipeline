"""
FLUX - FLUX Work HDA, SOP and LOP (ADR 0051, ADR 0090: one work = one scene).

A locked controller, one per scene. The artist's content is the whole scene, saved as
``wNNN.hip`` (extension from the license) through the backend routes
``/dcc/houdini/work/*`` (features/houdini_work). The HDA holds a tiny bootstrap; the
controller code is served by ``GET /dcc/houdini/work/module`` (MODULE_FUNCTIONS), so a
fix needs no HDA rebuild.

Rules (ADR 0051 / 0090):
* The scene knows its task from its own file: ``wNNN.hip`` + ``wNNN.json`` (manifest with
  project / seq / shot / task), read back when the scene opens (``bind``). The context
  menus are then locked; a free scene keeps them editable and "Sauver" adopts it as the
  next version of the chosen task.
* Never overwrite: every save is a new version and the scene takes its name. Opening the
  template ``w000`` saves ``w001`` at once (RENDER: after its setup from Production).
* Dirty = ``hou.hipFile.hasUnsavedChanges()``. Opening another version over unsaved
  changes asks Sauver / Abandonner / Annuler. Never a merge.
* Lock held by another artist: read-only until "Reprendre". A newer version than the
  loaded one: warned before saving.
* A second FLUX Work in the scene is refused.

Scene variables: the project / seq / shot / task / asset menus set ``$PROD`` ``$SEQ``
``$SHOT`` ``$TASK`` ``$ASSET`` (hscript ``set -g``, saved in the .hip).
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_work"
LABEL = "FLUX Work"
API = "/dcc/houdini/work"

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/work/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _dead_menu(*a, **kw): return ["", "FLUX offline"]
    for _n in ("menu_project", "menu_seq", "menu_shot", "menu_task", "menu_version", "menu_asset"):
        globals()[_n] = _dead_menu
    def set_scene_vars(node):
        # Offline too: the scene variables only need the menus.
        import hou
        for _v, _p in (("PROD", "project"), ("SEQ", "seq"), ("SHOT", "shot"), ("TASK", "task"), ("ASSET", "asset")):
            _val = "".join(c for c in (node.parm(_p).evalAsString() if node.parm(_p) else "") if c not in "\\\\\\"';")
            hou.hscript('set -g %s = "%s"' % (_v, _val))
        hou.hscript("varchange")
    def on_parm_changed(node): set_scene_vars(node)
    def _offline(node, name):
        try:
            _load()
            globals()[name](node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis reessaie")
    def load(node): _offline(node, "load")
    def save(node): _offline(node, "save")
    def take_over(node): _offline(node, "take_over")
    def release(node): _offline(node, "release")
    def refresh(node): _offline(node, "refresh")
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Controller, runs inside Houdini (globals of the HDA's PythonModule).
MODULE_FUNCTIONS: str = '''
import json, os, socket, time, urllib.error, urllib.parse, urllib.request

_API = "/dcc/houdini/work"
NODE_TYPE = "flux_work"
# Scene variable -> menu it comes from (Copy Path Relative of the Folder Manager uses them).
SCENE_VARS = (("PROD", "project"), ("SEQ", "seq"), ("SHOT", "shot"), ("TASK", "task"), ("ASSET", "asset"))
CONTEXT = ("project", "seq", "shot", "task")

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
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return {"ok": False, "error": json.loads(exc.read()).get("detail", str(exc))}
        except Exception:
            return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "_offline": True}

def _post(path, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{_flux_port()}" + path,
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return {"ok": False, "error": json.loads(exc.read()).get("detail", str(exc))}
        except Exception:
            return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "_offline": True}

_TTL = 30.0
_cache = {}

def _cached(key, fetch):
    """fetch() -> (data, ok). Only good answers are cached."""
    now = time.monotonic()
    if key in _cache and now < _cache[key][0]:
        return _cache[key][1]
    data, ok = fetch()
    if ok:
        _cache[key] = (now + _TTL, data)
    return data

def _pval(node, name):
    p = node.parm(name)
    return p.evalAsString() if p is not None else ""

def _set(node, name, value):
    """Set a parm only when it changes: any set marks the scene as modified."""
    p = node.parm(name)
    if p is None:
        return
    current = p.eval()
    if current == value or (isinstance(current, str) and current == str(value)):
        return
    p.set(value)

def _status(node, msg):
    _set(node, "status_msg", msg)

def _say(msg):
    """A message that must not modify the scene (status line, popup on demand)."""
    import hou
    if hou.isUIAvailable():
        hou.ui.displayMessage(msg, title="FLUX Work")
    else:
        print("[FLUX Work] " + msg)

def _flat(values):
    out = []
    for v in values:
        out += [v, v]
    return out

def _ro(node):
    p = node.parm("read_only")
    return bool(p.eval()) if p is not None else False

def _host():
    return socket.gethostname()

def _ref(node, loaded=False):
    pre = "loaded_" if loaded else ""
    return {k: _pval(node, pre + k) for k in CONTEXT}

def _bound(node):
    return bool(_pval(node, "loaded_task"))

def _label(ref):
    return " ".join(x for x in (ref["seq"], ref["shot"] or "(sequence)", ref["task"]) if x)

def _ask(text, buttons, default=0, close=None):
    """Dialog in the UI; without UI (hython, farm) the default answer."""
    import hou
    if not hou.isUIAvailable():
        return default
    return hou.ui.displayMessage(text, buttons=buttons, default_choice=default,
                                 close_choice=len(buttons) - 1 if close is None else close,
                                 title="FLUX Work")

def _defer(fn):
    """Run *fn* once Houdini is idle (a scene load from a callback, a node destroy)."""
    try:
        import hdefereval
        hdefereval.executeDeferred(fn)
    except ImportError:
        fn()

def _stage(node):
    """Network holding the scene content the Work drives (RENDER: /stage)."""
    return node.parent()

def is_dirty(node=None):
    import hou
    return hou.hipFile.hasUnsavedChanges()

def _others(node):
    """The other FLUX Work nodes of the scene (SOP or LOP)."""
    import hou
    out = []
    for cat in (hou.sopNodeTypeCategory(), hou.lopNodeTypeCategory()):
        ntype = cat.nodeTypes().get(NODE_TYPE)
        if ntype is not None:
            out += [n for n in ntype.instances() if n.path() != node.path()]
    return out

# ── menus ──

def menu_project(node):
    def _fetch():
        r = _get("/dcc/houdini/importer/tokens")
        return r.get("projects", []), not r.get("_offline")
    projects = _cached("projects", _fetch)
    return _flat(projects) if projects else ["", "FLUX injoignable ou aucun projet"]

def _sequences(node):
    project = _pval(node, "project")
    if not project:
        return []
    def _fetch():
        r = _get(_API + "/shots", project=project)
        return r.get("sequences", []), "sequences" in r
    return _cached("shots:" + project, _fetch)

def menu_seq(node):
    return _flat([s["seq"] for s in _sequences(node)]) or ["", "aucune sequence (Production)"]

def menu_shot(node):
    seq = _pval(node, "seq")
    shots = next((s["shots"] for s in _sequences(node) if s["seq"] == seq), [])
    return ["", "(sequence entiere)"] + _flat(shots)

def menu_task(node):
    project = _pval(node, "project")
    if not project:
        return ["", "choisis un projet"]
    def _fetch():
        r = _get(_API + "/tasks", project=project, category=category)
        return r.get("tasks", []), "tasks" in r
    category = node.type().category().name()        # Sop: CFX / FX, Lop: LIGHT / RENDER
    return _flat(_cached("tasks:%s:%s" % (project, category), _fetch)) or ["", "aucune tache"]

def _mine(node, versions):
    """Committed versions this Work can open: same network type (a SOP work never
    opens as a LOP one). Manifests without category are kept."""
    cat = node.type().category().name()
    return [v for v in versions if v.get("state") == "ok" and v.get("category", cat) in ("", cat)]

def _task_status(ref, based_on=""):
    return _get(_API + "/status", based_on=based_on, host=_host(), **ref)

def menu_version(node):
    ref = _ref(node)
    out = ["latest", "Derniere version"]
    if not (ref["project"] and ref["seq"] and ref["task"]):
        return out
    st = _task_status(ref)
    for v in reversed(_mine(node, st.get("versions", []))):
        if v["version"] == "w000":
            text = "w000  template"
        else:
            text = "%s  %s  %s" % (v["version"], v.get("author", ""), (v.get("comment") or "")[:40])
        out += [v["version"], text.strip()]
    return out

def menu_asset(node):
    project = _pval(node, "project")
    if not project:
        return ["", "choisis un projet"]
    def _fetch():
        r = _get(_API + "/assets", project=project)
        return r.get("assets", []), "assets" in r
    return ["", "(aucun)"] + _flat(_cached("assets:" + project, _fetch))

def _version_tuple(text):
    out = []
    for part in str(text or "").split("."):
        try:
            out.append(int(part))
        except ValueError:
            break
    return tuple(out)

# ── RENDER template setup and <-> Production Timeline (features/houdini_work/render_sync.py) ──

def _render_setup(stage, plan):
    """RENDER template = the maintainer's render scene (ADR 0037): FLUX Sequence, shot blocks, each
    block's imports and FLUX Render, the project resolution. Same steps as the render
    scene generator (features/folder_manager/houdini_render_scene.py), on /stage."""
    import hou
    ns = {}
    exec(plan["sequence_module"], ns)
    seq = plan["seq"]
    top = stage.node("FLUX_SEQUENCE") or stage.createNode("flux_sequence", "FLUX_SEQUENCE")
    for name, value in (("project", plan["project"]), ("seq", seq), ("shot_count", plan["blocks"])):
        if top.parm(name) is not None:
            top.parm(name).set(value)
    structure = stage.node("STRUCTURE")
    if structure is not None and not top.outputs() and not structure.inputs():
        structure.setInput(0, top)
        top.setPosition(structure.position() + hou.Vector2(0, 1.5))
    ns["grow_to"](stage, plan["blocks"], plan["project"], seq)
    real = [s["shot"] for s in plan["shots"]]
    for n in ns["shot_numbers"](stage):
        shot = real[n - 1] if n - 1 < len(real) else ""
        rng = plan["shots"][n - 1].get("range") if n - 1 < len(real) else None
        for prefix in ("IMPORT_ENV_", "IMPORT_CHAR_", "FLUX_RENDER_"):
            block = stage.node("%sSHOT%03d" % (prefix, n))
            if block is None:
                continue
            for pname, pval in (("project", plan["project"]), ("seq", seq), ("shot", shot)):
                if block.parm(pname) is not None and (pval or pname != "shot"):
                    block.parm(pname).set(pval)
        if rng:
            _set_block_range(stage, "SHOT%03d" % n, rng)
    if top.parm("status_msg") is not None:
        top.parm("status_msg").set("%d shot(s)" % plan["blocks"])
    for rs in stage.children():
        if rs.type().name().startswith("karmarendersettings") and rs.parmTuple("resolution") is not None:
            if rs.parm("res_mode") is not None:
                rs.parm("res_mode").set("manual")
            for p, v in zip(rs.parmTuple("resolution"), plan["resolution"]):
                p.lock(False)
                p.deleteAllKeyframes()
                p.set(v)

def _is_render(ref):
    return ref.get("task") == "RENDER"

def _render_blocks(stage):
    """[{block, shot, range}] of the render Work: one per FLUX_RENDER_SHOTnnn."""
    out = []
    for fr in stage.children():
        if not fr.name().startswith("FLUX_RENDER_SHOT") or fr.parm("frame_rangex") is None:
            continue
        try:
            rng = [int(fr.evalParm("frame_rangex")), int(fr.evalParm("frame_rangey"))]
        except Exception:
            rng = None
        shot = fr.parm("shot").evalAsString().upper() if fr.parm("shot") is not None else ""
        out.append({"block": fr.name()[len("FLUX_RENDER_"):], "shot": shot, "range": rng})
    return sorted(out, key=lambda b: b["block"])

def _set_block_range(stage, block, rng):
    """The block's range as plain values on FLUX Render (stops following the import)."""
    fr = stage.node("FLUX_RENDER_" + block)
    if fr is None or not rng:
        return False
    for comp, value in zip(("x", "y"), rng):
        p = fr.parm("frame_range" + comp)
        if p is not None:
            p.deleteAllKeyframes()
            p.set(int(value))
    return True

def _add_blocks(node, ref, stage, missing):
    """Shots of the Timeline without a block: new blocks through FLUX Sequence."""
    tpl = _get(_API + "/template", **ref)
    module = (tpl.get("setup") or {}).get("sequence_module")
    if not module or not missing:
        return []
    ns = {}
    exec(module, ns)
    before = list(ns["shot_numbers"](stage))
    ns["grow_to"](stage, len(before) + len(missing), ref["project"], ref["seq"])
    new = [n for n in ns["shot_numbers"](stage) if n not in before]
    added = []
    for n, item in zip(new, missing):
        for prefix in ("IMPORT_ENV_", "IMPORT_CHAR_", "FLUX_RENDER_"):
            block = stage.node("%sSHOT%03d" % (prefix, n))
            if block is None:
                continue
            for pname, pval in (("project", ref["project"]), ("seq", ref["seq"]), ("shot", item["shot"])):
                if block.parm(pname) is not None:
                    block.parm(pname).set(pval)
        _set_block_range(stage, "SHOT%03d" % n, item.get("range"))
        added.append(item["shot"])
    top = stage.node("FLUX_SEQUENCE")
    if top is not None and top.parm("shot_count") is not None:
        top.parm("shot_count").set(len(ns["shot_numbers"](stage)))
    return added

def _follow_timeline(node, ref, stage, version):
    """Opening: the Timeline changes made since *version* go into the blocks."""
    plan = _post(_API + "/render-sync/plan", dict(ref, base_version=version, blocks=_render_blocks(stage)))
    if "pull" not in plan:
        return "Timeline non lue : %s" % plan.get("error", "")
    pulled = [p["shot"] for p in plan["pull"] if _set_block_range(stage, p["block"], p["range"])]
    added = _add_blocks(node, ref, stage, plan["missing"]) if not ref["shot"] else []
    parts = []
    if pulled:
        parts.append("plage(s) suivie(s) : " + ", ".join(pulled))
    if added:
        parts.append("shot(s) ajoute(s) : " + ", ".join(added))
    return ("Timeline FLUX : " + " ; ".join(parts) + " (a sauver)") if parts else ""

def follow_timeline_from_flux(node, project, changed):
    """FLUX saved the Production (dcc/houdini/shot_sync.py): a render Work on one of the
    changed sequences takes the Timeline now, as an opening would (ranges pulled, blocks
    added for new shots, the scene then has to be saved). None = not concerned."""
    ref = _ref(node, loaded=True)
    if not _is_render(ref) or ref["project"] != project:
        return None
    if not any(str(seq) == ref["seq"] for seq, _shot in changed):
        return None
    if _ro(node):
        return "read_only"
    msg = _follow_timeline(node, ref, _stage(node), _pval(node, "loaded_version"))
    if msg:
        _status(node, msg)
    return msg or "unchanged"

def _push_timeline(ref, stage, loaded):
    """Save: the blocks changed in Houdini go to Production (asked when both sides
    changed, confirmed for new shots). Returns (blocks to store, error, report)."""
    plan = _post(_API + "/render-sync/plan", dict(ref, base_version=loaded, blocks=_render_blocks(stage)))
    if "push" not in plan:
        return None, "Timeline non lue : %s" % plan.get("error", ""), ""
    push, create = list(plan["push"]), list(plan["create"])
    pull = list(plan["pull"])
    for c in plan["conflicts"]:
        flux = c.get("flux")
        choice = _ask("Shot %s modifie dans Houdini ET dans la Timeline FLUX.\\nHoudini : %d-%d\\nFLUX : %s\\n"
                      "Quelle plage garder ?" % (c["shot"], c["houdini"][0], c["houdini"][1],
                                                 "%d-%d" % tuple(flux) if flux else "aucune"),
                      ("Garder Houdini", "Garder FLUX"), default=1, close=1)
        if choice == 0 or not flux:
            push.append({"block": c["block"], "shot": c["shot"], "range": c["houdini"]})
        else:
            pull.append({"block": c["block"], "shot": c["shot"], "range": flux})
    if create:
        choice = _ask("Creer dans Production %d shot(s) absent(s) de la Timeline ?\\n%s"
                      % (len(create), ", ".join("%s (%d-%d)" % (c["shot"], c["range"][0], c["range"][1]) for c in create)),
                      ("Creer", "Ne pas creer", "Annuler"), default=0, close=2)
        if choice == 2:
            return None, "Sauvegarde annulee", ""
        if choice == 1:
            create = []
    for p in pull:
        _set_block_range(stage, p["block"], p["range"])
    report = []
    if push or create:
        done = _post(_API + "/render-sync/apply", dict(ref, push=push, create=create))
        if "updated" not in done:
            return None, "Timeline non mise a jour : %s" % (done.get("error") or done), ""
        if done["updated"]:
            report.append("Timeline mise a jour : " + ", ".join(done["updated"]))
        if done["created"]:
            report.append("shot(s) cree(s) : " + ", ".join(done["created"]))
        if done["locked"]:
            report.append("verrouille(s), non change(s) : " + ", ".join(done["locked"]))
    if pull:
        report.append("plage(s) FLUX gardee(s) : " + ", ".join(p["shot"] for p in pull))
    return _render_blocks(stage), "", "  ".join(report)

# ── opening: the scene tells its task ──

def bind(node):
    """The scene just opened: read its task from its manifest, lock it, prepare and save
    w001 when it is the template w000 (ADR 0090 point 4). A free scene is left as is."""
    import hou
    if hou.node(node.path()) is None:
        return
    w = _get(_API + "/identify", path=hou.hipFile.path())
    if "work" not in w:
        _status(node, "FLUX injoignable : %s" % w.get("error", "")); return
    work = w["work"]
    if not work:
        return
    ref = {k: work.get(k, "") for k in CONTEXT}
    for k, v in ref.items():
        _set(node, k, v)
        _set(node, "loaded_" + k, v)
    _set(node, "loaded_version", work["version"])
    set_scene_vars(node)
    lock = _post(_API + "/lock", dict(ref, author="", host=_host()))
    read_only = not lock.get("ok")
    _set(node, "read_only", 1 if read_only else 0)
    holder = lock.get("lock") or {}
    if not read_only:
        _autosave_arm(node)
    if work["version"] == "w000":
        if _is_render(ref):
            tpl = _get(_API + "/template", **ref)
            setup = tpl.get("setup") or {}
            if setup.get("kind") == "render_sequence":
                _render_setup(_stage(node), setup)
        if read_only:
            _status(node, "Template ouvert, verrou de %s@%s : Reprendre puis Sauver"
                    % (holder.get("author"), holder.get("host"))); return
        save(node, comment="template", template=True)
        return
    if not read_only and _offer_recovery(node, ref, work["version"]):
        return
    msg = ""
    if read_only:
        msg = "LECTURE SEULE (verrou %s@%s, Reprendre pour sauver)" % (holder.get("author"), holder.get("host"))
    if _is_render(ref) and not read_only:
        msg = _follow_timeline(node, ref, _stage(node), work["version"])
    if msg:
        _status(node, "%s %s  %s" % (_label(ref), work["version"], msg))

# â”€â”€ autosave and recovery (features/houdini_work/autosave.py, ADR 0090 point 6) â”€â”€

_AUTOSAVE_TICK_S = 20.0       # the event loop callback only looks at the clock

def _autosave_state():
    """One state per Houdini session, kept on the hou module so that a re-exec of this
    module (fix without rebuild) replaces the old callback instead of doubling it."""
    import hou
    st = getattr(hou, "_flux_work_autosave", None)
    if st is None:
        st = {"cb": None, "node": "", "last": time.monotonic(), "minutes": None, "busy": False}
        hou._flux_work_autosave = st
    return st

def _autosave_arm(node):
    """Start the timer for this scene's FLUX Work (UI sessions only)."""
    import hou
    if not hou.isUIAvailable():
        return
    st = _autosave_state()
    st["node"] = node.path()
    st["last"] = time.monotonic()
    if st["cb"] is not None:
        try:
            hou.ui.removeEventLoopCallback(st["cb"])
        except Exception:
            pass
    st["cb"] = _autosave_tick
    hou.ui.addEventLoopCallback(_autosave_tick)

def _autosave_tick():
    """Event loop callback: cheap clock check, the work happens once per interval."""
    import hou
    st = _autosave_state()
    try:
        if st["busy"]:
            return
        wait = (st["minutes"] if st["minutes"] is not None else 5) * 60.0
        if wait <= 0:
            wait = 60.0                       # off: look at the setting again every minute
        if time.monotonic() - st["last"] < max(wait, _AUTOSAVE_TICK_S):
            return
        st["last"] = time.monotonic()
        st["busy"] = True
        try:
            _autosave_once(st)
        finally:
            st["busy"] = False
    except Exception:
        pass                                  # an autosave problem never reaches the artist

def _autosave_once(st):
    """Interval from the backend (advanced switch), then a copy of the bound scene when it
    has unsaved changes. save(copy) renames the scene, setName gives the name back."""
    import hou
    cfg = _get(_API + "/autosave/config")
    if "minutes" not in cfg:
        return                                # FLUX offline: next time
    st["minutes"] = int(cfg["minutes"])
    if st["minutes"] <= 0:
        return
    node = hou.node(st["node"])
    if node is None or not _bound(node) or _ro(node) or not hou.hipFile.hasUnsavedChanges():
        return
    if hou.hipFile.isNewFile():
        return
    ref = _ref(node, loaded=True)
    slot = _post(_API + "/autosave/slot", dict(ref, ext=os.path.splitext(hou.hipFile.path())[1]))
    if not slot.get("path"):
        return
    current = hou.hipFile.path()
    try:
        hou.hipFile.save(slot["path"], save_to_recent_files=False)
    finally:
        hou.hipFile.setName(current)
    _keep_dirty(node)

def _keep_dirty(node):
    """The scene had unsaved changes before the autosave copy: it must still have them,
    or Houdini would close without asking and the real wNNN would never be written. A
    harmless re-set of a hidden parm (same value) marks it modified again if the copy
    cleared the flag."""
    import hou
    if hou.hipFile.hasUnsavedChanges():
        return
    p = node.parm("loaded_version")
    if p is not None:
        p.set(p.eval())

def _offer_recovery(node, ref, version):
    """Opening a work: an autosave newer than its file is proposed (2026-11-21: here
    in Houdini only). Yes = it becomes the next version wNNN+1 and that scene opens."""
    import hou
    if not hou.isUIAvailable():
        return False
    found = _get(_API + "/autosave/candidate", **ref).get("candidate")
    if not found:
        return False
    when = time.strftime("%d/%m %H:%M", time.localtime(found["mtime"]))
    choice = _ask("Une sauvegarde automatique du %s est plus recente que %s %s.\\n"
                  "La recuperer comme version suivante ?" % (when, _label(ref), version),
                  ("Recuperer", "Ignorer"), default=0, close=1)
    if choice != 0:
        return False
    r = _post(_API + "/autosave/recover", dict(ref, author="", host=_host()))
    if not r.get("hip"):
        _status(node, "Recuperation refusee : %s" % (r.get("error") or r))
        return False
    _defer(lambda: _open_scene(r["hip"]))
    return True

def _open_scene(path):
    import hou
    hou.hipFile.load(path, suppress_save_prompt=True)

# ── buttons ──

def load(node):
    """Open the chosen version of the task (Ouvrir): the latest (the template copied
    first when the task has none) or an older wNNN. Asks before dropping changes."""
    import hou
    ref = _ref(node)
    if not (ref["project"] and ref["seq"] and ref["task"]):
        _status(node, "Choisis projet, sequence et tache"); return False
    want = _pval(node, "version") or "latest"
    if want == "latest":
        r = _post(_API + "/start", dict(ref, author="", host=_host()))
        if not r.get("hip"):
            _status(node, "Ouverture refusee : %s" % (r.get("error") or r)); return False
        path = r["hip"]
    else:
        st = _task_status(ref)
        if "versions" not in st:
            _status(node, "FLUX injoignable : %s" % st.get("error", "")); return False
        target = next((v for v in _mine(node, st["versions"]) if v["version"] == want), None)
        if target is None or not target.get("hip"):
            _status(node, "Version introuvable : %s" % want); return False
        if _version_tuple(target.get("houdini_version")) > _version_tuple(hou.applicationVersionString()):
            _status(node, "%s sauvee avec Houdini %s, plus recent que cette session : refus"
                    % (target["version"], target.get("houdini_version"))); return False
        path = target["hip"]
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(hou.hipFile.path())):
        _say("Cette version est deja ouverte."); return False
    if is_dirty():
        choice = _ask("La scene a des modifications non sauvees.", ("Sauver", "Abandonner", "Annuler"),
                      default=0, close=2)
        if choice == 2:
            return False
        if choice == 0:
            if _bound(node):
                if not save(node):
                    return False
            elif hou.hipFile.isNewFile():
                _say("Scene sans nom : sauve-la (Fichier > Enregistrer) ou choisis Abandonner.")
                return False
            else:
                hou.hipFile.save()
    old = _ref(node, loaded=True)
    if old["task"] and old != ref and not _ro(node):
        _post(_API + "/unlock", dict(old, author="", host=_host()))
    _defer(lambda: _open_scene(path))
    return True

def save(node, comment=None, template=False):
    """New version of the scene (Sauver). The scene takes its name; never an overwrite.
    A free scene (no task yet) becomes the next version of the task of the menus.
    *template*: w001 saved from the template at opening (RENDER blocks stored as set up,
    nothing pushed to Production)."""
    import hou
    adopt = not _bound(node)
    ref = _ref(node) if adopt else _ref(node, loaded=True)
    if not (ref["project"] and ref["seq"] and ref["task"]):
        _status(node, "Choisis projet, sequence et tache"); return False
    loaded = "" if adopt else _pval(node, "loaded_version")
    st = _task_status(ref, based_on=loaded)
    if "versions" not in st:
        _status(node, "FLUX injoignable : %s" % st.get("error", "")); return False
    if adopt:
        lock = _post(_API + "/lock", dict(ref, author="", host=_host()))
        if not lock.get("ok"):
            holder = lock.get("lock") or {}
            _status(node, "Tache verrouillee par %s@%s" % (holder.get("author"), holder.get("host"))); return False
        if st.get("latest"):
            choice = _ask("%s a deja des versions (derniere : %s).\\nCette scene devient la suivante ?"
                          % (_label(ref), st["latest"]), ("Sauver", "Annuler"), default=1, close=1)
            if choice != 0:
                return False
    else:
        if st.get("read_only") or _ro(node):
            lock = st.get("lock") or {}
            _status(node, "Lecture seule : verrou de %s@%s. Reprendre pour sauver" % (lock.get("author"), lock.get("host")))
            return False
        if st.get("diverged"):
            latest = next((v for v in st["versions"] if v["version"] == st["latest"]), {})
            choice = _ask("Une version plus recente existe : %s (%s, %s).\\nTa scene part de %s.\\n"
                          "Sauver quand meme en nouvelle version ?" % (st["latest"], latest.get("author", "?"),
                                                                        latest.get("date", "?"), loaded),
                          ("Sauver quand meme", "Annuler"), default=1, close=1)
            if choice != 0:
                _status(node, "Sauvegarde annulee : %s plus recente que %s" % (st["latest"], loaded)); return False
    blocks, report = None, ""
    if _is_render(ref) and template:
        blocks = _render_blocks(_stage(node))
    elif _is_render(ref):
        # Production first: a failed save after it never makes the next opening undo
        # the artist's ranges (scene == Production then, nothing to pull).
        blocks, err, report = _push_timeline(ref, _stage(node), loaded)
        if err:
            _status(node, err); return False
    text = _pval(node, "comment") if comment is None else comment
    r = _post(_API + "/reserve", dict(ref, author="", host=_host(), based_on=loaded, comment=text,
                                      houdini_version=hou.applicationVersionString(),
                                      license=str(hou.licenseCategory()).split(".")[-1],
                                      category=node.type().category().name()))
    if not r.get("version"):
        _status(node, "Reservation refusee : %s" % (r.get("error") or r)); return False
    # What the saved file must hold is set BEFORE writing it: a parm set after the save
    # would mark the fresh version as modified.
    before = {k: _pval(node, k) for k in ["loaded_" + c for c in CONTEXT] + ["loaded_version", "comment", "status_msg"]}
    for k, v in ref.items():
        _set(node, "loaded_" + k, v)
    _set(node, "loaded_version", r["version"])
    _set(node, "comment", "")
    _status(node, ("Sauve : %s %s  " % (_label(ref), r["version"]) + report).strip())
    try:
        hou.hipFile.save(r["hip"])
    except Exception as exc:
        for k, v in before.items():
            _set(node, k, v)
        _post(_API + "/abort", dict(ref, version=r["version"]))
        _status(node, "Ecriture Houdini echouee : %s" % exc); return False
    c = _post(_API + "/commit", dict(ref, version=r["version"], render_blocks=blocks))
    if c.get("state") != "ok":
        _post(_API + "/abort", dict(ref, version=r["version"]))
        _status(node, "Commit refuse : %s (scene non versionnee, resauve)" % (c.get("error") or c)); return False
    return True

def take_over(node):
    """Take the lock of the task (Reprendre): traced in lock.json."""
    ref = _ref(node, loaded=True)
    if not ref["task"]:
        _status(node, "Rien de charge"); return False
    r = _post(_API + "/lock", dict(ref, author="", host=_host(), force=True))
    if not r.get("ok"):
        _status(node, "Reprise refusee : %s" % (r.get("error") or r)); return False
    _set(node, "read_only", 0)
    taken = (r.get("lock") or {}).get("taken_from") or {}
    _status(node, "Verrou repris" + (" a %s@%s" % (taken.get("author"), taken.get("host")) if taken else ""))
    return True

def release(node):
    """Free the lock of the task (Liberer). The scene stays open, read-only."""
    ref = _ref(node, loaded=True)
    if not ref["task"] or _ro(node):
        _status(node, "Pas de verrou a liberer"); return False
    _post(_API + "/unlock", dict(ref, author="", host=_host()))
    _set(node, "read_only", 1)
    _status(node, "Verrou libere : %s en lecture seule" % _label(ref))
    return True

def refresh(node):
    """Loaded version, newest one, lock, unsaved changes (popup: the scene stays as is)."""
    ref = _ref(node, loaded=True)
    if not ref["task"]:
        _say("Scene libre : choisis la tache puis Sauver pour la versionner."); return
    loaded = _pval(node, "loaded_version")
    st = _task_status(ref, based_on=loaded)
    if "versions" not in st:
        _say("FLUX injoignable"); return
    parts = ["%s %s" % (_label(ref), loaded)]
    if st.get("diverged"):
        parts.append("plus recente : %s" % st["latest"])
    if st.get("read_only"):
        lock = st.get("lock") or {}
        parts.append("verrou %s@%s" % (lock.get("author"), lock.get("host")))
    parts.append("modifiee" if is_dirty() else "a jour")
    _say("\\n".join(parts))

# ── scene variables ──

def set_scene_vars(node):
    """$PROD / $SEQ / $SHOT / $TASK / $ASSET of the scene (hscript set -g, saved in the
    .hip) from the menus; only the ones that change (a set marks the scene modified)."""
    import hou
    changed = False
    for var, parm in SCENE_VARS:
        value = "".join(c for c in _pval(node, parm) if c not in "\\\\\\"';")
        current = hou.hscript("echo $%s" % var)[0].strip()
        if current == value or (not value and current == "$" + var):
            continue
        hou.hscript('set -g %s = "%s"' % (var, value))
        changed = True
    if changed:
        hou.hscript("varchange")

def on_parm_changed(node):
    set_scene_vars(node)

def on_created(node):
    """One FLUX Work per scene (ADR 0090): a second one is removed."""
    others = _others(node)
    if not others:
        return
    _ask("Un seul FLUX Work par scene : il y a deja %s." % others[0].path(), ("OK",))
    def _drop():
        try:
            node.destroy()
        except Exception:
            pass                # already gone (undo, scene closed)
    _defer(_drop)

def on_loaded(node):
    _defer(lambda: bind(node))
'''


def module_code() -> str:
    """Served PythonModule of the FLUX Work HDA."""
    return MODULE_FUNCTIONS


# Body of the build: the subnet that becomes the HDA (_sub) and what holds it (_holder,
# destroyed after). The Work drives the whole scene: its own output is empty.
_CONTAINER = {
    "Sop": '''
_obj = hou.node("/obj")
_old = _obj.node("__flux_work_build__")
if _old is not None:
    _old.destroy()
_holder = _obj.createNode("geo", "__flux_work_build__")
for _c in _holder.children():
    _c.destroy()
_sub = _holder.createNode("subnet", "flux_work")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
''',
    "Lop": '''
_holder = None
_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_work_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_work_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
''',
}
_CATEGORY_EXPR = {"Sop": "hou.sopNodeTypeCategory()", "Lop": "hou.lopNodeTypeCategory()"}


def _build_code(hda_path: str, category: str = "Sop") -> str:
    from dcc.houdini.hda.hda_common import FINALIZE as _finalize, ICON_PATH as icon_path
    from dcc.houdini.hda.preserve_instances import RESTORE as _restore, snapshot

    _snapshot = snapshot(_CATEGORY_EXPR[category], NODE_NAME).replace("{{", "{").replace("}}", "}")
    _container = _CONTAINER[category]
    return f'''
import hou
{_snapshot}

_HDA_PATH = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NAME = {NODE_NAME!r}
_PY = hou.scriptLanguage.Python
_PM_CODE = {BOOTSTRAP!r}

def _menu(name, label, default, fn, help_txt, scene_var=False, context=False):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt,
                               menu_type=hou.menuType.Normal)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    if scene_var:  # sets $PROD / $SEQ / $SHOT / $TASK / $ASSET of the scene
        t.setScriptCallback("hou.phm().on_parm_changed(kwargs['node'])")
        t.setScriptCallbackLanguage(_PY)
    if context:    # the task of a versioned scene comes from its file: locked
        t.setConditional(hou.parmCondType.DisableWhen, '{{ loaded_task != "" }}')
    return t

def _button(name, label, fn, help_txt, join=False):
    t = hou.ButtonParmTemplate(name, label, script_callback="hou.phm()." + fn + "(kwargs['node'])",
                               script_callback_language=_PY, help=help_txt)
    t.setJoinWithNext(join)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Projet", "", "menu_project", "FLUX project ($PROD)", True, True))
_ptg.append(_menu("seq", "Sequence", "", "menu_seq", "Sequence of the task ($SEQ)", True, True))
_ptg.append(_menu("shot", "Shot", "", "menu_shot", "Shot of the task, empty = sequence task ($SHOT)", True, True))
_ptg.append(_menu("task", "Tache", "", "menu_task", "Department: CFX, FX, LIGHT, RENDER ($TASK)", True, True))
_ptg.append(_menu("asset", "Asset", "", "menu_asset", "Character of the work, only sets $ASSET", True))
_ptg.append(_menu("version", "Version", "latest", "menu_version",
                  "Version to open: latest, an older wNNN or the template w000"))
_ptg.append(_button("btn_load", "Ouvrir", "load",
                    "Open the chosen version as the scene (asks before dropping unsaved changes)"))
_ptg.append(hou.SeparatorParmTemplate("sep_save"))
_ptg.append(hou.StringParmTemplate("comment", "Commentaire", 1, default_value=("",),
                                   help="Comment of the next saved version"))
_ptg.append(_button("btn_save", "Sauver (nouvelle version)", "save",
                    "Saves the scene as a new version wNNN, never an overwrite", join=True))
_ptg.append(_button("btn_refresh", "Statut", "refresh", "Newest version, lock, unsaved changes"))
_ptg.append(_button("btn_take_over", "Reprendre", "take_over",
                    "Take the lock of another artist (traced)", join=True))
_ptg.append(_button("btn_release", "Liberer", "release", "Free the lock, the scene stays open read-only"))
_ptg.append(hou.SeparatorParmTemplate("sep_state"))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))
# What the scene is: the only target of Sauver (set from the scene's manifest).
for _n in ("loaded_project", "loaded_seq", "loaded_shot", "loaded_task", "loaded_version"):
    _ptg.append(hou.StringParmTemplate(_n, _n, 1, default_value=("",), is_hidden=True))
_ptg.append(hou.ToggleParmTemplate("read_only", "read_only", default_value=False, is_hidden=True))

{_container}
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=0, max_num_inputs=0, version="1.0")
{_finalize}
if _holder is not None:
    _holder.destroy()
{_restore}
result = {{"ok": True, "path": _HDA_PATH, "node_type": {category!r} + "/" + _NAME}}
'''


def build_hda(hda_path: str, category: str = "Sop") -> dict:
    """Build the FLUX Work HDA (SOP by default) in the running Houdini."""
    log.info("Building FLUX Work HDA (%s) -> %s", category, hda_path)
    resp = houdini_client.run(_build_code(hda_path, category))
    if resp.get("ok"):
        log.info("FLUX Work HDA built (%s): %s", category, hda_path)
    else:
        log.error("FLUX Work HDA build failed (%s): %s", category, resp.get("error"))
    return resp


def build_hda_lop(hda_path: str) -> dict:
    """FLUX Work in /stage: LIGHT and RENDER tasks."""
    return build_hda(hda_path, "Lop")
