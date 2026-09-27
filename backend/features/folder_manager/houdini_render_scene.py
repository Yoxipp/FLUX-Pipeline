# houdini_render_scene.py — the default render scene of a sequence, shipped by FLUX.
#
# <SEQ>/usd/lighting/<SEQ>_render.hip (.hiplc / .hipnc per licence), built by code from an
# empty scene in an ISOLATED hython (never the artist's session: creating a usdrender ROP
# in a live Houdini crashed it once, ADR 0021). Nothing is loaded from disk, so there is
# no binary template to maintain and no machine path in the scene (ADR 0012).
# Made once, when the sequence is created, with 10 shots by default (2026-09-27); the
# layout is the one of the maintainer's hand-made render scene, cleaned of its test content.
#
# /stage
#   STRUCTURE                    scopes /asset/{env,char}, /lights, /cameras, /mtl, /Render
#   graft_env_seq   <- SEQUENCE_ENV     decor shared by every shot (merge_sequence_env above)
#   graft_light_seq <- SEQUENCE_LIGHTS  lights shared by every shot (merge_sequence_lights)
#   per shot, one column:
#     SHOT_<SH>            FLUX Shot (project / seq / shot / LAST): the shot stage
#     graft_lights_<SH>    <- OUT_LIGHTS_<SH>  lights of the shot; the FLUX Shot light_node
#                          points here so "Publier le light rig du shot" exports the lights
#                          only, never what comes below
#     graft_cameras_<SH>   <- OUT_CAMERAS_<SH>
#     graft_env_<SH>       <- OUT_ENV_<SH>
#     graft_char_<SH>      <- OUT_CHAR_<SH>
#     CRYPTO_<SH>          Karma Cryptomatte (objects + materials)
#     RENDER_SETTINGS_<SH> camera + images of FLUX Shot, project resolution, motion blur,
#                          AOVs + variance (denoise)
#     OUT_<SH>             end of the branch, rendered by the ROP
# /out
#   RENDER_<SEQ>_<SH>  USD Render (Karma) per shot, already linked to its FLUX Shot
#                      (render_rop): range, camera and images follow the node, so
#                      "Rendre ce shot" / "Rendre la sequence" work at once.
#
# The scene opens on the Solaris desktop, network editor in /stage (hou.session): /obj is
# empty, opening there looked like an empty scene.
#
# Idempotent: an existing render scene is never overwritten.

from __future__ import annotations

import json
import threading
from pathlib import Path

from core.logger import get_logger
from features.folder_manager.houdini_scene_template import (
    LIGHTING_SUBDIR,
    USD_SUBDIR,
    _run_offline,
    existing_hip,
)

log = get_logger(__name__)

# AOVs switched on in Karma Render Settings (toggle parm names, Houdini 22); __variance
# writes the variance AOVs the denoiser needs.
AOVS = ("beauty", "combineddiffuse", "combinedglossyreflection", "combinedemission",
        "albedo", "hitP", "hitPz", "hitN", "motionvectors", "__variance")
DEFAULT_RESOLUTION = (1920, 1080)
# Shot branches of a new sequence: SHOT001..SHOT010, plus any shot already made beyond.
DEFAULT_SHOT_COUNT = 10
# (branch, graft primpath, source prims): the grafts of each shot column, top to bottom.
GRAFTS = (("LIGHTS", "/lights", "/lights/*"), ("CAMERAS", "/cameras", "/cameras/*"),
          ("ENV", "/asset/env", "/*"), ("CHAR", "/asset/char", "/*"))
STRUCTURE_PRIMS = ("/asset", "/asset/env", "/asset/char", "/lights", "/cameras", "/mtl", "/Render")

# hou.session of the scene: open on Solaris, network editor in /stage.
SESSION_SOURCE = '''# FLUX: the render scene lives in /stage and /out, show /stage when it opens.
import hou


def _flux_show_stage():
    try:
        hou.ui.desktop("Solaris").setAsCurrent()
    except Exception:
        pass
    stage = hou.node("/stage")
    for pane in hou.ui.paneTabs():
        if stage is not None and pane.type() == hou.paneTabType.NetworkEditor:
            pane.setPwd(stage)


if hou.isUIAvailable():
    import hdefereval
    hdefereval.executeDeferred(_flux_show_stage)
'''


