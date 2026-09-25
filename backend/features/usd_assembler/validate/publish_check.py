# publish_check.py — contract check of a freshly published USD version (USD strategy R3).
#
# Runs from usd_publish_hooks.after_usd_publish on the IMMUTABLE version. Warn only:
# the publish already landed, a finding goes to the log and modif_logs.json, it never
# blocks or fails anything. Reads the version's own layer stack (no payload loaded).
#
# Checks (docs/architecture/USD_STRATEGY.md section 3):
#   * a defaultPrim, and for an asset department layer it is the asset NAME (ADR 0019);
#   * portable asset paths: no drive letter, no backslash, no "$VAR" (USD never expands
#     it) in sublayers, references, payloads AND asset attributes (textures);
#   * metersPerUnit / upAxis, when authored, equal to project.json (ADR 0011);
#   * an animated layer carries timeCodesPerSecond equal to the project fps;
#   * every Mesh has an authored extent (bounds, culling);
#   * a look layer defines no geometry (materials + overs only, ADR 0019 7quater).

from __future__ import annotations

import re
from pathlib import Path

from core.logger import get_logger

from .validator import ERROR, WARN, Issue

log = get_logger("usd_assembler.publish_check")

__all__ = ["check_published_usd", "find_project_root", "ERROR", "WARN", "Issue"]

_ABSOLUTE_RE = re.compile(r"^([A-Za-z]:|/)")
_MAX_LISTED = 5


def find_project_root(folder: Path) -> Path | None:
    """First parent of *folder* holding project.json or tokens.json."""
    for cand in [Path(folder), *Path(folder).parents]:
        if (cand / "project.json").is_file() or (cand / "tokens.json").is_file():
            return cand
    return None


def _project_units(project: Path | None) -> dict | None:
    if project is None:
        return None
    try:
        from features.folder_manager.project_config import read_project_config

        cfg = read_project_config(project)
    except Exception:           # noqa: BLE001 - no config = nothing to compare with
        return None
    if not cfg:
        return None
    usd = cfg.get("usd") or {}
    return {"fps": float(cfg.get("fps") or 24),
            "meters_per_unit": float(usd.get("meters_per_unit") or 1.0),
            "up_axis": str(usd.get("up_axis") or "Y")}


def _path_issue(asset_path: str, where: str | None) -> Issue | None:
    if not asset_path:
        return None
    if "$" in asset_path:
        return Issue(WARN, f"chemin avec variable non resolue par USD : {asset_path}", where)
    if "\\" in asset_path:
        return Issue(WARN, f"chemin avec antislash : {asset_path}", where)
    if _ABSOLUTE_RE.match(asset_path):
        return Issue(WARN, f"chemin absolu (non portable) : {asset_path}", where)
    return None


def _layer_paths(layer) -> list[Issue]:
    """Sublayers, references, payloads and asset-valued attributes of one layer."""
    from pxr import Sdf

    issues: list[Issue] = []
    for sub in layer.subLayerPaths:
        hit = _path_issue(sub, None)
        if hit:
            issues.append(hit)

    def _visit(path) -> None:
        if path.IsPrimPath() or path.IsPrimVariantSelectionPath():
            spec = layer.GetPrimAtPath(path)
            if spec is None:
                return
            items = list(spec.referenceList.GetAddedOrExplicitItems())
            items += list(spec.payloadList.GetAddedOrExplicitItems())
            for item in items:
                hit = _path_issue(item.assetPath, path.pathString)
                if hit:
                    issues.append(hit)
        elif path.IsPropertyPath():
            spec = layer.GetAttributeAtPath(path)
            if spec is None or spec.typeName not in asset_types:
                return
            values = [spec.default] if spec.HasDefaultValue() else []
            values += [layer.QueryTimeSample(path, t) for t in layer.ListTimeSamplesForPath(path)]
            for value in values:
                for asset in ([value] if isinstance(value, Sdf.AssetPath) else list(value or [])):
                    hit = _path_issue(getattr(asset, "path", ""), path.pathString)
                    if hit:
                        issues.append(hit)

    asset_types = (Sdf.ValueTypeNames.Asset, Sdf.ValueTypeNames.AssetArray)

    layer.Traverse(Sdf.Path.absoluteRootPath, _visit)
    return issues


