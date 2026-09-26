# houdini_render_scene.py — the default render scene of a sequence, shipped by FLUX.
#
# <SEQ>/usd/lighting/<SEQ>_render.hip (.hiplc / .hipnc per licence), built by code from an
# empty scene in an ISOLATED hython (never the artist's session: creating a usdrender ROP
# in a live Houdini crashed it once, ADR 0021). Nothing is loaded from disk, so there is
# no binary template to maintain and no machine path in the scene (ADR 0012).
#
# /stage
#   COMMON_LIGHTS                    lights shared by every shot go above this null
#   └─ per shot, side by side:
#      SHOT_<SH>        FLUX Shot (project / seq / shot / LAST, range + fps of the stage)
#      SHOT_LIGHTS_<SH> lights of this shot go between FLUX Shot and this null; the node's
#                       light_node points here so "Publier le light rig du shot" exports
#                       the lights only, never the render settings below
#      CRYPTO_<SH>      Karma Cryptomatte (objects + materials)
#      RENDER_SETTINGS_<SH>  Karma Render Settings: camera + images of FLUX Shot, project
#                       resolution, motion blur, AOVs
#      OUT_<SH>         end of the branch, rendered by the ROP
# /out
#   RENDER_<SEQ>_<SH>  USD Render (Karma) per shot, already linked to its FLUX Shot
#                      (render_rop): range, camera and images follow the node, so
#                      "Rendre ce shot" / "Rendre la sequence" work at once.
#
# Idempotent: an existing render scene is never overwritten.

from __future__ import annotations

import json
from pathlib import Path

from core.logger import get_logger
from features.folder_manager.houdini_scene_template import (
    LIGHTING_SUBDIR,
    USD_SUBDIR,
    _run_offline,
    existing_hip,
)

log = get_logger(__name__)

# AOVs switched on in Karma Render Settings (toggle parm names, Houdini 22).
AOVS = ("beauty", "combineddiffuse", "combinedglossyreflection", "combinedemission",
        "albedo", "hitP", "hitPz", "hitN", "motionvectors")
DEFAULT_RESOLUTION = (1920, 1080)


# Built-in preset of the Template Editor / New Scene menu (never stored in presets.json).
BUILTIN_PREFIX = "builtin:sequence_render:"


def builtin_presets(project_path: Path) -> list[dict]:
    """One read-only "Rendu de sequence" preset per sequence of the project (Houdini, SEQ).

    Launching it builds <SEQ>_render.hip when missing and opens the real scene."""
    from features.importer.library_import import _stage_shots

    seqs = sorted({seq for seq, _ in _stage_shots(Path(project_path))})
    out = []
    for seq in seqs:
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


def sequence_shots(project_path: Path, seq: str) -> list[dict]:
    """Shots of *seq* (SHOT tokens), with the range / fps of their stage when it exists."""
    from features.importer.library_import import _stage_shots
    from features.usd_assembler.shot_light import list_stage_shots

    seq = seq.upper()
    staged = {(s["seq"], s["shot"]): s for s in list_stage_shots(project_path)}
    out = []
    for s_seq, shot in _stage_shots(Path(project_path)):
        if s_seq != seq:
            continue
        info = staged.get((s_seq, shot)) or {}
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
    }


def _gen_script(plan: dict, dest_base: str) -> str:
    """Python run by hython: builds the scene from *plan*, saves dest_base + licence ext."""
    return f'''
import hou, json, os, traceback
plan = json.loads({json.dumps(json.dumps(plan))})
result = {{"ok": False}}
try:
    hou.hipFile.clear(suppress_save_prompt=True)
    stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
    out = hou.node("/out") or hou.node("/").createNode("ropnet", "out")
    common = stage.createNode("null", "COMMON_LIGHTS")
    common.setComment("Lumieres communes a tous les shots : les poser au-dessus de ce node")
    common.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    common.setPosition(hou.Vector2(0, 2))
    seq, made = plan["seq"], []
    for i, item in enumerate(plan["shots"]):
        sh = item["shot"]
        x = i * 5.0
        shot = stage.createNode("flux_shot", "SHOT_" + sh)
        shot.setInput(0, common)
        for pname, pval in (("project", plan["project"]), ("seq", seq), ("shot", sh), ("version", "LAST")):
            if shot.parm(pname) is not None:
                shot.parm(pname).set(pval)
        if item.get("range") and shot.parmTuple("frame_range") is not None:
            shot.parmTuple("frame_range").set(item["range"])
        if item.get("fps") and shot.parm("fps") is not None:
            shot.parm("fps").set(item["fps"])
        lights = stage.createNode("null", "SHOT_LIGHTS_" + sh)
        lights.setInput(0, shot)
        lights.setComment("Lumieres du shot %s : entre SHOT_%s et ce node" % (sh, sh))
        lights.setGenericFlag(hou.nodeFlag.DisplayComment, True)
        shot.parm("light_node").set(lights.path())
        crypto = stage.createNode("karmacryptomatte", "CRYPTO_" + sh)
        crypto.setInput(0, lights)
        for pname in ("doprimcrypto", "domtlcrypto"):
            if crypto.parm(pname) is not None:
                crypto.parm(pname).set(1)
        rs = stage.createNode("karmarendersettings", "RENDER_SETTINGS_" + sh)
        rs.setInput(0, crypto)
        me = shot.path()
        rs.parm("camera").setExpression('chs("%s/camera")' % me, hou.exprLanguage.Hscript)
        rs.parm("picture").set('`chs("%s/render_picture")`' % me)
        rs.parmTuple("resolution").set(plan["resolution"])
        if rs.parm("res_mode") is not None:
            rs.parm("res_mode").set("manual")
        rs.parm("enablemblur").set(1)
        for aov in plan["aovs"]:
            if rs.parm(aov) is not None:
                rs.parm(aov).set(1)
        end = stage.createNode("null", "OUT_" + sh)
        end.setInput(0, rs)
        for j, n in enumerate((shot, lights, crypto, rs, end)):
            n.setPosition(hou.Vector2(x, -j * 1.5))
        end.setDisplayFlag(True) if i == 0 else None
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
    """Build <SEQ>_render.hip with one FLUX Shot branch + ROP per shot of the sequence.

    Never overwrites: an existing scene is returned as is ({"created": False}).
    """
    project_path = Path(project_path)
    base = render_scene_base(project_path, seq)
    current = existing_hip(base)
    if current is not None:
        return {"ok": True, "created": False, "path": str(current)}
    plan = build_plan(project_path, seq)
    if not plan["shots"]:
        return {"ok": False, "error": f"Aucun shot dans la sequence {seq.upper()}"}
    res = _run_offline(_gen_script(plan, str(base).replace("\\", "/")))
    if not res.get("ok"):
        log.warning("Render scene NOT generated for %s: %s", seq, res.get("error"))
        return {"ok": False, "error": res.get("error") or "hython"}
    log.info("Render scene generated: %s (%d shots)", res.get("path"), len(res.get("shots", [])))
    missing = [s["shot"] for s in plan["shots"] if not s["has_stage"]]
    return {"ok": True, "created": True, "path": res["path"], "shots": res.get("shots", []),
            "without_stage": missing}
