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
                      "versions": ["LAST"]})
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
        path = Path(asm["file"]) if asm else None

    if path is None or not path.is_file():
        return {"ok": False, "error": f"Fichier introuvable pour {key} {version or 'LAST'}"}
    return {"ok": True, "path": str(path), "kind": kind, **_skel(path)}


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
    if path.suffix.lower() not in (".usd", ".usda", ".usdc", ".usdz"):
        return {"has_skel": False}
    return {"has_skel": bool(probe_usd(path).get("has_skel"))}
