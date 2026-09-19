# houdini_scene_template.py — author the per-seq / per-shot Houdini lighting scene.
#
# Parallel to sequence_template.py (which writes the USD layers). Where the USD
# templates drop the *_light.usda layers, this drops the .hip scene the lighter
# opens, next to them:
#
#   <SEQ>/usd/lighting/<SEQ>_light.hip                 ← sequence lighting (general)
#   <SEQ>/<SHOT>/usd/lighting/<SEQ>_<SHOT>_light.hip   ← shot lighting (refines seq)
#
# Same contract as the USD templates: lazy Houdini discovery, idempotent (never
# overwrites an artist's .hip), and failure is ALWAYS non-fatal — a missing Houdini
# only logs a warning, the folders / tokens / USD layers still stand.
#
# Mechanism (see §3 of the RETAKES-2 spec):
#   1. offline via `hython` ONLY — a separate, isolated process. hython loads the
#      base template, drops/repoints the FLUX Lighting HDA, and saves the .hip.
#   2. no hython (or a save failure) → warn + {"ok": False}, never raise.
#
# IMPORTANT — never author in a live session. The generation script does
# hou.hipFile.load()+save(); running that in the artist's connected Houdini would
# REPLACE and clobber whatever scene they have open. Creating a seq/shot must never
# touch a live DCC, so there is deliberately NO live fallback here (that fallback was
# the "creating a shot wiped my open Houdini scene" bug). If hython is unavailable
# the .hip is simply not generated — the folders / tokens / USD layers still stand.
#
# License note (§7, fixed 2026-09-19): the scene is built from an EMPTY file (only a
# FLUX Lighting node) and saved with the extension of the licence: .hip (commercial),
# .hiplc (indie), .hipnc (education / apprentice), like the sequence scene (A5). The old way loaded
# the .hipnc seed first, which turned a commercial hython non commercial and made its
# .hip save fail: no shot ever got a scene. A team template is only loaded when it is a
# .hip / .hiplc in <project>/template/ (a .hipnc template would do the same again).

from __future__ import annotations

import glob
import os
import platform
import subprocess
import tempfile
from pathlib import Path

from core.constants import DCC_EXE_PATTERNS
from core.logger import get_logger

log = get_logger(__name__)

USD_SUBDIR = "usd"
LIGHTING_SUBDIR = "lighting"

# Template file names looked up inside <project>/template/ (then the pipeline seed).
_SEQ_TEMPLATE_NAMES = ("flux_template_sequence.hip", "flux_template_sequence.hipnc")
_SHOT_TEMPLATE_NAMES = ("flux_template_shot.hip", "flux_template_shot.hipnc")

# Pipeline seed (versioned default) — copied into <project>/template/ at project init.
_SEED_DIR = Path(__file__).parent.parent.parent / "resources" / "scenes" / "houdini"
_SEED_SEQ = _SEED_DIR / "flux_template_sequence.hipnc"


# ── template resolution ─────────────────────────────────────────────────────────

HIP_EXTS = (".hip", ".hiplc", ".hipnc")


def existing_hip(base: Path) -> Path | None:
    """The scene at *base* (no extension) whatever the licence that wrote it."""
    for ext in HIP_EXTS:
        cand = base.with_suffix(ext)
        if cand.is_file():
            return cand
    return None


def loadable_template(project_path: Path, names: tuple[str, ...]) -> Path | None:
    """A team template the generator may load: .hip / .hiplc in <project>/template/.
    None means "build from an empty scene" (the .hipnc seed is never loaded)."""
    for name in names:
        cand = project_path / "template" / name
        if cand.is_file() and cand.suffix.lower() in (".hip", ".hiplc"):
            return cand
    return None


