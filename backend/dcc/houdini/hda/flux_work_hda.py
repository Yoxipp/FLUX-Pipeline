"""
FLUX - FLUX Work SOP HDA (ADR 0051, step E3).

A locked controller placed in any geo network: project / sequence / shot (empty = a
sequence task) / task / version menus, "Charger" and "Sauver". The artist's content is
the sibling subnet ``WORK_<SEQ>_<SHOT>_<TASK>`` (free to edit), saved as ``wNNN.cpio``
through the backend routes ``/dcc/houdini/work/*`` (features/houdini_work). The HDA
holds a tiny bootstrap; the controller code is served by ``GET /dcc/houdini/work/module``
(source of flux_work_io.py + MODULE_FUNCTIONS), so a fix needs no HDA rebuild.

Rules (ADR 0051):
* Save always targets ``loaded_*`` (hidden parms), never the menus. Changing the menus
  does nothing until "Charger".
* Never overwrite: every save is a new version. A task without any version gets its
  template ``w000`` first (default content, replaceable by saving a new w000 by hand).
* Loading over unsaved changes asks Sauver / Abandonner / Annuler.
* Lock held by another artist: read-only until "Reprendre". A newer version than the
  loaded one: warned before saving. No merge, ever.
"""

from __future__ import annotations

from pathlib import Path

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
    for _n in ("menu_project", "menu_seq", "menu_shot", "menu_task", "menu_version"):
        globals()[_n] = _dead_menu
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

