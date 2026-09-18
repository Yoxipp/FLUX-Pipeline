# library_import.py — USD library (components / assemblies) for DCC importers.
#
# The Houdini flux_importer HDA has three sources (2026-09-17): project tokens,
# the USD library (same data as FLUX "Bibliotheque"), and a free file path. This
# module serves the last two: compact menu items, and item/version -> file + the
# facts (skeleton) the HDA needs to pick usdimport vs KineFX character import.

from __future__ import annotations

import re
from pathlib import Path

from core.logger import get_logger
from features.importer.usd_probe import probe_usd

log = get_logger(__name__)

_VERSION_RE = re.compile(r"v\d+")


def library_items(project_path: str | Path) -> list[dict]:
    """[{"key": "component:NAME" | "assembly:NAME" | "shot:SEQ/SHOT", "label",
    "versions": ["LAST", ...]}]. Shots are listed once their stage exists (ADR 0020)."""
    from features.usd_assembler.library import build_library

    lib = build_library(project_path)
    items: list[dict] = []
    for comp in lib.get("components", []):
        if not comp.get("last") and not comp.get("versions"):
            continue
        items.append({
            "key": f"component:{comp['name']}",
            "label": f"Component  {comp['name']}",
            "versions": ["LAST"] + sorted(comp.get("versions") or [], reverse=True),
        })
    for asm in lib.get("assemblies", []):
        items.append({"key": f"assembly:{asm['name']}", "label": f"Assembly  {asm['name']}",
                      "versions": ["LAST"] + sorted(asm.get("versions") or [], reverse=True)})
    items += _shot_items(project_path)
    return items


def _shot_items(project_path: str | Path) -> list[dict]:
    from features.usd_assembler import shot_stage as ss

    items = []
    for seq, shot in _stage_shots(Path(project_path)):
        versions = ss.stage_versions(project_path, seq, shot)
        if not versions and not ss.last_file(project_path, seq, shot).is_file():
            continue
        items.append({"key": f"shot:{seq}/{shot}", "label": f"Shot  {seq} {shot}",
                      "versions": ["LAST"] + sorted(versions, reverse=True)})
    return items


def _stage_shots(project: Path) -> list[tuple[str, str]]:
    """(SEQ, SHOT) of the SHOT tokens of the project."""
    from features.folder_manager.tokens import load_tokens

    out = []
    for key in sorted(((load_tokens(project) or {}).get("SHOT") or {})):
        seq, _, shot = str(key).partition("/")
        if seq and shot:
            out.append((seq.upper(), shot.upper()))
    return out


def _resolve_shot(project_path: str | Path, name: str, version: str) -> dict:
    from features.usd_assembler import shot_stage as ss

    seq, _, shot = name.partition("/")
    if not seq or not shot:
        return {"ok": False, "error": f"Shot invalide : {name!r}"}
    if version in ("", "LAST", "latest"):
        path = ss.last_file(project_path, seq, shot)
    elif _VERSION_RE.fullmatch(version):
        ent = ss.entity(seq, shot)
        path = ss.stage_dir(project_path, seq, shot) / f"{ent}_{version}" / f"{ent}.usda"
    else:
        return {"ok": False, "error": f"Version invalide : {version!r}"}
    if not path.is_file():
        return {"ok": False, "error": f"Stage du shot {seq} {shot} {version or 'LAST'} introuvable "
                                      "(le generer depuis la page USD)"}
    # A shot stage is a whole scene: it is sublayered, never referenced under a prim.
    return {"ok": True, "path": str(path), "kind": "shot", "has_skel": False, "prim_path": "/assets"}


def resolve_library_item(project_path: str | Path, key: str, version: str = "LAST") -> dict:
    """Return {"ok", "path", "kind", "has_skel"} or {"ok": False, "error"}."""
    from features.usd_assembler.library import build_library

    kind, _, name = (key or "").partition(":")
    if kind == "shot":
        return _resolve_shot(project_path, name, version)
    if kind not in ("component", "assembly") or not name:
        return {"ok": False, "error": f"Element de bibliotheque invalide : {key!r}"}
    lib = build_library(project_path)

    path: Path | None = None
    if kind == "component":
        comp = next((c for c in lib.get("components", []) if c["name"] == name), None)
        if comp is None:
            return {"ok": False, "error": f"Component introuvable : {name}"}
        if version in ("", "LAST", "latest"):
            path = Path(comp["last"]) if comp.get("last") else None
        elif _VERSION_RE.fullmatch(version):
            path = Path(comp["dir"]) / f"{name}_{version}" / f"{name}.usda"
        else:
            return {"ok": False, "error": f"Version invalide : {version!r}"}
    else:
        asm = next((a for a in lib.get("assemblies", []) if a["name"] == name), None)
        if asm is None:
            path = None
        elif version in ("", "LAST", "latest") or asm.get("legacy"):
            path = Path(asm["file"])
        elif _VERSION_RE.fullmatch(version):
            path = Path(asm["file"]).parent / f"{name}_{version}" / f"{name}.usda"
        else:
            return {"ok": False, "error": f"Version invalide : {version!r}"}

    if path is None or not path.is_file():
        return {"ok": False, "error": f"Fichier introuvable pour {key} {version or 'LAST'}"}
    return {"ok": True, "path": str(path), "kind": kind, **_skel(path)}


