# houdini_render_scene.py — the default render scene of a sequence, shipped by FLUX.
#
# <SEQ>/usd/lighting/<SEQ>_render.hip (.hiplc / .hipnc per licence), made in an ISOLATED
# hython (never the artist's session: creating a usdrender ROP in a live Houdini crashed it
# once, ADR 0021).
#
# ADR 0037 (2026-09-27, replaces the built-by-code layout of ADR 0036 points 1 and 6):
# the scene IS the maintainer's render scene, shipped as resources/scenes/houdini/
# flux_template_sequence_render.hip and kept as it is (backdrops, test content, switch,
# renderpass). FLUX only adds:
#   * FLUX Sequence (settings, top of the tree, feeds STRUCTURE): the number of shot
#     blocks; "Appliquer" copies the last block, shifted like the others, never deletes;
#   * per shot block, the render chain CRYPTO_SHOTnnn -> RENDER_SETTINGS_SHOTnnn ->
#     FLUX_RENDER_SHOTnnn (copied from shot 1's; shot 1 keeps the maintainer's chain after the
#     switch) and its ROP /out/RENDER_<SEQ>_SHOTnnn;
#   * the project resolution on every Render Settings, the sequence name on the ROPs.
# The shot blocks are slots (SHOT001, SHOT002...): the artist puts a FLUX Shot Import at
# the top of a branch to load a shot, FLUX Render follows it.
#
# The scene opens on the Solaris desktop, network editor in /stage (hou.session).
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

DEFAULT_RESOLUTION = (1920, 1080)
# the maintainer's render scene (ADR 0037), copied as the start of every sequence render scene.
TEMPLATE = (Path(__file__).parent.parent.parent / "resources" / "scenes" / "houdini"
            / "flux_template_sequence_render.hip")
# The template's own sequence name (its /out ROPs), renamed to the real sequence.
TEMPLATE_SEQ = "SEQ001"
# Shot blocks of a new scene: the template's 3, more when the sequence already has more.
MIN_SHOT_BLOCKS = 3
# HDAs the generator places: missing ones mean the Shelf Manager rebuild was not done.
REQUIRED_TYPES = ("flux_render", "flux_sequence", "flux_shot")
# A type installed but older than the template needs: rebuilt (FLUX Shot Import "Contenu").
REQUIRED_PARMS = {"flux_shot": "content"}

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
TEMPLATE_PRESET_ID = BUILTIN_PREFIX + "__template__"


def builtin_presets(project_path: Path) -> list[dict]:
    """One read-only "Rendu de sequence" preset per sequence of the project (Houdini, SEQ).

    Launching it builds <SEQ>_render.hip when missing and opens the real scene."""
    # The template itself (2026-09-28): what every new sequence starts from.
    out = [{"id": TEMPLATE_PRESET_ID, "name": "Modele scene de rendu (FLUX)", "file": TEMPLATE.name,
            "task": "SEQ", "soft": "houdini", "builtin": True, "exists": TEMPLATE.is_file()}]
    for seq in project_sequences(project_path):
        current = find_render_scene(project_path, seq)
        out.append({"id": BUILTIN_PREFIX + seq, "name": f"Rendu {seq}",
                    "file": current.name if current else f"{seq}_render.hip (a creer)",
                    "task": "SEQ", "soft": "houdini", "builtin": True, "exists": current is not None})
    return out


def open_builtin_preset(project_path: Path, preset_id: str) -> dict:
    """Scene to open for a built-in preset id: the sequence render scene, built if missing."""
    if preset_id == TEMPLATE_PRESET_ID:
        return open_template_copy()
    if not preset_id.startswith(BUILTIN_PREFIX):
        return {"ok": False, "error": f"Preset FLUX inconnu : {preset_id}"}
    return create_sequence_render_scene(project_path, preset_id[len(BUILTIN_PREFIX):])


def open_template_copy() -> dict:
    """A throwaway copy of the render scene template (looking at it never changes the
    template every new sequence starts from)."""
    import shutil
    import tempfile

    if not TEMPLATE.is_file():
        return {"ok": False, "error": f"Template absent : {TEMPLATE}"}
    dest = Path(tempfile.mkdtemp(prefix="flux_render_template_")) / TEMPLATE.name
    shutil.copy2(TEMPLATE, dest)
    return {"ok": True, "created": False, "path": str(dest)}


def render_scene_base(project_path: Path, seq: str) -> Path:
    """<project>/shot/<SEQ>/<SEQ>_render (no extension): the render scene alone at the root
    of the sequence (ADR 0038, 2026-09-28)."""
    seq = seq.upper()
    return Path(project_path) / "shot" / seq / f"{seq}_render"