# Controller, runs inside Houdini after the flux_work_io functions (same globals).
MODULE_FUNCTIONS: str = '''
import json, os, socket, time, urllib.error, urllib.parse, urllib.request

_API = "/dcc/houdini/work"

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

def _ro(node):
    p = node.parm("read_only")
    return bool(p.eval()) if p is not None else False

def _host():
    return socket.gethostname()

def _ref(node, loaded=False):
    pre = "loaded_" if loaded else ""
    return {k: _pval(node, pre + k) for k in ("project", "seq", "shot", "task")}

def _label(ref):
    return " ".join(x for x in (ref["seq"], ref["shot"] or "(sequence)", ref["task"]) if x)

def _work_name(ref):
    return "WORK_" + "_".join(x for x in (ref["seq"], ref["shot"], ref["task"]) if x)

def _ask(text, buttons, default=0, close=None):
    """Dialog in the UI; without UI (hython, farm) the default answer."""
    import hou
    if not hou.isUIAvailable():
        return default
    return hou.ui.displayMessage(text, buttons=buttons, default_choice=default,
                                 close_choice=len(buttons) - 1 if close is None else close,
                                 title="FLUX Work")

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

def _task_status(ref, based_on=""):
    return _get(_API + "/status", based_on=based_on, host=_host(), **ref)

def menu_version(node):
    ref = _ref(node)
    out = ["latest", "Derniere version"]
    if not (ref["project"] and ref["seq"] and ref["task"]):
        return out
    st = _task_status(ref)
    for v in reversed([v for v in st.get("versions", []) if v.get("state") == "ok"]):
        if v["version"] == "w000":
            text = "w000  template"
        else:
            text = "%s  %s  %s" % (v["version"], v.get("author", ""), (v.get("comment") or "")[:40])
        out += [v["version"], text.strip()]
    return out

# ── state ──

def _work_node(node):
    import hou
    path = _pval(node, "work_path")
    return hou.node(path) if path else None

def _ensure_work_node(node, ref):
    """Sibling subnet of the HDA holding the content of *ref*."""
    import hou
    parent = node.parent()
    name = _work_name(ref)
    sub = parent.node(name)
    if sub is None:
        sub = parent.createNode("subnet", name)
        sub.setPosition(node.position() + hou.Vector2(0, -1.5))
    _set(node, "work_path", sub.path())
    return sub

def is_dirty(node):
    sub = _work_node(node)
    base = _pval(node, "baseline_hash")
    if sub is None or not base:
        return False
    return current_hash(sub) != base

def _set_loaded(node, ref, version, baseline, read_only):
    for k, v in ref.items():
        _set(node, "loaded_" + k, v)
    _set(node, "loaded_version", version)
    _set(node, "baseline_hash", baseline)
    _set(node, "read_only", 1 if read_only else 0)

def _version_tuple(text):
    out = []
    for part in str(text or "").split("."):
        try:
            out.append(int(part))
        except ValueError:
            break
    return tuple(out)

def _default_content(subnet, task):
    """Content of a task without any template cpio (project or FLUX)."""
    import hou
    note = subnet.createStickyNote("flux_template_note")
    if subnet.childTypeCategory() == hou.sopNodeTypeCategory():
        merge = subnet.createNode("object_merge", "IN_ANIM")
        merge.parm("xformtype").set(1)              # into this object
        out = subnet.createNode("null", "OUT_" + task)
        out.setInput(0, merge)
        note.setText("Template FLUX %s : IN_ANIM = objet de l'anim du shot, travail entre IN et OUT." % task)
    else:
        out = subnet.createNode("null", "OUT_" + task)
        out.setInput(0, subnet.indirectInputs()[0])
        note.setText("Template FLUX %s : pose un FLUX Shot Import en tete, travail jusqu'a OUT." % task)
    end = subnet.createNode("output", "output0")
    end.setInput(0, out)
    end.setDisplayFlag(True)
    subnet.layoutChildren()

def _render_setup(stage, plan):
    """RENDER template = the maintainer's render scene (ADR 0037): FLUX Sequence, shot blocks, each
    block's imports and FLUX Render, the project resolution. Same steps as the render
    scene generator (features/folder_manager/houdini_render_scene.py), on the Work subnet."""
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

def _build_template(ref, subnet):
    """Fill *subnet* with the template of the task (becomes w000). Returns an error or ""."""
    tpl = _get(_API + "/template", **ref)
    if "cpio" not in tpl:
        return "FLUX injoignable : %s" % tpl.get("error", "")
    clear_work(subnet)
    if tpl["cpio"]:
        res = load_work(subnet, tpl["cpio"])
        if not res["ok"]:
            clear_work(subnet)
            return "Template refuse, types absents : %s (reconstruis les HDA)" % ", ".join(res["missing_types"])
    else:
        _default_content(subnet, ref["task"])
    setup = tpl.get("setup") or {}
    if setup.get("kind") == "render_sequence":
        _render_setup(subnet, setup)
    return ""

def _save_version(ref, subnet, based_on, comment, template=False, render_blocks=None):
    """Reserve -> write the cpio -> commit. Returns (result, error)."""
    import hou
    r = _post(_API + "/reserve", dict(ref, author="", host=_host(), based_on=based_on, comment=comment,
                                      houdini_version=hou.applicationVersionString(),
                                      license=str(hou.licenseCategory()).split(".")[-1],
                                      category=subnet.childTypeCategory().name(), template=template))
    if not r.get("version"):
        return None, "Reservation refusee : %s" % (r.get("error") or r)
    try:
        saved = save_work(subnet, r["cpio"])
    except Exception as exc:
        _post(_API + "/abort", dict(ref, version=r["version"]))
        return None, "Ecriture Houdini echouee : %s" % exc
    c = _post(_API + "/commit", dict(ref, version=r["version"], hash=saved["hash"], size=saved["size"],
                                     node_types=saved["node_types"], external_deps=saved["external_deps"],
                                     embedded_hdas=saved["embedded_hdas"], render_blocks=render_blocks))
    if c.get("state") != "ok":
        _post(_API + "/abort", dict(ref, version=r["version"]))
        return None, "Commit refuse : %s" % (c.get("error") or c)
    return {"version": r["version"], "hash": saved["hash"]}, ""

# ── RENDER <-> Production Timeline (features/houdini_work/render_sync.py) ──

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

# ── buttons ──

def load(node):
    """Open the task of the menus at the chosen version (Charger)."""
    import hou
    ref = _ref(node)
    if not (ref["project"] and ref["seq"] and ref["task"]):
        _status(node, "Choisis projet, sequence et tache"); return False
    old_ref = _ref(node, loaded=True)
    old_sub = _work_node(node)
    if old_ref["task"] and old_sub is not None and not _ro(node) and is_dirty(node):
        choice = _ask("Le Work charge (%s) a des modifications non sauvees." % _label(old_ref),
                      ("Sauver", "Abandonner", "Annuler"), default=0, close=2)
        if choice == 2:
            _status(node, "Chargement annule"); return False
        if choice == 0 and not save(node):
            return False
    st = _task_status(ref)
    if "versions" not in st:
        _status(node, "FLUX injoignable : %s" % st.get("error", "")); return False
    ok_versions = [v for v in st["versions"] if v.get("state") == "ok"]
    want = _pval(node, "version") or "latest"
    if not ok_versions:
        target = None
    elif want == "latest":
        target = ok_versions[-1]
    else:
        target = next((v for v in ok_versions if v["version"] == want), None)
        if target is None:
            _status(node, "Version introuvable : %s" % want); return False
    if target is not None and _version_tuple(target.get("houdini_version")) > _version_tuple(hou.applicationVersionString()):
        _status(node, "%s sauvee avec Houdini %s, plus recent que cette session : refus"
                % (target["version"], target.get("houdini_version"))); return False
    lock = _post(_API + "/lock", dict(ref, author="", host=_host()))
    read_only = not lock.get("ok")
    holder = lock.get("lock") or {}
    if target is None and read_only:
        _status(node, "Tache vide et verrouillee par %s@%s" % (holder.get("author"), holder.get("host")))
        return False
    is_new = hou.node(node.parent().path() + "/" + _work_name(ref)) is None
    sub = _ensure_work_node(node, ref)
    if target is None:
        err = _build_template(ref, sub)
        if not err:
            set_context(sub, ref["seq"], ref["shot"], ref["task"])
            res, err = _save_version(ref, sub, "", "template", template=True,
                                     render_blocks=_render_blocks(sub) if _is_render(ref) else None)
        if err:
            if is_new:
                sub.destroy()
                _set(node, "work_path", old_sub.path() if old_sub is not None else "")
            if ref != old_ref:
                _post(_API + "/unlock", dict(ref, author="", host=_host()))
            _status(node, err); return False
        version, baseline, missing_deps = res["version"], res["hash"], []
    else:
        res = load_work(sub, target["cpio"], expected_types=target.get("node_types"))
        if not res["ok"]:
            if res["warnings"]:
                clear_work(sub)
            if is_new and not sub.children():
                sub.destroy()
                _set(node, "work_path", old_sub.path() if old_sub is not None and old_sub.path() != sub.path() else "")
            if not read_only and ref != old_ref:
                _post(_API + "/unlock", dict(ref, author="", host=_host()))
            _status(node, "Refus : types de nodes absents dans cette session : %s" % ", ".join(res["missing_types"]))
            return False
        set_context(sub, ref["seq"], ref["shot"], ref["task"])
        version, baseline = target["version"], res["baseline_hash"]
        missing_deps = [d for d in target.get("external_deps", []) if not os.path.exists(d.get("path", ""))]
    timeline = _follow_timeline(node, ref, sub, version) if _is_render(ref) and target is not None else ""
    # The previous Work: lock freed, content removed (saved or abandoned above).
    if old_ref["task"] and old_ref != ref:
        if not _ro(node):
            _post(_API + "/unlock", dict(old_ref, author="", host=_host()))
        if old_sub is not None and old_sub.path() != sub.path():
            old_sub.destroy()
    _set_loaded(node, ref, version, baseline, read_only)
    msg = "Charge : %s %s" % (_label(ref), version)
    if read_only:
        msg += "  LECTURE SEULE (verrou %s@%s, Reprendre pour sauver)" % (holder.get("author"), holder.get("host"))
    if missing_deps:
        msg += "  fichiers absents : " + ", ".join(d["node"] + "/" + d["parm"] for d in missing_deps[:5])
    if timeline:
        msg += "  " + timeline
    _status(node, msg)
    return True

def save(node):
    """New version of the loaded task (Sauver). Never the menus, never an overwrite."""
    ref = _ref(node, loaded=True)
    if not ref["task"]:
        _status(node, "Rien de charge : clique Charger"); return False
    sub = _work_node(node)
    if sub is None:
        _status(node, "Subnet de travail introuvable (%s)" % _pval(node, "work_path")); return False
    loaded = _pval(node, "loaded_version")
    st = _task_status(ref, based_on=loaded)
    if "versions" not in st:
        _status(node, "FLUX injoignable : %s" % st.get("error", "")); return False
    if st.get("read_only") or _ro(node):
        lock = st.get("lock") or {}
        _status(node, "Lecture seule : verrou de %s@%s. Reprendre pour sauver" % (lock.get("author"), lock.get("host")))
        return False
    if st.get("diverged"):
        latest = next((v for v in st["versions"] if v["version"] == st["latest"]), {})
        choice = _ask("Une version plus recente existe : %s (%s, %s).\\nTon travail part de %s.\\n"
                      "Sauver quand meme en nouvelle version ?" % (st["latest"], latest.get("author", "?"),
                                                                    latest.get("date", "?"), loaded),
                      ("Sauver quand meme", "Annuler"), default=1, close=1)
        if choice != 0:
            _status(node, "Sauvegarde annulee : %s plus recente que %s" % (st["latest"], loaded)); return False
    blocks, report = None, ""
    if _is_render(ref):
        # Production first: a failed save after it never makes the next opening undo
        # the artist's ranges (scene == Production then, nothing to pull).
        blocks, err, report = _push_timeline(ref, sub, loaded)
        if err:
            _status(node, err); return False
    res, err = _save_version(ref, sub, loaded, _pval(node, "comment"), render_blocks=blocks)
    if res is None:
        _status(node, err); return False
    _set(node, "loaded_version", res["version"])
    _set(node, "baseline_hash", res["hash"])
    _set(node, "comment", "")
    _status(node, ("Sauve : %s %s  " % (_label(ref), res["version"]) + report).strip())
    return True

def take_over(node):
    """Take the lock of the loaded task (Reprendre): traced in lock.json."""
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
    """Free the lock of the loaded task (Liberer). The content stays in the scene."""
    ref = _ref(node, loaded=True)
    if not ref["task"] or _ro(node):
        _status(node, "Pas de verrou a liberer"); return False
    _post(_API + "/unlock", dict(ref, author="", host=_host()))
    _set(node, "read_only", 1)
    _status(node, "Verrou libere : %s en lecture seule" % _label(ref))
    return True

def refresh(node):
    """Status line: loaded version, newest one, lock, unsaved changes."""
    ref = _ref(node, loaded=True)
    if not ref["task"]:
        _status(node, "Rien de charge"); return
    loaded = _pval(node, "loaded_version")
    st = _task_status(ref, based_on=loaded)
    if "versions" not in st:
        _status(node, "FLUX injoignable"); return
    parts = ["%s %s" % (_label(ref), loaded)]
    if st.get("diverged"):
        parts.append("plus recente : %s" % st["latest"])
    if st.get("read_only"):
        lock = st.get("lock") or {}
        parts.append("verrou %s@%s" % (lock.get("author"), lock.get("host")))
    parts.append("modifie" if is_dirty(node) else "a jour")
    _status(node, "  ".join(parts))

def on_created(node):
    pass

def on_loaded(node):
    pass
'''