def resolve_template(project_path: Path, names: tuple[str, ...]) -> Path | None:
    """Resolve a base template, preferring the project's interchangeable copy.

    Order: 1) <project>/template/<name>  → 2) pipeline seed resource.
    Logs which one was used. Returns None if nothing is found.
    """
    tpl_dir = project_path / "template"
    for name in names:
        cand = tpl_dir / name
        if cand.is_file():
            log.info("Houdini template resolved from project: %s", cand)
            return cand
    if _SEED_SEQ.is_file():
        log.info("Houdini template resolved from pipeline seed: %s", _SEED_SEQ)
        return _SEED_SEQ
    log.warning("No Houdini template found (project template/ empty and no seed).")
    return None


# ── Houdini / hython discovery ───────────────────────────────────────────────────

def _find_hython() -> Path | None:
    """Locate hython(.exe) next to the discovered houdini.exe. None if not found.

    Reuses the exe globs from constants (same source autostart/shelf discovery use),
    then swaps the launcher name for hython in the same bin/ directory.
    """
    exe_name = "hython.exe" if platform.system() == "Windows" else "hython"
    for pattern in DCC_EXE_PATTERNS.get("Houdini", []):
        for exe in sorted(glob.glob(pattern), reverse=True):  # newest install first
            hy = Path(exe).parent / exe_name
            if hy.is_file():
                return hy
    return None


# ── the generation script run by hython / houdini_client ─────────────────────────

def _gen_script(template: str | None, dest_base: str, usd_input_rel: str, usd_output_rel: str) -> str:
    """Return Python that starts from *template* (None = empty scene), sets the FLUX
    Lighting node and saves ``dest_base`` + the licence's extension.

    Runs inside hython only. Assigns a JSON-serialisable dict to `result`. Paths are
    $HIP-relative so the saved scene stays portable.
    """
    return f'''
import hou, traceback
result = {{"ok": False}}
try:
    if {template!r}:
        hou.hipFile.load({template!r}, suppress_save_prompt=True, ignore_load_warnings=True)
    else:
        hou.hipFile.clear(suppress_save_prompt=True)

    stage = hou.node("/stage") or hou.node("/").createNode("stage")

    # Find an existing FLUX Lighting node, else drop one (HDA must be installed).
    node = None
    for n in stage.allSubChildren():
        try:
            if n.type().name().startswith("flux_lighting"):
                node = n
                break
        except Exception:
            pass
    if node is None:
        try:
            node = stage.createNode("flux_lighting")
        except Exception as exc:
            result = {{"ok": False, "error": "flux_lighting HDA not installed: %s" % exc}}
            node = None

    if node is not None:
        for pname, pval in (("usd_input", {usd_input_rel!r}), ("usd_output", {usd_output_rel!r})):
            p = node.parm(pname)
            if p is not None:
                p.set(pval)
        node.setDisplayFlag(True) if hasattr(node, "setDisplayFlag") else None

        # Machine paths never land in the scene (ADR 0012).
        for _var in ("JOB", "POSE"):
            hou.hscript("set -g %s = ''" % _var)
        _cat = hou.licenseCategory()
        _ext = ".hip" if _cat == hou.licenseCategoryType.Commercial \\
            else ".hiplc" if _cat == hou.licenseCategoryType.Indie else ".hipnc"
        _dest = {dest_base!r} + _ext
        import os as _os
        _os.makedirs(_os.path.dirname(_dest), exist_ok=True)
        hou.hipFile.save(_dest)
        result = {{"ok": True, "path": _dest}}
except hou.OperationFailed as exc:
    result = {{"ok": False, "error": "save failed: %s" % exc}}
except Exception as exc:
    result = {{"ok": False, "error": "%s\\n%s" % (exc, traceback.format_exc())}}
'''


