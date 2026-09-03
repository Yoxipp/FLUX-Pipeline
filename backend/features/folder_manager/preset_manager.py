# preset_manager.py — template "presets" library, stored in <project>/template/.
#
# Builds on the template/ folder introduced by RETAKES-2 (project_init seeds it).
# A preset is a reusable model file the team links once and drops anywhere in the
# folder manager. The registry is <project>/template/presets.json:
#
#   {"presets": [{"id": "preset_1", "name": "layout_base", "file": "layout_base.hip",
#                 "task": "RIG", "soft": "maya"},
#                {"id": "preset_2", "name": "preset 2", "file": null,
#                 "task": null, "soft": null}]}
#
# task = the TASK token (a TYPE token, or the sentinel DEFAULT / SEQ / SHOT / ENV / FX)
# the preset is assigned to; soft = the target software key (maya, houdini…). Both may
# be null, and several presets may share the same (task, soft).
#
# Contract (same as the rest of folder_manager): pure functions returning
# {"ok": True, ...} or {"ok": False, "error": "..."}, atomic JSON writes, robust to
# a missing/corrupt registry (start empty, never raise), and no hardcoded paths.

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

TEMPLATE_SUBDIR = "template"
PRESETS_FILENAME = "presets.json"


# ── registry I/O ──────────────────────────────────────────────────────────────

def _registry_path(project_path: Path) -> Path:
    return project_path / TEMPLATE_SUBDIR / PRESETS_FILENAME


def _load(project_path: Path) -> list[dict]:
    """Return the preset list. Missing/corrupt registry → empty list (no raise)."""
    reg = _registry_path(project_path)
    if not reg.is_file():
        return []
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
        presets = data.get("presets", [])
        if not isinstance(presets, list):
            return []
        # Forward-compat: older registries have no task/soft — default them so every
        # returned preset carries the full shape ({id,name,file,task,soft}).
        for p in presets:
            if isinstance(p, dict):
                p.setdefault("task", None)
                p.setdefault("soft", None)
        return presets
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("presets.json unreadable for %s (%s); starting empty.", project_path.name, exc)
        return []


def _save(project_path: Path, presets: list[dict]) -> bool:
    """Atomically write the registry. Returns True on success."""
    reg = _registry_path(project_path)
    try:
        reg.parent.mkdir(parents=True, exist_ok=True)
        tmp = reg.with_name(f".{reg.stem}.tmp{reg.suffix}")
        tmp.write_text(json.dumps({"presets": presets}, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, reg)
        return True
    except OSError as exc:
        log.warning("Could not write presets.json for %s: %s", project_path.name, exc)
        return False


def _next_id(presets: list[dict]) -> str:
    """Return a fresh preset_N id (max existing N + 1)."""
    maxn = 0
    for p in presets:
        m = re.match(r"preset_(\d+)$", str(p.get("id", "")))
        if m:
            maxn = max(maxn, int(m.group(1)))
    return f"preset_{maxn + 1}"


def _find(presets: list[dict], preset_id: str) -> dict | None:
    return next((p for p in presets if p.get("id") == preset_id), None)


def _dedupe_name(dest_dir: Path, filename: str) -> str:
    """Return *filename*, or a `_NNN`-suffixed variant if it already exists in dest_dir.

    Handles compound extensions (bgeo.sc) by splitting on the first dot.
    """
    if not (dest_dir / filename).exists():
        return filename
    if "." in filename:
        base, suffix = filename.split(".", 1)
        suffix = "." + suffix
    else:
        base, suffix = filename, ""
    n = 1
    while True:
        cand = f"{base}_{n:03d}{suffix}"
        if not (dest_dir / cand).exists():
            return cand
        n += 1


# ── public API ────────────────────────────────────────────────────────────────

def list_presets(project_path: Path) -> list[dict]:
    """Return the ordered preset list ([{id,name,file}, ...])."""
    return _load(project_path)


def add_preset_slot(project_path: Path, name: str | None = None) -> dict:
    """Append an empty preset slot. Default name 'preset N'."""
    presets = _load(project_path)
    pid = _next_id(presets)
    label = (name or "").strip() or f"preset {len(presets) + 1}"
    presets.append({"id": pid, "name": label, "file": None, "task": None, "soft": None})
    if not _save(project_path, presets):
        return {"ok": False, "error": "could not write presets.json"}
    return {"ok": True, "preset": presets[-1], "presets": presets}


def prepare_new_scene(project_path: Path, preset_id: str) -> dict:
    """Copy the preset's linked scene into a fresh temp dir; return that copy's path.

    Non-destructive "New Scene": the DCC opens this throwaway copy, never the shared
    template in <project>/template/, so saving over it can't corrupt the preset. Each
    call gets its own temp dir, so the original filename (and its compound extension,
    e.g. .bgeo.sc) is preserved for a clean DCC title with zero collisions.
    """
    presets = _load(project_path)
    p = _find(presets, preset_id)
    if p is None:
        return {"ok": False, "error": f"unknown preset {preset_id}"}
    fname = p.get("file")
    if not fname:
        return {"ok": False, "error": "preset has no linked file"}
    src = project_path / TEMPLATE_SUBDIR / fname
    if not src.is_file():
        return {"ok": False, "error": f"linked file missing: {fname}"}
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="flux_newscene_"))
        dest = tmp_dir / src.name
        shutil.copy2(src, dest)
    except OSError as exc:
        return {"ok": False, "error": f"temp copy failed: {exc}"}
    log.info("Prepared New Scene copy: %s -> %s", src, dest)
    return {"ok": True, "path": str(dest), "name": src.name}