# Built-in preset of the Template Editor / New Scene menu (never stored in presets.json).
BUILTIN_PREFIX = "builtin:sequence_render:"


def builtin_presets(project_path: Path) -> list[dict]:
    """One read-only "Rendu de sequence" preset per sequence of the project (Houdini, SEQ).

    Launching it builds <SEQ>_render.hip when missing and opens the real scene."""
    out = []
    for seq in project_sequences(project_path):
        current = existing_hip(render_scene_base(project_path, seq))
        out.append({"id": BUILTIN_PREFIX + seq, "name": f"Rendu {seq}",
                    "file": current.name if current else f"{seq}_render.hip (a creer)",
                    "task": "SEQ", "soft": "houdini", "builtin": True, "exists": current is not None})
    return out


def open_builtin_preset(project_path: Path, preset_id: str) -> dict:
    """Scene to open for a built-in preset id: the sequence render scene, built if missing."""
    if not preset_id.startswith(BUILTIN_PREFIX):
        return {"ok": False, "error": f"Preset FLUX inconnu : {preset_id}"}
    return create_sequence_render_scene(project_path, preset_id[len(BUILTIN_PREFIX):])


def render_scene_base(project_path: Path, seq: str) -> Path:
    """<project>/shot/<SEQ>/usd/lighting/<SEQ>_render (no extension)."""
    seq = seq.upper()
    return Path(project_path) / "shot" / seq / USD_SUBDIR / LIGHTING_SUBDIR / f"{seq}_render"


def project_sequences(project_path: Path) -> list[str]:
    """SEQ tokens of the project plus the sequences of its SHOT tokens (a new sequence has
    no shot yet but already has its render scene)."""
    from features.folder_manager.tokens import load_tokens
    from features.importer.library_import import _stage_shots

    project_path = Path(project_path)
    seqs = {str(k).upper() for k in ((load_tokens(project_path) or {}).get("SEQ") or {})}
    seqs |= {seq for seq, _ in _stage_shots(project_path)}
    return sorted(seqs)


def sequence_shots(project_path: Path, seq: str) -> list[dict]:
    """Shots of the render scene of *seq*: SHOT001..SHOT010 plus the shots of the sequence
    (SHOT tokens), with the range / fps of their stage when it exists."""
    from features.folder_manager.naming_validator import format_shot
    from features.importer.library_import import _stage_shots
    from features.usd_assembler.shot_light import list_stage_shots

    seq = seq.upper()
    staged = {(s["seq"], s["shot"]): s for s in list_stage_shots(project_path)}
    names = {format_shot(n) for n in range(1, DEFAULT_SHOT_COUNT + 1)}
    names |= {shot for s_seq, shot in _stage_shots(Path(project_path)) if s_seq == seq}
    out = []
    for shot in sorted(names):
        info = staged.get((seq, shot)) or {}
        out.append({"shot": shot, "range": info.get("range"), "fps": info.get("fps"),
                    "has_stage": bool(info)})
    return out


def _resolution(project_path: Path) -> list[int]:
    from features.folder_manager.project_config import read_project_config

    res = (read_project_config(Path(project_path)) or {}).get("resolution")
    if isinstance(res, (list, tuple)) and len(res) == 2 and all(isinstance(v, int) and v > 0 for v in res):
        return list(res)
    return list(DEFAULT_RESOLUTION)


def build_plan(project_path: Path, seq: str) -> dict:
    """Everything the hython script needs, as plain JSON (tested without Houdini)."""
    return {
        "project": Path(project_path).name,
        "seq": seq.upper(),
        "shots": sequence_shots(project_path, seq),
        "resolution": _resolution(project_path),
        "aovs": list(AOVS),
        "grafts": [list(g) for g in GRAFTS],
        "structure": "\n".join(STRUCTURE_PRIMS),
        "session": SESSION_SOURCE,
    }