def legacy_render_scene_base(project_path: Path, seq: str) -> Path:
    """Where sequences made before ADR 0038 keep it: shot/<SEQ>/usd/lighting/<SEQ>_render."""
    seq = seq.upper()
    return Path(project_path) / "shot" / seq / USD_SUBDIR / LIGHTING_SUBDIR / f"{seq}_render"


def find_render_scene(project_path: Path, seq: str) -> Path | None:
    """The render scene of *seq* (new place, else the old one), None when not made yet."""
    return existing_hip(render_scene_base(project_path, seq)) or existing_hip(
        legacy_render_scene_base(project_path, seq))


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
    """Shots of *seq* (SHOT tokens), with the range / fps of their stage when it exists."""
    from features.importer.library_import import _stage_shots
    from features.usd_assembler.shot_light import list_stage_shots

    seq = seq.upper()
    staged = {(s["seq"], s["shot"]): s for s in list_stage_shots(project_path)}
    names = {shot for s_seq, shot in _stage_shots(Path(project_path)) if s_seq == seq}
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


HDA_PATH_TOKEN = "__FLUX_HDA_PATH__"


def _builders() -> dict:
    """{node type: HDA build script} for REQUIRED_TYPES, the .hda path left as a token."""
    from dcc.houdini.hda import flux_render_hda, flux_sequence_hda, flux_shot_switch_hda

    return {"flux_render": flux_render_hda._build_code(HDA_PATH_TOKEN),
            "flux_sequence": flux_sequence_hda._build_code(HDA_PATH_TOKEN),
            "flux_shot": flux_shot_switch_hda._build_code(HDA_PATH_TOKEN)}


def build_plan(project_path: Path, seq: str) -> dict:
    """Everything the hython script needs, as plain JSON (tested without Houdini)."""
    from dcc.houdini.hda.flux_sequence_hda import MODULE_FUNCTIONS

    shots = sequence_shots(project_path, seq)
    return {
        "project": Path(project_path).name,
        "seq": seq.upper(),
        "shots": shots,
        "blocks": max(MIN_SHOT_BLOCKS, len(shots)),
        "resolution": _resolution(project_path),
        "template": str(TEMPLATE).replace("\\", "/"),
        "template_seq": TEMPLATE_SEQ,
        "required": list(REQUIRED_TYPES),
        "required_parms": REQUIRED_PARMS,
        # Built in hython into the user's otls when missing (Shelf Manager not rerun yet).
        "builders": _builders(),
        "sequence_module": MODULE_FUNCTIONS,
        "session": SESSION_SOURCE,
    }