def module_code() -> str:
    """Served PythonModule: the flux_work_io functions then the controller."""
    from dcc.houdini.hda import flux_work_io

    io_src = Path(flux_work_io.__file__).read_text(encoding="utf-8")
    io_src = io_src.replace("from __future__ import annotations\n", "")
    return io_src + "\n" + MODULE_FUNCTIONS


# Body of the build: the subnet that becomes the HDA (_sub) and what holds it (_holder,
# destroyed after). Output of the HDA = the work subnet (object_merge in SOP, fetch in LOP).
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
_res = _sub.createNode("object_merge", "work_result")
_res.parm("objpath1").set('`chs("../work_path")`')
_res.parm("xformtype").set(1)
_out = _sub.createNode("output", "output0")
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
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \
    or _sub.createNode("output", "output0")
_res = _sub.createNode("fetch", "work_result")
_res.parm("loppath").set('`chs("../work_path")`')
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

def _menu(name, label, default, fn, help_txt):
    t = hou.StringParmTemplate(name, label, 1, default_value=(default,), help=help_txt,
                               menu_type=hou.menuType.Normal)
    t.setItemGeneratorScript("hou.phm()." + fn + "(kwargs['node'])")
    t.setItemGeneratorScriptLanguage(_PY)
    return t

def _button(name, label, fn, help_txt, join=False):
    t = hou.ButtonParmTemplate(name, label, script_callback="hou.phm()." + fn + "(kwargs['node'])",
                               script_callback_language=_PY, help=help_txt)
    t.setJoinWithNext(join)
    return t