def set_preset_meta(project_path: Path, preset_id: str, task: str = "", soft: str = "") -> dict:
    """Assign the preset's TASK token (or DEFAULT) and target SOFT.

    Empty string clears the field to null. Both are always set from the caller's
    current selection. Multiple presets may share the same (task, soft).
    """
    presets = _load(project_path)
    p = _find(presets, preset_id)
    if p is None:
        return {"ok": False, "error": f"unknown preset {preset_id}"}
    p["task"] = (task or "").strip() or None
    p["soft"] = (soft or "").strip() or None
    if not _save(project_path, presets):
        return {"ok": False, "error": "could not write presets.json"}
    return {"ok": True, "preset": p, "presets": presets}


def rename_preset(project_path: Path, preset_id: str, new_name: str) -> dict:
    presets = _load(project_path)
    p = _find(presets, preset_id)
    if p is None:
        return {"ok": False, "error": f"unknown preset {preset_id}"}
    label = (new_name or "").strip()
    if not label:
        return {"ok": False, "error": "empty name"}
    p["name"] = label
    if not _save(project_path, presets):
        return {"ok": False, "error": "could not write presets.json"}
    return {"ok": True, "preset": p, "presets": presets}


def link_preset(project_path: Path, preset_id: str, src_file: Path) -> dict:
    """Copy *src_file* into template/ and set the slot's `file`.

    Idempotent-ish: overwrites the template/ copy for this slot's filename.
    """
    src = Path(src_file)
    if not src.is_file():
        return {"ok": False, "error": f"source file not found: {src}"}

    presets = _load(project_path)
    p = _find(presets, preset_id)
    if p is None:
        return {"ok": False, "error": f"unknown preset {preset_id}"}

    tpl_dir = project_path / TEMPLATE_SUBDIR
    tpl_dir.mkdir(parents=True, exist_ok=True)
    dest = tpl_dir / src.name
    try:
        # Only dedupe against OTHER presets' files, not our own previous copy.
        if dest.exists() and (p.get("file") != src.name):
            dest = tpl_dir / _dedupe_name(tpl_dir, src.name)
        shutil.copy2(src, dest)
    except OSError as exc:
        return {"ok": False, "error": f"copy failed: {exc}"}

    p["file"] = dest.name
    if not _save(project_path, presets):
        return {"ok": False, "error": "could not write presets.json"}
    return {"ok": True, "preset": p, "presets": presets}


def unlink_preset(project_path: Path, preset_id: str, delete_file: bool = False) -> dict:
    """Clear the slot's `file` (non-destructive by default; keeps template/ copy)."""
    presets = _load(project_path)
    p = _find(presets, preset_id)
    if p is None:
        return {"ok": False, "error": f"unknown preset {preset_id}"}
    old = p.get("file")
    p["file"] = None
    if delete_file and old:
        # only delete if no other preset references the same file
        if not any(q.get("file") == old for q in presets if q is not p):
            try:
                (project_path / TEMPLATE_SUBDIR / old).unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Could not delete template file %s: %s", old, exc)
    if not _save(project_path, presets):
        return {"ok": False, "error": "could not write presets.json"}
    return {"ok": True, "preset": p, "presets": presets}


def remove_preset_slot(project_path: Path, preset_id: str) -> dict:
    """Remove the slot from the registry (keeps any template/ file)."""
    presets = _load(project_path)
    if _find(presets, preset_id) is None:
        return {"ok": False, "error": f"unknown preset {preset_id}"}
    presets = [p for p in presets if p.get("id") != preset_id]
    if not _save(project_path, presets):
        return {"ok": False, "error": "could not write presets.json"}
    return {"ok": True, "presets": presets}


def drop_preset(project_path: Path, preset_id: str, dest_subpath: str) -> dict:
    """Copy the preset's linked file into <project>/<dest_subpath>/ (deduped).

    Path-safe: dest must resolve INSIDE the project. Returns the created path.
    """
    presets = _load(project_path)
    p = _find(presets, preset_id)
    if p is None:
        return {"ok": False, "error": f"unknown preset {preset_id}"}
    fname = p.get("file")
    if not fname:
        return {"ok": False, "error": "preset has no linked file"}

    src = project_path / TEMPLATE_SUBDIR / fname
    if not src.is_file():
        return {"ok": False, "error": f"linked file missing: {fname}"}

    # Resolve + contain the destination inside the project.
    rel = (dest_subpath or "").replace("\\", "/").strip("/")
    dest_dir = (project_path / rel).resolve() if rel else project_path.resolve()
    try:
        dest_dir.relative_to(project_path.resolve())
    except ValueError:
        return {"ok": False, "error": "destination outside project"}
    if not dest_dir.is_dir():
        return {"ok": False, "error": f"destination folder not found: {rel}"}

    out_name = _dedupe_name(dest_dir, fname)
    try:
        shutil.copy2(src, dest_dir / out_name)
    except OSError as exc:
        return {"ok": False, "error": f"copy failed: {exc}"}

    log.info("Preset %s dropped → %s", preset_id, dest_dir / out_name)
    return {"ok": True, "name": out_name, "path": str(dest_dir / out_name)}
