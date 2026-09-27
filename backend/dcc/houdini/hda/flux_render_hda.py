"""
FLUX - Houdini "FLUX Render" HDA for Solaris (2026-09-27).

The end of a shot branch in a render scene, placed under the Karma Render Settings: it
passes the stage through and renders it. The render buttons lived on FLUX Shot, at the top
of the branch ("pourquoi rendre ce shot est dans le flux shot alors qu'il est en haut
de l'arbre"); they are here now, where the render happens.

  * the shot (project / sequence / shot, frame range, camera) comes from the FLUX Shot
    Import found upstream (through a switch, its active input), or from ``shot_node``;
  * ``render_picture``: images of the shot, beside the scene;
  * "Creer le ROP du shot": the usdrender_rop LOP wired under this node in /stage when
    there is one (the maintainer's render scene, 2026-09-28), else a USD Render ROP in /out rendering
    THIS node; frame range / camera / images follow the node;
  * "Rendre ce shot", "Rendre la sequence" (every FLUX Render of the same sequence, one
    after the other, a failure never stops the others).

Same bootstrap as FLUX Shot: the HDA holds a few lines that fetch the real module from
GET /dcc/houdini/flux_render/module, so a fix needs no HDA rebuild.
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_render"
LABEL = "FLUX Render"
# Output of the shot render: <project>/render/<SEQ>/<SHOT>/ (2026-09-28), $FLUX = the
# workspace (flux.json package), projects under DOSSIER_PROJETS.
RENDER_PICTURE = ('$FLUX/DOSSIER_PROJETS/`chs("project")`/render/`chs("seq")`/`chs("shot")`/'
                  '`chs("seq")`_`chs("shot")`.$F4.exr')

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/flux_render/module", timeout=3) as _r:
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
    def create_render_rop(node): _offline(node, "create_render_rop")
    def render_shot(node): _offline(node, "render_shot")
    def render_sequence(node): _offline(node, "render_sequence")
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Served by GET /dcc/houdini/flux_render/module, exec()'d by the bootstrap (runs inside Houdini).
# Needs no FLUX call: everything is read from the scene (the upstream FLUX Shot Import).
MODULE_FUNCTIONS: str = '''
import hou

SHOT_TYPE = "flux_shot"

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
    """The FLUX Shot Import feeding this branch: breadth first up the inputs; a switch
    only follows its active input (several shots side by side, ADR 0023)."""
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
    """Point the node at its FLUX Shot Import: shot_node, and seq / shot / range / camera
    follow it by expression (a shot change upstream follows by itself)."""
    shot = _shot_node(node)
    if shot is None:
        _status(node, "Pas de FLUX Shot Import en amont : branche-en un ou remplis Shot Node")
        return None
    rel = node.relativePathTo(shot)
    if not _pval(node, "shot_node"):
        _set(node, "shot_node", rel)
    for name in ("project", "seq", "shot", "camera"):
        p = node.parm(name)
        if p is not None and shot.parm(name) is not None:
            p.setExpression('chs(chsop("shot_node") + "/%s")' % name, hou.exprLanguage.Hscript)
    for comp in ("x", "y"):
        p = node.parm("frame_range" + comp)
        if p is not None and shot.parm("frame_range" + comp) is not None:
            p.setExpression('ch(chsop("shot_node") + "/frame_range%s")' % comp, hou.exprLanguage.Hscript)
    _status(node, "Shot : %s %s" % (_pval(node, "seq"), _pval(node, "shot")))
    return shot

def _tag(node):
    return "%s_%s" % (_pval(node, "seq"), _pval(node, "shot"))

def _stage_rop(node):
    """A usdrender_rop LOP wired right under this node (render scene layout)."""
    for out in node.outputs():
        if out.type().name().split("::")[0] in ("usdrender_rop", "usdrender"):
            return out
    return None

def create_render_rop(node):
    """One USD Render ROP (Karma) per shot, rendering this node (range, camera, images)."""
    if sync_shot(node) is None:
        return
    if not (_pval(node, "seq") and _pval(node, "shot")):
        _status(node, "Le FLUX Shot Import en amont n'a pas de sequence / shot"); return
    rop = hou.node(_pval(node, "render_rop")) if _pval(node, "render_rop") else None
    if rop is None:
        rop = _stage_rop(node)
    if rop is None:
        # Creating a render ROP in a live session crashed Houdini once (ADR 0021, 0029):
        # save first so nothing is lost.
        try:
            if hou.hipFile.hasUnsavedChanges() and not hou.hipFile.isNewFile():
                hou.hipFile.save()
        except Exception as exc:
            _status(node, "Sauvegarde impossible avant le ROP : %s" % exc); return
        out = hou.node("/out") or hou.node("/").createNode("ropnet", "out")
        rop = out.createNode("usdrender", "RENDER_" + _tag(node))
    link_rop(node, rop)
    _status(node, "ROP %s : rend %s" % (rop.path(), node.path()))

def link_rop(node, rop):
    me = node.path()
    # A ROP inside the LOP network renders its input: no loppath to set.
    if rop.parent() != node.parent() and rop.parm("loppath") is not None:
        rop.parm("loppath").set(me)
    if rop.parm("renderer") is not None:
        rop.parm("renderer").set("BRAY_HdKarma")
    rop.parm("trange").set(1)
    rop.parm("f1").setExpression('ch("%s/frame_rangex")' % me, hou.exprLanguage.Hscript)
    rop.parm("f2").setExpression('ch("%s/frame_rangey")' % me, hou.exprLanguage.Hscript)
    if rop.parm("override_camera") is not None:
        rop.parm("override_camera").setExpression('chs("%s/camera")' % me, hou.exprLanguage.Hscript)
    if rop.parm("outputimage") is not None:
        rop.parm("outputimage").set('`chs("%s/render_picture")`' % me)
    _set(node, "render_rop", rop.path())

def _render(node):
    """Render one shot with its own ROP and range. "" when done, else why not."""
    if not _pval(node, "shot_node") and _upstream_shot(node) is not None:
        # A FLUX Shot Import put at the top of the branch after this node was made.
        sync_shot(node)
    rop = hou.node(_pval(node, "render_rop")) if _pval(node, "render_rop") else None
    if rop is None and _stage_rop(node) is not None:
        rop = _stage_rop(node)
        link_rop(node, rop)
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
    _status(node, ("Rendu %s termine" % _tag(node)) if not err else "Rendu impossible : " + err)

def _sequence_nodes(node):
    """Every FLUX Render of the scene on the same project and sequence, in shot order."""
    same = [n for n in node.type().instances()
            if _pval(n, "project") == _pval(node, "project") and _pval(n, "seq") == _pval(node, "seq")]
    return sorted(same, key=lambda n: _pval(n, "shot"))

def render_sequence(node):
    done, failed = [], []
    for n in _sequence_nodes(node):
        err = _render(n)
        if err:
            failed.append("%s (%s)" % (_pval(n, "shot"), err))
        else:
            done.append(_pval(n, "shot"))
    msg = "Sequence %s : %d shot(s) rendu(s)" % (_pval(node, "seq"), len(done))
    if failed:
        msg += ", non rendus : " + ", ".join(failed)
    _status(node, msg)

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
# Read from the FLUX Shot Import by expression (sync_shot): shown, not edited here.
for _n, _l in (("project", "Projet"), ("seq", "Sequence"), ("shot", "Shot"), ("camera", "Camera")):
    _t = hou.StringParmTemplate(_n, _l, 1, default_value=("",))
    _t.setConditional(hou.parmCondType.DisableWhen, '{{ shot_node != "" }}')
    _ptg.append(_t)
_rng = hou.IntParmTemplate("frame_range", "Plage", 2, default_value=(1, 0))
_rng.setConditional(hou.parmCondType.DisableWhen, '{{ shot_node != "" }}')
_ptg.append(_rng)
_ptg.append(hou.SeparatorParmTemplate("sep_render"))
_ptg.append(hou.StringParmTemplate("render_picture", "Images du shot", 1, default_value=({RENDER_PICTURE!r},),
                                   string_type=hou.stringParmType.FileReference,
                                   help="Output of this shot's render ROP"))
_ptg.append(hou.StringParmTemplate("render_rop", "ROP du shot", 1, default_value=("",),
                                   string_type=hou.stringParmType.NodeReference,
                                   help="USD Render ROP of this shot (created by the button)"))
_ptg.append(_btn("btn_render_rop", "Creer le ROP du shot", "create_render_rop",
                 "Karma ROP rendering this node (range, camera, images)"))
_ptg.append(_btn("btn_render_shot", "Rendre ce shot", "render_shot"))
_ptg.append(_btn("btn_render_seq", "Rendre la sequence", "render_sequence",
                 "Every FLUX Render of this sequence in the scene, one after the other"))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_render_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_render_build__")
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
    """Build the FLUX Render LOP HDA in the running Houdini."""
    log.info("Building FLUX Render HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Render HDA built: %s", hda_path)
    else:
        log.error("FLUX Render HDA build failed: %s", resp.get("error"))
    return resp
