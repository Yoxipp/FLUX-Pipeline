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
    """[{"key": "component:NAME" | "assembly:NAME", "label", "versions": ["LAST", ...]}]."""
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
    return items


def resolve_library_item(project_path: str | Path, key: str, version: str = "LAST") -> dict:
    """Return {"ok", "path", "kind", "has_skel"} or {"ok": False, "error"}."""
    from features.usd_assembler.library import build_library

    kind, _, name = (key or "").partition(":")
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
