"""
FLUX - Houdini "FLUX Sequence" HDA for Solaris (2026-09-27).

The settings node at the top of a sequence render scene (above STRUCTURE): how many shot
branches the scene shows. "Appliquer" clones the block of the last shot as it is in the
scene (the maintainer's layout, ADR 0037): its backdrops shifted like the others, cameras / lights /
env / char branches, grafts, the SHOT_NNN null, the render chain CRYPTO -> RENDER_SETTINGS
-> FLUX Render and its ROP in /out. Everything stays visible and editable.

It never deletes a branch: a lower count only reports the extra shots (a shot removed by
mistake in Production must not take the lighting work of the scene with it).

Naming read from the scene: a shot block is every /stage node whose name holds SHOTnnn
(``cam_SHOT003``, ``graft_env_SHOT003``) or SHOT_nnn (the ``SHOT_003`` null), plus the
backdrop whose comment starts with SHOT and holds ``cam_SHOTnnn``.

The PythonModule is fetched from GET /dcc/houdini/flux_sequence/module (no rebuild on
fix); the scene generator (houdini_render_scene.py) runs the same code in hython.
"""

from __future__ import annotations

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

NODE_NAME = "flux_sequence"
LABEL = "FLUX Sequence"

BOOTSTRAP: str = '''
import json, os, urllib.request

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

def _load():
    with urllib.request.urlopen(f"http://127.0.0.1:{_flux_port()}/dcc/houdini/flux_sequence/module", timeout=3) as _r:
        exec(json.loads(_r.read())["code"], globals())

try:
    _load()
except Exception:
    def apply_shot_count(node):
        try:
            _load()
            apply_shot_count(node)
        except Exception:
            node.parm("status_msg").set("FLUX offline : demarre FLUX puis reessaie")
    def on_created(node): pass
    def on_loaded(node): pass
'''