def _gen_script(plan: dict, dest_base: str) -> str:
    """Python run by hython: the maintainer's template + FLUX Sequence + one render chain / FLUX Render
    / ROP per shot block, saved as dest_base + licence ext."""
    return f'''
import hou, json, os, traceback
plan = json.loads({json.dumps(json.dumps(plan))})
result = {{"ok": False}}
try:
    def _outdated(t):
        nt = hou.nodeType(hou.lopNodeTypeCategory(), t)
        if nt is None:
            return True
        need = plan["required_parms"].get(t)
        return bool(need) and nt.parmTemplateGroup().find(need) is None
    missing = [t for t in plan["required"] if _outdated(t)]
    # Missing FLUX HDAs are built here into the user's otls (where the Shelf Manager
    # writes them): a sequence made before the rebuild still gets its scene.
    # Beside flux_shot.hda (installed by FLUX), else the Houdini prefs otls.
    _ref = hou.nodeType(hou.lopNodeTypeCategory(), "flux_shot")
    _lib = _ref.definition().libraryFilePath() if _ref is not None and _ref.definition() else ""
    _otls = (os.path.dirname(_lib) if _lib and os.path.isfile(_lib)
             else os.path.join(hou.homeHoudiniDirectory(), "otls")).replace(os.sep, "/")
    for _t in list(missing):
        try:
            os.makedirs(_otls, exist_ok=True)
            _g = {{}}
            exec(plan["builders"][_t].replace({HDA_PATH_TOKEN!r}, _otls + "/" + _t + ".hda"), _g)
            if not _outdated(_t):
                missing.remove(_t)
        except Exception:
            pass
    if missing:
        raise RuntimeError("HDA FLUX absents (%s) : reconstruis les HDA depuis le Shelf Manager"
                           % ", ".join(missing))
    hou.hipFile.load(plan["template"], suppress_save_prompt=True, ignore_load_warnings=True)
    stage = hou.node("/stage")
    seq = plan["seq"]
    ns = {{}}
    exec(plan["sequence_module"], ns)
    # The template's ROPs carry its sequence name.
    out = hou.node("/out")
    if out is not None and seq != plan["template_seq"]:
        for rop in out.children():
            if plan["template_seq"] in rop.name():
                rop.setName(rop.name().replace(plan["template_seq"], seq), unique_name=True)
    # FLUX Sequence at the top of the tree, feeding STRUCTURE.
    top = stage.node("FLUX_SEQUENCE") or stage.createNode("flux_sequence", "FLUX_SEQUENCE")
    for name, value in (("project", plan["project"]), ("seq", seq), ("shot_count", plan["blocks"])):
        top.parm(name).set(value)
    structure = stage.node("STRUCTURE")
    if structure is not None and top.outputs():
        structure = None            # the template already wires it
    if structure is not None:
        if not structure.inputs():
            structure.setInput(0, top)
        top.setPosition(structure.position() + hou.Vector2(0, 1.5))
        # Into the innermost big box around STRUCTURE (SEQUENCE), not STRUCTURE's own.
        holders = [b for b in stage.networkBoxes()
                   if structure in b.items() and b.comment().upper() != "STRUCTURE"]
        if holders:
            holder = min(holders, key=lambda b: len(b.items()))
            holder.addItem(top)
            for b in sorted(holders, key=lambda b: len(b.items())):
                ns["grow_box"](b)
    added, extra = ns["grow_to"](stage, plan["blocks"], plan["project"], seq)
    # Block n shows the n-th shot of the sequence: its imports (ENV = decors, CHAR =
    # characters) and its FLUX Render are filled, the artist can change them.
    real = [s["shot"] for s in plan["shots"]]
    for n in ns["shot_numbers"](stage):
        shot = real[n - 1] if n - 1 < len(real) else ""
        for prefix in ("IMPORT_ENV_", "IMPORT_CHAR_", "FLUX_RENDER_"):
            node = stage.node("%sSHOT%03d" % (prefix, n))
            if node is None:
                continue
            for pname, pval in (("project", plan["project"]), ("seq", seq), ("shot", shot)):
                if node.parm(pname) is not None and (pval or pname != "shot"):
                    node.parm(pname).set(pval)
    top.parm("status_msg").set("%d shot(s)" % plan["blocks"])
    for rs in stage.children():
        if rs.type().name().startswith("karmarendersettings") and rs.parmTuple("resolution") is not None:
            if rs.parm("res_mode") is not None:
                rs.parm("res_mode").set("manual")
            for _p, _v in zip(rs.parmTuple("resolution"), plan["resolution"]):
                _p.lock(False)
                _p.deleteAllKeyframes()
                _p.set(_v)
    hou.setSessionModuleSource(plan["session"])
    for _var in ("JOB", "POSE"):
        hou.hscript("set -g %s = \'\'" % _var)
    _cat = hou.licenseCategory()
    _ext = ".hip" if _cat == hou.licenseCategoryType.Commercial \\
        else ".hiplc" if _cat == hou.licenseCategoryType.Indie else ".hipnc"
    _dest = {dest_base!r} + _ext
    os.makedirs(os.path.dirname(_dest), exist_ok=True)
    hou.hipFile.save(_dest)
    result = {{"ok": True, "path": _dest, "shots": ns["shot_numbers"](stage), "added": added}}
except Exception as exc:
    result = {{"ok": False, "error": "%s\\n%s" % (exc, traceback.format_exc())}}
'''


def create_sequence_render_scene(project_path: Path, seq: str) -> dict:
    """Build <SEQ>_render.hip from the maintainer's template (ADR 0037): N shot blocks, each with its
    render chain, FLUX Render and ROP.

    Never overwrites: an existing scene is returned as is ({"created": False}).
    """
    project_path = Path(project_path)
    base = render_scene_base(project_path, seq)
    current = find_render_scene(project_path, seq)
    if current is not None:
        return {"ok": True, "created": False, "path": str(current)}
    plan = build_plan(project_path, seq)
    res = _run_offline(_gen_script(plan, str(base).replace("\\", "/")))
    if not res.get("ok"):
        log.warning("Render scene NOT generated for %s: %s", seq, res.get("error"))
        return {"ok": False, "error": res.get("error") or "hython"}
    log.info("Render scene generated: %s (%d shot blocks)", res.get("path"), len(res.get("shots", [])))
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