def _run_offline(script: str) -> dict:
    """Run *script* through hython. Returns {"ok": bool, ...}."""
    hython = _find_hython()
    if not hython:
        return {"ok": False, "error": "hython not found"}

    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
            # print a parseable marker so we can read the outcome from stdout
            fh.write(script + "\nprint('FLUX_HIP_RESULT:' + __import__('json').dumps(result))\n")
            tmp = fh.name
        extra: dict = {}
        if platform.system() == "Windows":
            extra["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.run(
            [str(hython), tmp], capture_output=True, text=True, timeout=300, **extra,
        )
        for line in proc.stdout.splitlines():
            if line.startswith("FLUX_HIP_RESULT:"):
                import json
                return json.loads(line[len("FLUX_HIP_RESULT:"):])
        return {"ok": False, "error": f"hython gave no result (rc={proc.returncode}): {proc.stderr[-500:]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "hython timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _generate(template: Path | None, dest_base: Path, usd_input_rel: str, usd_output_rel: str) -> dict:
    """Author the .hip via an ISOLATED hython process only — NEVER a live session.

    The script does hou.hipFile.load()+save(); running it in a connected Houdini
    would replace and clobber the artist's open scene. So there is no live fallback:
    if hython is unavailable (or the save fails, e.g. Apprentice can't write .hip),
    the .hip is simply not generated and we return {"ok": False}. Folders / tokens /
    USD layers created by the caller still stand; nothing is ever raised.
    """
    script = _gen_script(str(template) if template else None, str(dest_base).replace("\\", "/"),
                         usd_input_rel, usd_output_rel)

    res = _run_offline(script)
    if res.get("ok"):
        log.info("Houdini scene generated (offline hython): %s", res.get("path"))
        return res

    msg = res.get("error") or "unknown"
    log.warning(
        "Houdini scene NOT generated for %s: %s (hython introuvable ?). "
        "Skipped — a live Houdini session is never touched.",
        dest_base.name, msg,
    )
    return {"ok": False, "error": msg}


# ── public API ────────────────────────────────────────────────────────────────

def create_sequence_hip_scene(seq_path: Path, seq_label: str) -> dict:
    """Author the sequence lighting .hip (general light rig) under *seq_path*.

    Idempotent: never overwrites an existing .hip (artist work is kept).
    Returns {"ok": True, "created": [path]} or {"ok": False, "error": "..."}.
    """
    project_path = seq_path.parents[1]  # <project>/shot/<SEQ> → <project>
    light_dir = seq_path / USD_SUBDIR / LIGHTING_SUBDIR
    dest_base = light_dir / f"{seq_label}_light"

    current = existing_hip(dest_base)
    if current is not None:
        return {"ok": True, "created": [], "path": str(current)}

    template = loadable_template(project_path, _SEQ_TEMPLATE_NAMES)

    # $HIP is the scene's own usd/lighting dir. Seq root USD sits one level up.
    usd_input = "$HIP/../{seq}.usda".format(seq=seq_label)
    usd_output = "$HIP/{seq}_light.usda".format(seq=seq_label)

    res = _generate(template, dest_base, usd_input, usd_output)
    if res.get("ok"):
        return {"ok": True, "created": [res["path"]], "path": res["path"]}
    return {"ok": False, "error": res.get("error"), "created": []}


def create_shot_hip_scene(shot_path: Path, seq_label: str, shot_label: str) -> dict:
    """Author the shot lighting .hip (refines/overrides the seq rig) under *shot_path*.

    Idempotent. Returns {"ok": True, "created": [path]} or {"ok": False, "error": ...}.
    """
    project_path = shot_path.parents[2]  # <project>/shot/<SEQ>/<SHOT> → <project>
    entity = f"{seq_label}_{shot_label}"
    light_dir = shot_path / USD_SUBDIR / LIGHTING_SUBDIR
    dest_base = light_dir / f"{entity}_light"

    current = existing_hip(dest_base)
    if current is not None:
        return {"ok": True, "created": [], "path": str(current)}

    template = loadable_template(project_path, _SHOT_TEMPLATE_NAMES)

    # $HIP is shot/usd/lighting. Shot root USD sits one level up; it already
    # sublayers the sequence light rig (strong → weak).
    usd_input = "$HIP/../{entity}.usda".format(entity=entity)
    usd_output = "$HIP/{entity}_light.usda".format(entity=entity)

    res = _generate(template, dest_base, usd_input, usd_output)
    if res.get("ok"):
        return {"ok": True, "created": [res["path"]], "path": res["path"]}
    return {"ok": False, "error": res.get("error"), "created": []}