def _units_issues(root_layer, units: dict | None) -> list[Issue]:
    """Authored units that differ from project.json. An ABSENT value is not reported:
    the light export does not declare units yet (P-USD-7, declaring them changes how
    mayaUSD imports the scale: needs a live check first)."""
    issues: list[Issue] = []
    info = root_layer.pseudoRoot
    if units and info.HasInfo("metersPerUnit"):
        mpu = float(info.GetInfo("metersPerUnit"))
        if abs(mpu - units["meters_per_unit"]) > 1e-6:
            issues.append(Issue(WARN, f"metersPerUnit {mpu:g} different du projet "
                                      f"({units['meters_per_unit']:g})", None))
    if units and info.HasInfo("upAxis") and str(info.GetInfo("upAxis")) != units["up_axis"]:
        issues.append(Issue(WARN, f"upAxis {info.GetInfo('upAxis')} different du projet "
                                  f"({units['up_axis']})", None))
    return issues


def _time_issues(stage, root_layer, units: dict | None) -> list[Issue]:
    animated = root_layer.HasStartTimeCode() or root_layer.HasEndTimeCode()
    if not animated:
        return []
    if not root_layer.HasTimeCodesPerSecond():
        return [Issue(WARN, "layer anime sans timeCodesPerSecond (fps inconnu)", None)]
    fps = stage.GetTimeCodesPerSecond()
    if units and abs(fps - units["fps"]) > 1e-6:
        return [Issue(WARN, f"fps {fps:g} different du projet ({units['fps']:g})", None)]
    return []


def _summarize(prims: list[str], msg: str) -> list[Issue]:
    if not prims:
        return []
    shown = ", ".join(prims[:_MAX_LISTED]) + (" ..." if len(prims) > _MAX_LISTED else "")
    return [Issue(WARN, f"{msg} ({len(prims)}) : {shown}", prims[0])]


def check_published_usd(version_path: str | Path, base: str,
                        project: Path | None = None) -> list[Issue]:
    """Contract findings for the published USD *version_path* (warn level). Never raises."""
    try:
        from pxr import Sdf, Usd, UsdGeom
    except ImportError:
        return []
    path = Path(str(version_path))
    try:
        stage = Usd.Stage.Open(str(path), Usd.Stage.LoadNone)
    except Exception as exc:       # noqa: BLE001
        return [Issue(WARN, f"USD illisible : {exc}", None)]
    if stage is None:
        return [Issue(WARN, "USD illisible", None)]
    try:
        from features.usd_export.departments import contribution, is_motion_only

        contrib = contribution(base)
    except Exception:              # noqa: BLE001
        contrib = None
    root_layer = stage.GetRootLayer()
    issues: list[Issue] = []

    if not root_layer.defaultPrim:
        issues.append(Issue(WARN, "pas de defaultPrim", None))
    elif contrib and contrib["kind"] == "asset" and contrib.get("department") and contrib.get("name"):
        from features.usd_assembler.structure.naming import sanitize_token

        expected = sanitize_token(contrib["name"])
        if root_layer.defaultPrim != expected:
            issues.append(Issue(WARN, f"prim racine {root_layer.defaultPrim} au lieu de "
                                      f"{expected} (ADR 0019)", f"/{root_layer.defaultPrim}"))

    for layer in stage.GetLayerStack(includeSessionLayers=False):
        issues.extend(_layer_paths(layer))

    units = _project_units(project if project is not None else find_project_root(path.parent))
    motion_only = False
    try:
        motion_only = is_motion_only(contrib)
    except Exception:              # noqa: BLE001
        pass
    if not motion_only:            # a motion clip inherits units from its asset
        issues.extend(_units_issues(root_layer, units))
    issues.extend(_time_issues(stage, root_layer, units))

    predicate = Usd.PrimAllPrimsPredicate
    meshes_without_extent: list[str] = []
    look_geometry: list[str] = []
    is_look = bool(contrib and contrib["kind"] == "asset" and contrib.get("department") == "look")
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), predicate):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        if prim.GetSpecifier() == Sdf.SpecifierDef and is_look:
            look_geometry.append(prim.GetPath().pathString)
        if prim.GetSpecifier() == Sdf.SpecifierDef and not UsdGeom.Mesh(prim).GetExtentAttr().HasAuthoredValue():
            meshes_without_extent.append(prim.GetPath().pathString)
    issues.extend(_summarize(meshes_without_extent, "mesh sans extent"))
    issues.extend(_summarize(look_geometry, "couche look qui definit de la geometrie"))
    return issues