_ptg = hou.ParmTemplateGroup()
_ptg.append(_menu("project", "Projet", "", "menu_project", "FLUX project"))
_ptg.append(_menu("seq", "Sequence", "", "menu_seq", "Sequence of the task"))
_ptg.append(_menu("shot", "Shot", "", "menu_shot", "Shot of the task (empty = sequence task)"))
_ptg.append(_menu("task", "Tache", "", "menu_task", "Department (CFX, FX, LIGHT, RENDER)"))
_ptg.append(_menu("version", "Version", "latest", "menu_version",
                  "Version to load: latest, an older wNNN or the template w000"))
_ptg.append(_button("btn_load", "Charger", "load",
                    "Load the chosen task and version (asks before dropping unsaved changes)"))
_ptg.append(hou.SeparatorParmTemplate("sep_save"))
_ptg.append(hou.StringParmTemplate("comment", "Commentaire", 1, default_value=("",),
                                   help="Comment of the next saved version"))
_ptg.append(_button("btn_save", "Sauver (nouvelle version)", "save",
                    "Saves the LOADED task as a new version, never an overwrite", join=True))
_ptg.append(_button("btn_refresh", "Statut", "refresh", "Newest version, lock, unsaved changes"))
_ptg.append(_button("btn_take_over", "Reprendre", "take_over",
                    "Take the lock of another artist (traced)", join=True))
_ptg.append(_button("btn_release", "Liberer", "release", "Free the lock, the task stays loaded read-only"))
_ptg.append(hou.SeparatorParmTemplate("sep_state"))
_wp = hou.StringParmTemplate("work_path", "Contenu", 1, default_value=("",),
                             string_type=hou.stringParmType.NodeReference,
                             help="Sibling subnet holding the work (WORK_<SEQ>_<SHOT>_<TASK>)")
_wp.setConditional(hou.parmCondType.DisableWhen, "{{ 1 == 1 }}")
_ptg.append(_wp)
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))
# What is loaded: the only target of Sauver (ADR 0051).
for _n in ("loaded_project", "loaded_seq", "loaded_shot", "loaded_task", "loaded_version", "baseline_hash"):
    _ptg.append(hou.StringParmTemplate(_n, _n, 1, default_value=("",), is_hidden=True))
_ptg.append(hou.ToggleParmTemplate("read_only", "read_only", default_value=False, is_hidden=True))

{_container}
_out.setInput(0, _res)
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
    """FLUX Work in /stage: LIGHT and RENDER tasks (content = a LOP subnet)."""
    return build_hda(hda_path, "Lop")