def _gen_script(plan: dict, dest_base: str) -> str:
    """Python run by hython: builds the scene from *plan*, saves dest_base + licence ext."""
    return f'''
import hou, json, os, traceback
plan = json.loads({json.dumps(json.dumps(plan))})
result = {{"ok": False}}


def graft(stage, name, main, branch, primpath, src):
    g = stage.createNode("graftbranches", name)
    g.setInput(0, main)
    g.setInput(1, branch)
    g.parm("primpath").set(primpath)
    g.parm("parentprimtype").set("UsdGeomScope")
    g.parm("srcprimpath1").set(src)
    g.parm("dstprimpath1").set("")
    return g


def out_branch(stage, label, comment, x, y):
    # merge (the artist wires content into it) -> null feeding the graft
    merge = stage.createNode("merge", "merge_" + label.lower())
    null = stage.createNode("null", label)
    null.setInput(0, merge)
    null.setComment(comment)
    null.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    merge.setPosition(hou.Vector2(x, y + 1.0))
    null.setPosition(hou.Vector2(x, y))
    return null


try:
    hou.hipFile.clear(suppress_save_prompt=True)
    stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
    out = hou.node("/out") or hou.node("/").createNode("ropnet", "out")
    seq, made = plan["seq"], []

    structure = stage.createNode("primitive", "STRUCTURE")
    structure.parm("primpath").set(plan["structure"])
    structure.parm("parentprimtype").set("UsdGeomScope")
    structure.parm("primtype").set("UsdGeomScope")
    structure.setPosition(hou.Vector2(0, 9))
    seq_env = out_branch(stage, "SEQUENCE_ENV", "Decor commun a toute la sequence", 3, 7.5)
    env_seq = graft(stage, "graft_env_seq", structure, seq_env, "/asset/env", "/*")
    env_seq.setPosition(hou.Vector2(0, 7))
    seq_lights = out_branch(stage, "SEQUENCE_LIGHTS", "Lumieres communes a tous les shots", 3, 5.5)
    common = graft(stage, "graft_light_seq", env_seq, seq_lights, "/lights", "/lights/*")
    common.setPosition(hou.Vector2(0, 5))

    for i, item in enumerate(plan["shots"]):
        sh = item["shot"]
        x = i * 7.0
        shot = stage.createNode("flux_shot", "SHOT_" + sh)
        shot.setInput(0, common)
        for pname, pval in (("project", plan["project"]), ("seq", seq), ("shot", sh), ("version", "LAST")):
            if shot.parm(pname) is not None:
                shot.parm(pname).set(pval)
        if item.get("range") and shot.parmTuple("frame_range") is not None:
            shot.parmTuple("frame_range").set(item["range"])
        if item.get("fps") and shot.parm("fps") is not None:
            shot.parm("fps").set(item["fps"])
        shot.setPosition(hou.Vector2(x, 3))
        prev, y = shot, 1.0
        for kind, primpath, src in plan["grafts"]:
            branch = out_branch(stage, "OUT_%s_%s" % (kind, sh),
                                "%s du shot %s" % (kind.capitalize(), sh), x + 3, y + 0.5)
            prev = graft(stage, "graft_%s_%s" % (kind.lower(), sh), prev, branch, primpath, src)
            prev.setPosition(hou.Vector2(x, y))
            if kind == "LIGHTS":
                # "Publier le light rig du shot" exports the layers down to here: lights only.
                shot.parm("light_node").set(prev.path())
            y -= 2.5
        crypto = stage.createNode("karmacryptomatte", "CRYPTO_" + sh)
        crypto.setInput(0, prev)
        for pname in ("doprimcrypto", "domtlcrypto"):
            if crypto.parm(pname) is not None:
                crypto.parm(pname).set(1)
        rs = stage.createNode("karmarendersettings", "RENDER_SETTINGS_" + sh)
        rs.setInput(0, crypto)
        me = shot.path()
        rs.parm("camera").setExpression('chs("%s/camera")' % me, hou.exprLanguage.Hscript)
        rs.parm("picture").set('`chs("%s/render_picture")`' % me)
        if rs.parm("res_mode") is not None:
            rs.parm("res_mode").set("manual")
        # "autoheight" leaves the height locked on an expression: a scripted switch to
        # manual does not free it, so a non 16:9 project got a computed height.
        for _p, _v in zip(rs.parmTuple("resolution"), plan["resolution"]):
            _p.lock(False)
            _p.deleteAllKeyframes()
            _p.set(_v)
        rs.parm("enablemblur").set(1)
        for aov in plan["aovs"]:
            if rs.parm(aov) is not None:
                rs.parm(aov).set(1)
        end = stage.createNode("null", "OUT_" + sh)
        end.setInput(0, rs)
        for j, n in enumerate((crypto, rs, end)):
            n.setPosition(hou.Vector2(x, y - j * 1.5))
        if i == 0:
            end.setDisplayFlag(True)
        rop = out.createNode("usdrender", "RENDER_%s_%s" % (seq, sh))
        rop.parm("loppath").set(end.path())
        if rop.parm("renderer") is not None:
            rop.parm("renderer").set("BRAY_HdKarma")
        rop.parm("trange").set(1)
        rop.parm("f1").setExpression('ch("%s/frame_rangex")' % me, hou.exprLanguage.Hscript)
        rop.parm("f2").setExpression('ch("%s/frame_rangey")' % me, hou.exprLanguage.Hscript)
        if rop.parm("override_camera") is not None:
            rop.parm("override_camera").setExpression('chs("%s/camera")' % me, hou.exprLanguage.Hscript)
        if rop.parm("outputimage") is not None:
            rop.parm("outputimage").set('`chs("%s/render_picture")`' % me)
        rop.setPosition(hou.Vector2(x, 0))
        shot.parm("render_rop").set(rop.path())
        made.append(sh)
    hou.setSessionModuleSource(plan["session"])
    for _var in ("JOB", "POSE"):
        hou.hscript("set -g %s = ''" % _var)
    _cat = hou.licenseCategory()
    _ext = ".hip" if _cat == hou.licenseCategoryType.Commercial \\
        else ".hiplc" if _cat == hou.licenseCategoryType.Indie else ".hipnc"
    _dest = {dest_base!r} + _ext
    os.makedirs(os.path.dirname(_dest), exist_ok=True)
    hou.hipFile.save(_dest)
    result = {{"ok": True, "path": _dest, "shots": made}}
except Exception as exc:
    result = {{"ok": False, "error": "%s\\n%s" % (exc, traceback.format_exc())}}
'''