def importer_source_for_file(project_path: str | Path, file: str | Path) -> dict:
    """flux_importer HDA parms that point at *file* (2026-09-17: "Ouvrir dans
    Houdini" must give an importer whose asset can be changed).

    * component / assembly entry (LAST or vNNN)  -> {"source_mode": "library", ...}
    * task publish the tokens resolve back to    -> {"source_mode": "tokens", ...}
    * anything else (a sublayer, a free file)     -> {"source_mode": "file", "free_path"}
    """
    from features.importer.importer_resolve import path_to_tokens, resolve_import_path
    from features.usd_assembler.library import build_library

    project = Path(str(Path(project_path).resolve()))
    target = Path(str(Path(file).resolve()))
    lib = build_library(project)

    def _entry_version(folder: Path, name: str) -> str | None:
        if target.parent == folder and target.name.startswith(f"{name}_LAST."):
            return "LAST"
        m = re.fullmatch(rf"{re.escape(name)}_(v\d+)", target.parent.name)
        if m and target.parent.parent == folder and target.stem == name:
            return m.group(1)
        return None

    for comp in lib.get("components", []):
        version = _entry_version(Path(str(Path(comp["dir"]).resolve())), comp["name"])
        if version:
            return {"source_mode": "library", "lib_item": f"component:{comp['name']}", "lib_version": version}
    shot = _shot_of_file(project, target)
    if shot:
        return {"source_mode": "library", "lib_item": f"shot:{shot[0]}/{shot[1]}", "lib_version": shot[2]}
    for asm in lib.get("assemblies", []):
        asm_file = Path(str(Path(asm["file"]).resolve()))
        if asm.get("legacy"):
            version = "LAST" if target == asm_file else None
        else:
            version = _entry_version(asm_file.parent, asm["name"])
        if version:
            return {"source_mode": "library", "lib_item": f"assembly:{asm['name']}", "lib_version": version}

    try:
        rel_parts = list(target.relative_to(project).parts)
    except ValueError:
        rel_parts = []
    tok = path_to_tokens(project, rel_parts) if rel_parts else {}
    if tok.get("CLASS") and tok.get("TYPE") and tok.get("NAME"):
        m = _ITER_RE.search(target.stem) or _ITER_RE.search(target.parent.name)
        iter_val = m.group(1) if m else "LAST"
        instance = tok.get("INSTANCE") or "null"
        instance = "null" if instance.upper() == "NULL" else instance
        r = resolve_import_path(project, tok["CLASS"], tok["TYPE"], tok["NAME"], instance, iter_val)
        if r.get("ok") and r.get("path") and Path(str(Path(r["path"]).resolve())) == target:
            return {"source_mode": "tokens", "flux_class": tok["CLASS"], "flux_type": tok["TYPE"],
                    "flux_name": tok["NAME"], "flux_instance": instance, "flux_iter": iter_val}
    return {"source_mode": "file", "free_path": str(file)}


_ITER_RE = re.compile(r"_(LAST|v\d+)$")


def probe_file(path: str | Path) -> dict:
    """Free path mode: expand a ``$FLUX/...`` token, check it exists, report skeleton."""
    from core.paths import from_flux_token

    raw = str(path or "").strip()
    if not raw:
        return {"ok": False, "error": "Chemin vide"}
    real = from_flux_token(raw) if raw.startswith("$FLUX") else Path(raw)
    if not real.is_file():
        return {"ok": False, "error": f"Fichier introuvable : {raw}"}
    return {"ok": True, "path": raw, **_skel(real)}


def _skel(path: Path) -> dict:
    """{"has_skel", "prim_path"}: prim_path is where a LOP importer puts the file
    (/assets/<X> for an asset, /sets/<X> for a decor), "" for a non-USD file."""
    if path.suffix.lower() not in (".usd", ".usda", ".usdc", ".usdz"):
        return {"has_skel": False, "prim_path": ""}
    from features.importer.usd_probe import reference_prim_path

    info = probe_usd(path)
    return {"has_skel": bool(info.get("has_skel")), "prim_path": reference_prim_path(info)}


def _shot_of_file(project: Path, target: Path) -> tuple[str, str, str] | None:
    """(SEQ, SHOT, "LAST" | vNNN) when *target* is a shot stage entry (ADR 0020)."""
    from features.usd_assembler import shot_stage as ss

    for seq, shot in _stage_shots(project):
        folder = Path(str(ss.stage_dir(project, seq, shot).resolve()))
        ent = ss.entity(seq, shot)
        if target.parent == folder and target.name == f"{ent}_LAST.usda":
            return seq, shot, "LAST"
        m = re.fullmatch(rf"{re.escape(ent)}_(v\d+)", target.parent.name)
        if m and target.parent.parent == folder and target.name == f"{ent}.usda":
            return seq, shot, m.group(1)
    return None
