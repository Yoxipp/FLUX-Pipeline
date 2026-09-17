# departments.py — which department a USD publish contributes to (ADR 0019).
#
# One USD publish = one department. The TYPE token of an asset publish names it;
# the light export only carries what that department owns (GEO: geometry + skin
# weights + the skeleton they bind to, RIG: skeleton, ANIM: skeleton animation clip).
# Pure python, no pxr.

from __future__ import annotations

from dataclasses import replace

from .contract import LightAsset

# Asset TYPE -> department layer of the asset (component). Strength: higher = stronger
# (AYON defaults). look (SHADING) and groom come from their own exporters.
ASSET_DEPARTMENTS: dict[str, str] = {"GEO": "model", "GROOM": "groom", "SHADING": "look", "RIG": "rig"}
DEPARTMENT_ORDER: dict[str, int] = {"model": 100, "groom": 175, "look": 200, "rig": 300}
# Asset TYPE published as a standalone skeleton animation (crowd clip, A6), not in the asset.
CLIP_TYPES = frozenset({"ANIM"})
# Asset TYPE the light (skinned mesh / skeleton) export can write.
LIGHT_EXPORT_TYPES = frozenset({"GEO", "RIG"}) | CLIP_TYPES


def contribution(base: str) -> dict | None:
    """{"kind": "asset" | "clip" | "shot", "department", "name", "instance", "type"} for a
    publish base name, or None when it does not parse as a FLUX name."""
    from features.folder_manager.naming_validator import parse_filename

    parsed = parse_filename(f"{base}.usd")
    if not parsed:
        return None
    if parsed.get("is_shot"):
        return {"kind": "shot", "department": None, "name": None,
                "instance": parsed.get("VARIANTE") or "", "type": None}
    task = str(parsed.get("TYPE") or "").upper()
    kind = "clip" if task in CLIP_TYPES else "asset"
    return {"kind": kind, "department": ASSET_DEPARTMENTS.get(task), "name": parsed.get("NAME") or "",
            "instance": parsed.get("INSTANCE") or "", "type": task}


def restrict_light_asset(asset: LightAsset, contrib: dict) -> tuple[LightAsset, list[str]]:
    """Keep only what the publish department owns; ValueError for a TYPE the light
    export cannot write (MULT, SHADING, ...). Returns (asset, warnings)."""
    if contrib["kind"] == "shot":
        return asset, []
    task = contrib["type"]
    if task not in LIGHT_EXPORT_TYPES:
        raise ValueError(
            f"TYPE {task} non publiable en USD leger : un publish = un departement "
            "(GEO = geometrie + poids, RIG = skeleton, ANIM = clip d'anim ; le look passe par l'export Look)")
    warnings: list[str] = []
    changes: dict = {}
    if asset.cameras or asset.lights:
        warnings.append("cameras et lumieres ignorees : elles appartiennent au shot")
        changes.update(cameras=[], lights=[])
    if task == "GEO" and asset.anim is not None:
        warnings.append("anim ignoree pour un publish GEO : l'anim se publie en ANIM ou dans le shot")
        changes["anim"] = None
    elif task == "RIG":
        if asset.meshes:
            warnings.append("geometrie ignoree pour un publish RIG : la geometrie et les poids se publient en GEO")
            changes["meshes"] = []
        if asset.anim is not None:
            warnings.append("anim ignoree pour un publish RIG : l'anim se publie en ANIM ou dans le shot")
            changes["anim"] = None
    elif task in CLIP_TYPES and asset.meshes:
        warnings.append("geometrie ignoree pour un clip d'anim")
        changes["meshes"] = []
    return (replace(asset, **changes) if changes else asset), warnings
