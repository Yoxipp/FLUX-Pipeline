# layout_publish.py — publish the placement layer of an assembly from a DCC
# (USD_ASSEMBLER_V2 section 10 point 3, 2026-09-17). The DCC only reports a local
# matrix per instance; this module authors the layer with pxr, so Houdini and Maya
# share one writer and neither needs its own USD export. Output:
#   usd/assembly/<ASM>/layout/<ASM>_layout_vNNN.usda   over /<ASM>/<CLASS>/<INSTANCE>
#                                                      xformOp:transform only
#   usd/assembly/<ASM>/<ASM>_layout_LAST.usda          pointer layer (ADR 0017)
# then a new assembly version whose payload sublayers that layout vNNN (frozen: an
# assembly version never moves when a later layout is published).

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

from .assembly_v2 import (
    ASSEMBLY_EXT, DEFAULT_CLASS, _check_name, assembly_root, current_entry,
    read_instances, write_version,
)
from .structure.naming import sanitize_token

log = get_logger("usd_assembler.layout_publish")

LAYOUT_SUBDIR = "layout"


def layout_base(name: str) -> str:
    return f"{name}_layout"


def _matrix(values) -> list[float]:
    flat = [float(v) for v in values]
    if len(flat) != 16:
        raise ValueError(f"matrice invalide ({len(flat)} valeurs au lieu de 16)")
    return flat


def match_placements(instances: list[dict], placements: dict[str, list]) -> tuple[list[tuple[dict, list[float]]], list[str]]:
    """Pair DCC placements with assembly instances by instance name (unique per assembly).

    Keys may be ``CLASS/INSTANCE``, ``/<ASM>/CLASS/INSTANCE`` or a DCC path: only the
    last segment counts. Returns ([(instance, matrix)], warnings).
    """
    by_name = {i["name"]: i for i in instances}
    rows: list[tuple[dict, list[float]]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for key, values in placements.items():
        inst_name = str(key).replace("|", "/").strip("/").split("/")[-1].split(":")[-1]
        inst = by_name.get(inst_name)
        if inst is None:
            warnings.append(f"instance absente de l'assembly, ignoree : {key}")
            continue
        if inst_name in seen:
            warnings.append(f"placement en double, premier garde : {key}")
            continue
        seen.add(inst_name)
        rows.append((inst, _matrix(values)))
    missing = [i["name"] for i in instances if i["name"] not in seen]
    if missing:
        warnings.append("sans placement dans la scene (restent a l'origine) : " + ", ".join(missing))
    return rows, warnings


def author_layout(path: Path, name: str, rows: list[tuple[dict, list[float]]], meta: dict) -> Path:
    """Write the overs-only layout layer at *path*."""
    from pxr import Gf, Sdf, Vt

    path.parent.mkdir(parents=True, exist_ok=True)
    layer = Sdf.Layer.CreateNew(str(path))
    root = Sdf.PrimSpec(layer, name, Sdf.SpecifierOver)
    groups: dict[str, Sdf.PrimSpec] = {}
    for inst, m in rows:
        cls = sanitize_token(inst["class"]) or DEFAULT_CLASS
        group = groups.get(cls)
        if group is None:
            group = groups[cls] = Sdf.PrimSpec(root, cls, Sdf.SpecifierOver)
        prim = Sdf.PrimSpec(group, inst["name"], Sdf.SpecifierOver)
        op = Sdf.AttributeSpec(prim, "xformOp:transform", Sdf.ValueTypeNames.Matrix4d)
        op.default = Gf.Matrix4d(*m)
        order = Sdf.AttributeSpec(prim, "xformOpOrder", Sdf.ValueTypeNames.TokenArray,
                                  Sdf.VariabilityUniform)
        order.default = Vt.TokenArray(["xformOp:transform"])
    layer.defaultPrim = name
    layer.customLayerData = {"flux_layout": {k: str(v) for k, v in meta.items()}}
    layer.Save()
    return path


def publish_layout(project_path: str | Path, name: str, placements: dict[str, list], *,
                   user: str = "", source: str = "") -> dict:
    """Publish a layout vNNN + LAST from DCC *placements*, then a new assembly version.

    Returns {"layout_version", "layout", "layout_last", "version", "last", "warnings"}.
    """
    from features.folder_manager.naming_validator import format_version
    from features.publisher import last_pointer as lp
    from features.publisher.publish_layout import (
        discard_rendered_version, flat_version_path, reserve_version,
    )

    project = Path(project_path)
    _check_name(name)
    if current_entry(project, name) is None and not (assembly_root(project) / f"{name}{ASSEMBLY_EXT}").is_file():
        raise ValueError(f"assembly introuvable : {name}")
    instances = read_instances(project, name)
    rows, warnings = match_placements(instances, placements or {})
    if not rows:
        raise ValueError(f"aucune instance de l'assembly {name} trouvee dans la scene")

    from .assembly_v2 import ensure_asset

    parent = ensure_asset(project, name)     # a decor is an asset (ADR 0019)
    folder = parent / LAYOUT_SUBDIR
    base = layout_base(name)
    ver = reserve_version(folder, base, ASSEMBLY_EXT)
    path = flat_version_path(folder, base, ver, ASSEMBLY_EXT)
    version = format_version(ver)
    try:
        author_layout(path, name, rows, {"assembly": name, "version": version, "source": source, "user": user})
    except Exception:
        discard_rendered_version(folder, base, ASSEMBLY_EXT, ver)
        raise
    last = lp.write_last(parent, base, ASSEMBLY_EXT, path, ver, lp.MODE_LAYER, user=user,
                         layer_target=f"{LAYOUT_SUBDIR}/{path.name}")
    if last is None:
        warnings.append("layout LAST non mis a jour (fichier verrouille) : la version d'assembly pointe quand meme le nouveau layout")
    log.info("Layout %s %s -> %s (%d placements, %s)", name, version, path, len(rows), source or "?")

    res = write_version(project, name, instances, user=user, force=True, layout=path)
    return {"layout_version": version, "layout": path, "layout_last": last,
            "version": res["version"] if res else None, "last": res.get("last") if res else None,
            "warnings": warnings + (res.get("warnings", []) if res else [])}
