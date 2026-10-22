"""
FLUX - Houdini "FLUX Render Submit" LOP HDA: send a shot to the Tractor farm (ADR 0015).

No farm logic here: the node only calls POST /render/submit, the same route as the
Tractor page of the launcher (freeze LAST -> vNNN, Tractor job, team settings).

  * the shot (project / sequence / shot, frame range) comes from the FLUX Shot Import
    found upstream, like FLUX Render;
  * Source "Shot publie": the backend freezes and renders the published shot stage;
  * Source "Entree LOP": the input stage is written with a USD ROP to
    <shot>/render/_stages/<SEQ>_<SHOT>_<date>.usd (never overwritten), then rendered.

Same bootstrap as FLUX Render: the real module is fetched from
GET /dcc/houdini/flux_render_submit/module, so a fix needs no HDA rebuild.
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_render_submit"
LABEL = "FLUX Render Submit"

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/flux_render_submit/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def _offline(node, name):
        try:
            _load()
            globals()[name](node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis reessaie")
    def sync_shot(node): _offline(node, "sync_shot")
    def submit(node): _offline(node, "submit")
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Served by GET /dcc/houdini/flux_render_submit/module, exec()'d by the bootstrap (inside Houdini).
MODULE_FUNCTIONS: str = '''
import datetime, json, os, urllib.error, urllib.request
import hou

SHOT_TYPE = "flux_shot"

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _post(path, payload, timeout=300):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (_flux_port(), path),
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", str(exc))
        except Exception:
            detail = str(exc)
        return {"ok": False, "error": detail}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _pval(node, name):
    p = node.parm(name)
    return p.evalAsString() if p is not None else ""

def _set(node, name, value):
    p = node.parm(name)
    if p is not None:
        p.set(value)

def _status(node, msg):
    _set(node, "status_msg", msg)

def _upstream_shot(node):
    seen, todo = set(), [node]
    while todo:
        cur = todo.pop(0)
        if cur is None or cur.path() in seen:
            continue
        seen.add(cur.path())
        if cur is not node and cur.type().name().split("::")[0] == SHOT_TYPE:
            return cur
        ins = list(cur.inputs())
        if cur.type().name().split("::")[0] == "switch" and ins:
            try:
                ins = [ins[int(cur.evalParm("input"))]]
            except Exception:
                ins = ins[:1]
        todo.extend(i for i in ins if i is not None)
    return None

def _shot_node(node):
    path = _pval(node, "shot_node")
    n = hou.node(path) if path else None
    return n if n is not None else _upstream_shot(node)

def sync_shot(node):
    shot = _shot_node(node)
    if shot is None:
        _status(node, "Pas de FLUX Shot Import en amont : branche-en un ou remplis Shot Node")
        return None
    if not _pval(node, "shot_node"):
        _set(node, "shot_node", node.relativePathTo(shot))
    for name in ("project", "seq", "shot"):
        p = node.parm(name)
        if p is not None and shot.parm(name) is not None:
            p.setExpression('chs(chsop("shot_node") + "/%s")' % name, hou.exprLanguage.Hscript)
    for comp in ("x", "y"):
        p = node.parm("frame_range" + comp)
        if p is not None and shot.parm("frame_range" + comp) is not None:
            p.setExpression('ch(chsop("shot_node") + "/frame_range%s")' % comp, hou.exprLanguage.Hscript)
    _status(node, "Shot : %s %s" % (_pval(node, "seq"), _pval(node, "shot")))
    return shot

def _write_input_stage(node):
    """The input stage as a new file of the shot (ADR 0055 layout), never overwritten."""
    src = node.inputs()[0] if node.inputs() else None
    if src is None:
        raise RuntimeError("Rien n'est branche en entree")
    seq, shot = _pval(node, "seq"), _pval(node, "shot")
    folder = hou.text.expandString("$FLUX/DOSSIER_PROJETS/%s/shot/%s/%s/render/_stages"
                                   % (_pval(node, "project"), seq, shot))
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, "%s_%s_%s.usd" % (seq, shot, datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))
    rop = node.parent().createNode("usd_rop", "__flux_render_submit_export__")
    try:
        rop.parm("loppath").set(src.path())
        rop.parm("lopoutput").set(out)
        for name, value in (("striplayerbreaks", 1), ("savestyle", "flattenimplicitlayers"), ("trange", 0)):
            p = rop.parm(name)
            if p is not None:
                p.set(value)
        rop.parm("execute").pressButton()
        errors = rop.errors()
        if errors:
            raise RuntimeError("; ".join(errors))
    finally:
        rop.destroy()
    return out.replace("\\\\", "/")

def submit(node):
    if not _pval(node, "seq") or not _pval(node, "shot"):
        sync_shot(node)
    project, seq, shot = _pval(node, "project"), _pval(node, "seq"), _pval(node, "shot")
    if not (project and seq and shot):
        _status(node, "Shot inconnu : branche un FLUX Shot Import en amont")
        return
    body = {"project": project, "seq": seq, "shot": shot,
            "frame_start": node.evalParm("frame_rangex"), "frame_end": node.evalParm("frame_rangey"),
            "renderer": _pval(node, "renderer") or "karma", "freeze": bool(node.evalParm("freeze"))}
    if _pval(node, "source") == "input":
        _status(node, "Ecriture du stage d'entree...")
        try:
            body["usd_path"] = _write_input_stage(node)
        except Exception as exc:
            _status(node, "Ecriture du stage echouee : %s" % exc)
            return
    _status(node, "Envoi a la farm...")
    resp = _post("/render/submit", body)
    if resp.get("ok") is False:
        _status(node, "Envoi echoue : %s" % resp.get("error"))
        return
    warn = " (%d avertissement(s), voir l'onglet Tractor de FLUX)" % len(resp["warnings"]) if resp.get("warnings") else ""
    if resp.get("dry_run"):
        _status(node, "Simulation : job ecrit dans %s, rien n'est envoye%s" % (resp.get("output"), warn))
    else:
        _status(node, "Job %s envoye : %s%s" % (resp.get("jid"), resp.get("title"), warn))

def on_created(node):
    try:
        sync_shot(node)
    except Exception:
        pass

def on_loaded(node):
    pass
'''


def _build_code(hda_path: str) -> str:
    from dcc.houdini.hda.hda_common import FINALIZE as _finalize, ICON_PATH as icon_path
    from dcc.houdini.hda.preserve_instances import RESTORE, snapshot

    _snapshot = snapshot('hou.lopNodeTypeCategory()', NODE_NAME).replace("{{", "{").replace("}}", "}")
    return f'''
import hou
{_snapshot}

_HDA_PATH = {hda_path!r}
_ICON_PATH = {icon_path!r}
_NAME = {NODE_NAME!r}
_PY = hou.scriptLanguage.Python
_PM_CODE = {BOOTSTRAP!r}

def _btn(name, label, fn, help_txt=""):
    return hou.ButtonParmTemplate(name, label, script_callback="hou.phm().%s(kwargs['node'])" % fn,
                                  script_callback_language=_PY, help=help_txt)

_ptg = hou.ParmTemplateGroup()
_ptg.append(hou.StringParmTemplate("shot_node", "Shot Node", 1, default_value=("",),
                                   string_type=hou.stringParmType.NodeReference,
                                   help="FLUX Shot Import of this branch (empty = found upstream)"))
_ptg.append(_btn("btn_sync", "Relire le shot", "sync_shot", "Find the FLUX Shot Import upstream again"))
for _n, _l in (("project", "Projet"), ("seq", "Sequence"), ("shot", "Shot")):
    _t = hou.StringParmTemplate(_n, _l, 1, default_value=("",))
    _t.setConditional(hou.parmCondType.DisableWhen, '{{ shot_node != "" }}')
    _ptg.append(_t)
_ptg.append(hou.IntParmTemplate("frame_range", "Plage", 2, default_value=(1, 0)))
_ptg.append(hou.SeparatorParmTemplate("sep_farm"))
_ptg.append(hou.MenuParmTemplate("source", "Source", ("shot", "input"), ("Shot publie", "Entree LOP"),
                                 default_value=0,
                                 help="Shot publie: the published shot stage. Entree LOP: this node's input, written as a new file of the shot"))
_ptg.append(hou.MenuParmTemplate("renderer", "Moteur", ("karma", "renderman"), ("Karma", "RenderMan"),
                                 default_value=0))
_ptg.append(hou.ToggleParmTemplate("freeze", "Geler la version", default_value=True,
                                   help="Render frozen vNNN files, not LAST (a LAST can move during the render)"))
_ptg.append(_btn("btn_submit", "Envoyer sur la farm", "submit", "Send this shot to Tractor through FLUX"))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_render_submit_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_render_submit_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
_out.setInput(0, _sub.indirectInputs()[0])
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=1, max_num_inputs=1, version="1.0")
{_finalize}
{RESTORE}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Render Submit LOP HDA in the running Houdini."""
    log.info("Building FLUX Render Submit HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Render Submit HDA built: %s", hda_path)
    else:
        log.error("FLUX Render Submit HDA build failed: %s", resp.get("error"))
    return resp