def create_sequence_render_scene(project_path: Path, seq: str) -> dict:
    """Build <SEQ>_render.hip with one FLUX Shot column + ROP per shot of the sequence.

    Never overwrites: an existing scene is returned as is ({"created": False}).
    """
    project_path = Path(project_path)
    base = render_scene_base(project_path, seq)
    current = existing_hip(base)
    if current is not None:
        return {"ok": True, "created": False, "path": str(current)}
    plan = build_plan(project_path, seq)
    res = _run_offline(_gen_script(plan, str(base).replace("\\", "/")))
    if not res.get("ok"):
        log.warning("Render scene NOT generated for %s: %s", seq, res.get("error"))
        return {"ok": False, "error": res.get("error") or "hython"}
    log.info("Render scene generated: %s (%d shots)", res.get("path"), len(res.get("shots", [])))
    missing = [s["shot"] for s in plan["shots"] if not s["has_stage"]]
    return {"ok": True, "created": True, "path": res["path"], "shots": res.get("shots", []),
            "without_stage": missing}


_building: set[str] = set()
_building_lock = threading.Lock()


def create_sequence_render_scene_async(project_path: Path, seq: str) -> bool:
    """Build the render scene of a new sequence in the background (hython takes about a
    minute: sequence creation must not wait for it). False when one is already running."""
    key = str(render_scene_base(project_path, seq)).lower()
    with _building_lock:
        if key in _building:
            return False
        _building.add(key)

    def _run() -> None:
        try:
            create_sequence_render_scene(project_path, seq)
        except Exception as exc:  # noqa: BLE001 — a background build only logs
            log.warning("Render scene build failed for %s: %s", seq, exc)
        finally:
            with _building_lock:
                _building.discard(key)

    threading.Thread(target=_run, name=f"render_scene_{seq}", daemon=True).start()
    return True
