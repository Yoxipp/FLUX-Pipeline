"""Freeze LAST -> vNNN before a farm submission (ADR 0009 / 0017).

The farm must only read immutable vNNN files: a LAST pointer can move while a
job renders, and the frames would then mix two versions.

  * Shot: regenerate the shot stage with frozen=True (shot_stage.write_stage
    writes vNNN paths instead of LAST for every department layer and asset).
  * Any USD: a LAST pointer picked by the user is replaced by its vNNN.

Then the whole dependency closure is audited (UsdUtils.ComputeAllDependencies):
LAST pointers still reachable deeper (a department vNNN that references an
asset LAST) and unresolved paths are reported as warnings, never blocking.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from core.logger import get_logger

log = get_logger(__name__)

_VERSION_DIR = re.compile(r"^v(\d{3,})$")


def is_last_pointer(path: Path) -> bool:
    return "_LAST" in Path(path).stem


def resolve_last(path: Path) -> Path:
    """The vNNN a LAST pointer targets (the file itself when it is not a pointer)."""
    from features.publisher.last_pointer import read_layer_flux

    path = Path(path)
    if not is_last_pointer(path):
        return path
    target = (read_layer_flux(path) or {}).get("target")
    if target:
        cand = path.parent / target
        if cand.is_file():
            return cand
    return path


def audit_dependencies(usd_path: Path) -> Dict[str, List[str]]:
    """{"layers", "last_pointers", "unresolved"} of the full dependency closure."""
    from pxr import UsdUtils

    layers, _assets, unresolved = UsdUtils.ComputeAllDependencies(str(usd_path))
    paths = [layer.realPath or layer.identifier for layer in layers]
    return {
        "layers": paths,
        "last_pointers": [p for p in paths if is_last_pointer(Path(p))],
        "unresolved": list(unresolved),
    }


def _warnings(audit: Dict[str, List[str]]) -> List[str]:
    out = [f"LAST encore lu par le rendu (non fige) : {p}" for p in audit["last_pointers"]]
    out += [f"Fichier introuvable : {p}" for p in audit["unresolved"]]
    return out


def freeze_usd(usd_path: Path, *, freeze: bool = True) -> Dict:
    """Pick the vNNN behind a LAST pointer, then audit what the job will read."""
    usd_path = Path(usd_path)
    frozen = resolve_last(usd_path) if freeze else usd_path
    if freeze and frozen == usd_path and is_last_pointer(usd_path):
        log.warning("LAST pointer without a readable target: %s", usd_path)
    audit = audit_dependencies(frozen)
    return {"usd": str(frozen), "frozen": not is_last_pointer(frozen),
            "audit": audit, "warnings": _warnings(audit)}


def freeze_shot(project_path: Path, seq: str, shot: str, *, user: str = "", freeze: bool = True) -> Dict:
    """Shot stage to render: a frozen stage version (default) or the current LAST."""
    from features.usd_assembler import shot_stage

    if freeze:
        result = shot_stage.write_stage(project_path, seq, shot, user=user, frozen=True)
        entry = result.get("entry")
        if entry is None:
            raise FileNotFoundError(f"Pas de stage pour {shot_stage.entity(seq, shot)}")
        audit = audit_dependencies(Path(entry))
        return {"usd": str(entry), "version": result.get("version"), "frozen": True,
                "audit": audit, "warnings": list(result.get("warnings") or []) + _warnings(audit)}
    last = shot_stage.last_file(project_path, seq, shot)
    if not last.is_file():
        raise FileNotFoundError(f"Pas de stage pour {shot_stage.entity(seq, shot)}")
    audit = audit_dependencies(last)
    return {"usd": str(last), "version": None, "frozen": False, "audit": audit, "warnings": _warnings(audit)}


def next_render_dir(shot_folder: Path) -> Path:
    """<shot>/render/vNNN, next free version (flat folder, no per-format subfolder)."""
    root = Path(shot_folder) / "render"
    used = [int(m.group(1)) for p in root.glob("v*") if p.is_dir() and (m := _VERSION_DIR.match(p.name))]
    return root / f"v{(max(used) + 1) if used else 1:03d}"


def reserve_render_dir(shot_folder: Path, attempts: int = 50) -> Path:
    """Create the next <shot>/render/vNNN atomically: two submits never share (and overwrite) a version."""
    for _ in range(attempts):
        target = next_render_dir(shot_folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.mkdir()
        except FileExistsError:
            continue  # taken by another submit meanwhile: next one
        return target
    raise RuntimeError(f"no free render version in {Path(shot_folder) / 'render'}")