# Served by GET /dcc/houdini/flux_sequence/module; also exec()'d by the render scene
# generator in hython. Pure hou, no FLUX call.
MODULE_FUNCTIONS: str = '''
import re
import hou

# Horizontal step between two shot blocks when the scene has a single one to measure.
DEFAULT_STEP = 30.0

def _status(node, msg):
    p = node.parm("status_msg")
    if p is not None:
        p.set(msg)

def _num_re(n):
    return re.compile(r"SHOT_?%03d(?!\\d)" % n)

def shot_numbers(stage):
    """Shot numbers present in /stage (SHOTnnn / SHOT_nnn in node names)."""
    found = set()
    for c in stage.children():
        for m in re.finditer(r"SHOT_?(\\d{3})(?!\\d)", c.name()):
            found.add(int(m.group(1)))
    return sorted(found)

def _block_nodes(stage, n):
    rx = _num_re(n)
    return [c for c in stage.children() if rx.search(c.name())]

def _shot_box(stage, n):
    """Backdrop of shot n: the smallest box commented SHOT* holding cam_SHOTnnn."""
    cam = stage.node("cam_SHOT%03d" % n)
    best = None
    for b in stage.networkBoxes():
        if not b.comment().upper().startswith("SHOT"):
            continue
        items = b.items()
        if cam is not None and cam in items:
            if best is None or len(items) < len(best.items()):
                best = b
    return best

def _sub_boxes(stage, box):
    return [b for b in stage.networkBoxes() if b is not box and b in box.items()]

def _retarget_parms(node, src, dst):
    """SHOTsrc -> SHOTdst in the node's string parms and expressions."""
    a, b = "SHOT%03d" % src, "SHOT%03d" % dst
    a2, b2 = "SHOT_%03d" % src, "SHOT_%03d" % dst
    for p in node.parms():
        try:
            try:
                expr = p.expression()
                new = expr.replace(a, b).replace(a2, b2)
                if new != expr:
                    p.setExpression(new, p.expressionLanguage())
                continue
            except hou.OperationFailed:
                pass
            if p.parmTemplate().type() != hou.parmTemplateType.String:
                continue
            raw = p.unexpandedString()
            new = raw.replace(a, b).replace(a2, b2)
            if new != raw:
                p.set(new)
        except Exception:
            pass

def _step(stage, src):
    """Horizontal distance between two shot blocks, measured on the scene."""
    here, prev = _shot_box(stage, src), _shot_box(stage, src - 1)
    if here is not None and prev is not None:
        d = here.position()[0] - prev.position()[0]
        if abs(d) > 1e-3:
            return d
    return DEFAULT_STEP

def _outer_boxes(stage, nodes, shot_box):
    """Big boxes (SEQUENCE, RENDER...) holding the source block: the clones join them."""
    out = []
    for b in stage.networkBoxes():
        if b is shot_box or (shot_box is not None and b in _sub_boxes(stage, shot_box)):
            continue
        if any(n in b.items() for n in nodes) and not b.comment().upper().startswith("SHOT"):
            out.append(b)
    return out

def grow_box(box, margin=0.6):
    """Enlarge *box* to hold every item it contains (nested boxes included). Never shrinks
    the artist's layout (fitAroundContents did, and ignored the nested boxes)."""
    x0, y0 = box.position()[0], box.position()[1]
    x1, y1 = x0 + box.size()[0], y0 + box.size()[1]
    for item in box.items():
        try:
            px, py = item.position()[0], item.position()[1]
            sx, sy = item.size()[0], item.size()[1]
        except Exception:
            continue
        x0, y0 = min(x0, px - margin), min(y0, py - margin)
        x1, y1 = max(x1, px + sx + margin), max(y1, py + sy + margin)
    # setBounds, not setPosition: moving a box moves everything inside it.
    box.setBounds(hou.BoundingRect(x0, y0, x1, y1))

def clone_shot(stage, src, dst):
    """Copy the block of shot *src* as shot *dst*, shifted right like the others."""
    nodes = _block_nodes(stage, src)
    if not nodes:
        raise RuntimeError("pas de bloc SHOT%03d a copier" % src)
    box = _shot_box(stage, src)
    boxes = ([box] + _sub_boxes(stage, box)) if box is not None else []
    dx = _step(stage, src) * (dst - src)
    outer = _outer_boxes(stage, nodes, box)
    # Node by node: the old -> new pairing is exact (copyItems does not keep the order).
    rx = _num_re(src)
    by_old = {}
    for old in nodes:
        new = hou.copyNodesTo([old], stage)[0]
        name = rx.sub(lambda m: m.group(0).replace("%03d" % src, "%03d" % dst), old.name())
        try:
            new.setName(name, unique_name=True)
        except Exception:
            pass
        new.setPosition(old.position() + hou.Vector2(dx, 0))
        by_old[old.path()] = new
    # Wiring like the source: inside the block to the copies, outside (the sequence
    # grafts) to the same nodes; a node fed by every block (switch, merge) gets the copy
    # on its next input.
    for old in nodes:
        new = by_old[old.path()]
        for i, inp in enumerate(old.inputs()):
            if inp is not None:
                new.setInput(i, by_old.get(inp.path(), inp))
        for out in old.outputs():
            if out.path() not in by_old and out.type().name().split("::")[0] in ("switch", "merge"):
                out.setNextInput(new)
        _retarget_parms(new, src, dst)
    # Backdrops: same size and colour, shifted; nested boxes stay nested.
    new_boxes = {}
    for old in boxes:
        nb = stage.createNetworkBox()
        nb.setComment("SHOT_%03d" % dst if old is box else old.comment())
        nb.setColor(old.color())
        nb.setPosition(old.position() + hou.Vector2(dx, 0))
        nb.setSize(old.size())
        new_boxes[old.name()] = nb
    for old in boxes:
        nb = new_boxes[old.name()]
        for item in old.items():
            if isinstance(item, hou.NetworkBox) and item.name() in new_boxes:
                nb.addItem(new_boxes[item.name()])
            elif isinstance(item, hou.Node) and item.path() in by_old:
                nb.addItem(by_old[item.path()])
        nb.setPosition(old.position() + hou.Vector2(dx, 0))
        nb.setSize(old.size())
    # An item belongs to one box only: each copy joins the innermost big box (SEQUENCE,
    # RENDER...) that held its original, nothing already inside the new shot backdrop.
    in_shot = set(box.items()) if box is not None else set()

    def _innermost(item):
        holders = [b for b in outer if item in b.items()]
        return min(holders, key=lambda b: len(b.items())) if holders else None

    moved = []
    if box is not None and box.name() in new_boxes:
        moved.append((box, new_boxes[box.name()]))
    moved += [(old, by_old[old.path()]) for old in nodes if old not in in_shot]
    touched = set()
    for old, new in moved:
        holder = _innermost(old)
        if holder is not None:
            holder.addItem(new)
            touched.add(holder.name())
    if touched:
        # Inner boxes first: RENDER holds SEQUENCE, it grows after SEQUENCE did.
        for b in sorted(outer, key=lambda b: len(b.items())):
            grow_box(b)
    return list(by_old.values())

def _find(stage, prefix, n):
    return stage.node("%s%03d" % (prefix, n))

def ensure_render_chain(stage, n, project="", seq="", frame_range=None):
    """CRYPTO -> RENDER_SETTINGS -> FLUX Render for shot n (one render chain per
    shot). An existing chain is kept; missing pieces are copied from shot 1's."""
    fr = _find(stage, "FLUX_RENDER_SHOT", n)
    if fr is not None:
        return fr
    rs = _find(stage, "RENDER_SETTINGS_SHOT", n)
    if rs is None:
        head = stage.node("SHOT_%03d" % n)
        if head is None:
            raise RuntimeError("pas de null SHOT_%03d" % n)
        crypto = _find(stage, "CRYPTO_SHOT", n)
        if crypto is None:
            model = _find(stage, "CRYPTO_SHOT", 1)
            crypto = (stage.copyItems([model])[0] if model is not None
                      else stage.createNode("karmacryptomatte"))
            crypto.setName("CRYPTO_SHOT%03d" % n, unique_name=True)
        crypto.setInput(0, head)
        crypto.setPosition(head.position() + hou.Vector2(0, -1.5))
        model = _find(stage, "RENDER_SETTINGS_SHOT", 1)
        rs = stage.copyItems([model])[0] if model is not None else stage.createNode("karmarendersettings")
        rs.setName("RENDER_SETTINGS_SHOT%03d" % n, unique_name=True)
        rs.setInput(0, crypto)
        rs.setPosition(crypto.position() + hou.Vector2(0, -1.5))
    if rs.parm("camera") is not None:
        rs.parm("camera").set("/cameras/cam_SHOT%03d" % n)
    # Beside what already hangs under the settings (shot 1: the maintainer's renderpass).
    side = -2.5 if rs.outputs() else 0.0
    fr = stage.createNode("flux_render", "FLUX_RENDER_SHOT%03d" % n)
    fr.setInput(0, rs)
    fr.setPosition(rs.position() + hou.Vector2(side, -1.5))
    for name, value in (("project", project), ("seq", seq), ("shot", "SHOT%03d" % n)):
        if value and fr.parm(name) is not None:
            fr.parm(name).set(value)
    if frame_range and fr.parmTuple("frame_range") is not None:
        fr.parmTuple("frame_range").set(tuple(int(v) for v in frame_range))
    if rs.parm("picture") is not None:
        rs.parm("picture").set('`chs("%s/render_picture")`' % fr.path())
    return fr

def link_rop(fr, seq):
    """The ROP of a FLUX Render: the usdrender_rop LOP wired under it in /stage (the maintainer's
    render scene, 2026-09-28), else /out/RENDER_<SEQ>_SHOTnnn, created when missing."""
    rop = next((o for o in fr.outputs() if o.type().name().split("::")[0] in ("usdrender_rop", "usdrender")), None)
    if rop is None:
        shot = fr.name().replace("FLUX_RENDER_", "")
        out = hou.node("/out") or hou.node("/").createNode("ropnet", "out")
        rop = out.node("RENDER_%s_%s" % (seq, shot)) if seq else None
        if rop is None:
            rop = out.createNode("usdrender", "RENDER_%s_%s" % (seq or "SEQ", shot))
    me = fr.path()
    if rop.parent() != fr.parent() and rop.parm("loppath") is not None:
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
    if fr.parm("render_rop") is not None:
        fr.parm("render_rop").set(rop.path())
    return rop

def grow_to(stage, count, project="", seq="", ranges=None):
    """Shot blocks 1..count: clone the last one until there are enough, and give each
    shot its render chain. Never deletes. Returns (added, extra) shot numbers."""
    ranges = ranges or {}
    have = shot_numbers(stage)
    if not have:
        raise RuntimeError("aucun bloc SHOTnnn dans /stage a dupliquer")
    added = []
    last = max(have)
    for n in range(1, count + 1):
        if n in have:
            continue
        clone_shot(stage, last, n)
        # A clone of a finished block carries its render chain: point it at its shot.
        fr = _find(stage, "FLUX_RENDER_SHOT", n)
        if fr is not None and fr.parm("shot") is not None and not fr.parm("shot_node").eval():
            fr.parm("shot").set("SHOT%03d" % n)
        added.append(n)
        last = n
    for n in shot_numbers(stage):
        if n > count:
            continue
        fr = ensure_render_chain(stage, n, project, seq, ranges.get("SHOT%03d" % n))
        link_rop(fr, seq)
    extra = [n for n in shot_numbers(stage) if n > count]
    return added, extra

def _block_shot(stage, n):
    fr = _find(stage, "FLUX_RENDER_SHOT", n)
    p = fr.parm("shot") if fr is not None else None
    return p.evalAsString().strip().upper() if p is not None else ""

def _block_range(stage, n):
    fr = _find(stage, "FLUX_RENDER_SHOT", n)
    try:
        rng = (int(fr.evalParm("frame_rangex")), int(fr.evalParm("frame_rangey")))
    except Exception:
        return None
    return rng if rng[1] >= rng[0] else None

def name_new_blocks(stage, added, default_start=1001, default_length=50):
    """Blocks added by hand (Nombre de shots): a clone still points at the shot it was
    copied from, so a Save of the render Work saw nothing new. Each one gets the next
    shot name of the FLUX convention (next ten, 4 digits: SHOT0040, as Production's New
    shot) and a range right after the previous block, same length, as plain values:
    the Save then offers to create the shot in Production (render_sync)."""
    used, nums = set(), []
    for n in shot_numbers(stage):
        if n in added:
            continue
        name = _block_shot(stage, n)
        m = re.match(r"SHOT_?(\\d+)$", name)
        if name:
            used.add(name)
        if m:
            nums.append(int(m.group(1)))
    last = max(nums) if nums else 0
    named = []
    for n in sorted(added):
        k = (last // 10 + 1) * 10
        while "SHOT%04d" % k in used:
            k += 10
        name = "SHOT%04d" % k
        last = k
        used.add(name)
        for prefix in ("IMPORT_ENV_SHOT", "IMPORT_CHAR_SHOT", "FLUX_RENDER_SHOT"):
            block = _find(stage, prefix, n)
            if block is not None and block.parm("shot") is not None:
                block.parm("shot").set(name)
        before = [b for b in shot_numbers(stage) if b < n]
        prev = _block_range(stage, before[-1]) if before else None
        if prev:
            rng = (prev[1] + 1, prev[1] + prev[1] - prev[0] + 1)
        else:
            rng = (default_start, default_start + default_length - 1)
        fr = _find(stage, "FLUX_RENDER_SHOT", n)
        for comp, value in zip(("x", "y"), rng):
            p = fr.parm("frame_range" + comp) if fr is not None else None
            if p is not None:
                p.deleteAllKeyframes()
                p.set(int(value))
        named.append(name)
    return named

def apply_shot_count(node):
    stage = node.parent()
    count = int(node.evalParm("shot_count"))
    try:
        added, extra = grow_to(stage, count, node.evalParm("project"), node.evalParm("seq"))
        named = name_new_blocks(stage, added) if added else []
    except Exception as exc:
        _status(node, "Impossible : %s" % exc); return
    msg = "%d shot(s)" % count
    if added:
        msg += ", ajoutes : " + ", ".join("SHOT%03d = %s" % (n, s) for n, s in zip(added, named))
        msg += " (Sauver le Work RENDER pour les creer dans FLUX)"
    if extra:
        msg += "  |  en trop (gardes, a supprimer a la main) : " + ", ".join("SHOT%03d" % n for n in extra)
    _status(node, msg)

def on_created(node):
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

_ptg = hou.ParmTemplateGroup()
_ptg.append(hou.StringParmTemplate("project", "Projet", 1, default_value=("",)))
_ptg.append(hou.StringParmTemplate("seq", "Sequence", 1, default_value=("",)))
_ptg.append(hou.IntParmTemplate("shot_count", "Nombre de shots", 1, default_value=(3,), min=1, max=200,
                                help="Shot blocks shown in the scene; a new one is a copy of the last"))
_ptg.append(hou.ButtonParmTemplate("btn_apply", "Appliquer",
                                   script_callback="hou.phm().apply_shot_count(kwargs['node'])",
                                   script_callback_language=_PY,
                                   help="Adds the missing shot blocks. Never deletes one."))
_ptg.append(hou.StringParmTemplate("status_msg", "Statut", 1, default_value=("",)))

_stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
_old = _stage.node("__flux_sequence_build__")
if _old is not None:
    _old.destroy()
_sub = _stage.createNode("subnet", "__flux_sequence_build__")
for _c in _sub.children():
    if _c.type().name() != "output":
        _c.destroy()
_out = next((c for c in _sub.children() if c.type().name() == "output"), None) \\
    or _sub.createNode("output", "output0")
_out.setInput(0, _sub.indirectInputs()[0])
_sub.layoutChildren()

_asset = _sub.createDigitalAsset(name=_NAME, hda_file_name=_HDA_PATH, description={LABEL!r},
                                 min_num_inputs=0, max_num_inputs=1, version="1.0")
{_finalize}
{RESTORE}
result = {{"ok": True, "path": _HDA_PATH, "node_type": "Lop/" + _NAME}}
'''


def build_hda(hda_path: str) -> dict:
    """Build the FLUX Sequence LOP HDA in the running Houdini."""
    log.info("Building FLUX Sequence HDA -> %s", hda_path)
    resp = houdini_client.run(_build_code(hda_path))
    if resp.get("ok"):
        log.info("FLUX Sequence HDA built: %s", hda_path)
    else:
        log.error("FLUX Sequence HDA build failed: %s", resp.get("error"))
    return resp
