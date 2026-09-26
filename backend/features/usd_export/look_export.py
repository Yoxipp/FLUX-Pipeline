# look_export.py — author the "look" department layer of an asset (ADR 0019, A1b).
#
# The DCC exports its materials to a throwaway USD (mayaUSDExport, Houdini USD ROP);
# this module reads that file with pxr and rewrites it into the FLUX shape:
#   /<NAME>                      over (the model layer gives the type)
#   /<NAME>/mtl/<Material>       the UsdShade materials, copied as-is
#   /<NAME>/geo/render/<mesh>    over + MaterialBindingAPI -> ../../mtl/<Material>
# No geometry is ever defined in a look layer: it composes over the model layer of the
# same asset (component_auto sublayers rig > look > model).
#
# Texture paths are rewritten relative to the version folder, and point at the
# published ".tx" sibling when texture_conform made one (ADR 0019 / incoherence 8).
#
# pxr is imported at module load: only the exporters and their tests import this
# module, never the sidecar boot (the FastAPI process stays pxr-free).

from __future__ import annotations

import json
import os
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdShade, UsdUtils

from core.logger import get_logger

from ..usd_assembler.structure.naming import sanitize_token
from .contract import mesh_prim_names
from .skel_export import GEO_RENDER_SCOPE

__all__ = ["ASSIGN_SET", "MTL_SCOPE", "assign_info", "author_look_layer", "publish_look_asset"]

log = get_logger("usd_export.look")

MTL_SCOPE = "mtl"
_TX_EXT = ".tx"
# ADR 0035: the variantSet of the material assignments, same name on every asset.
ASSIGN_SET = "assign"


# ── helpers ─────────────────────────────────────────────────────────────────────

def _new_layer(path: Path, fmt: str) -> Sdf.Layer:
    args = {"format": fmt} if fmt in ("usda", "usdc") else {}
    return Sdf.Layer.CreateNew(str(path).replace("\\", "/"), args=args)


def _rel(path: Path, start: Path) -> str:
    """*path* relative to *start* (forward slashes); absolute posix across drives."""
    try:
        return os.path.relpath(str(path), str(start)).replace(os.sep, "/")
    except ValueError:
        return Path(path).as_posix()


def _define_scopes(stage: Usd.Stage, path: str) -> None:
    """Scope prims for every missing ancestor between the root and *path*."""
    parts = [p for p in path.split("/") if p]
    for i in range(2, len(parts) + 1):
        sub = "/" + "/".join(parts[:i])
        if not stage.GetPrimAtPath(sub):
            UsdGeom.Scope.Define(stage, sub)


def _source_dir(stage: Usd.Stage) -> Path:
    """Folder the source layer lives in (texture paths resolve against it)."""
    real = stage.GetRootLayer().realPath
    return Path(real).parent if real else Path.cwd()


def _tx_sibling(path: Path) -> Path:
    """The ".tx" texture_conform writes beside *path* (same stem, same folder)."""
    return path.with_suffix(_TX_EXT)


def _materials(stage: Usd.Stage) -> list[Usd.Prim]:
    return [p for p in stage.Traverse() if p.IsA(UsdShade.Material)]


def _bound_material(prim: Usd.Prim) -> Usd.Prim | None:
    """The material bound on *prim*, inherited bindings included, or None."""
    try:
        mat, _rel_ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    except Exception as exc:                       # pragma: no cover - version guard
        log.warning("binding non lu sur %s: %s", prim.GetPath(), exc)
        return None
    return mat.GetPrim() if mat else None


def _retarget_textures(layer: Sdf.Layer, source_dir: Path, dest_dir: Path,
                       *, prefer_tx: bool = True) -> tuple[int, list[str]]:
    """Rewrite every asset-valued attribute of *layer* to a path relative to *dest_dir*.

    A texture that has a conformed ".tx" sibling is pointed at the ".tx" instead of the
    source image, so the published textures are finally referenced by a layer.
    Returns (number of rewritten paths, warnings).
    """
    rewritten = 0
    warnings: list[str] = []

    def _resolve(raw: str) -> Path | None:
        if not raw:
            return None
        p = Path(raw.replace("\\", "/"))
        return p if p.is_absolute() else (source_dir / p)

    def _one(value: Sdf.AssetPath) -> Sdf.AssetPath | None:
        nonlocal rewritten
        target = _resolve(value.path)
        if target is None:
            return None
        # A UDIM / <UDIM> pattern never exists on disk: conform its siblings by stem.
        tx = _tx_sibling(target)
        if prefer_tx and (tx.is_file() or ("<UDIM>" in target.name and tx.parent.is_dir()
                                           and any(tx.parent.glob(f"{target.stem.split('.')[0]}*{_TX_EXT}")))):
            target = tx
        elif not target.exists() and "<UDIM>" not in target.name:
            warnings.append(f"texture introuvable : {value.path}")
        rewritten += 1
        return Sdf.AssetPath(_rel(target, dest_dir))

    def _walk(spec: Sdf.PrimSpec) -> None:
        for attr in spec.attributes:
            if not attr.HasDefaultValue():
                continue
            if attr.typeName == Sdf.ValueTypeNames.Asset:
                new = _one(attr.default)
                if new is not None:
                    attr.default = new
            elif attr.typeName == Sdf.ValueTypeNames.AssetArray:
                values = [_one(v) or v for v in attr.default]
                attr.default = Sdf.AssetPathArray(values)
        for child in spec.nameChildren:
            _walk(child)

    for root in layer.rootPrims:
        _walk(root)
    return rewritten, warnings


# ── assign variants (ADR 0035) ──────────────────────────────────────────────────
# One Solaris export holds every material plus a variantSet whose variants only change
# the material assignments (variant block of Assign Material LOPs). FLUX splits it in
# the same publish: <base>_mtl (all the materials, no binding) and <base>_assign
# (over /<NAME> + variantSet "assign", one variant per assignment, bindings only).

_PURPOSES = (UsdShade.Tokens.allPurpose, UsdShade.Tokens.full, UsdShade.Tokens.preview)


def _direct_material(prim: Usd.Prim) -> Sdf.Path | None:
    """Material a prim binds itself (any purpose), inherited bindings not included."""
    api = UsdShade.MaterialBindingAPI(prim)
    for purpose in _PURPOSES:
        try:
            mat = api.GetDirectBinding(materialPurpose=purpose).GetMaterial()
        except Exception:                          # pragma: no cover - version guard
            mat = None
        if mat:
            return mat.GetPath()
    return None


def _binding_map(stage: Usd.Stage) -> dict[str, Sdf.Path]:
    """{prim path relative to /<NAME>: bound material} of an export.

    * Every prim that binds a material itself counts, typeless "over" prims included:
      a Solaris look exported after a Layer Break holds no geometry, only the Assign
      Material opinions on the paths of the imported asset (2026-09-26, UTAH:
      the feathers stay out of the export).
    * A path under a "geo" prim keeps its tail (/UTAH/geo/render/body -> geo/render/body,
      a group like geo/render/feathers stays a group); a geometry elsewhere lands
      under geo/render by the model layer's naming rule (contract.mesh_prim_names).
    * A geometry that only inherits its binding (native DCC scene) is bound itself.
    """
    pred = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)
    found: dict[Sdf.Path, Sdf.Path] = {}
    gprims: set[Sdf.Path] = set()
    it = iter(Usd.PrimRange.Stage(stage, pred))
    for prim in it:
        if prim.IsA(UsdShade.Material):
            it.PruneChildren()                         # shaders never bind
            continue
        mat = _direct_material(prim)
        if prim.IsA(UsdGeom.Gprim):
            gprims.add(prim.GetPath())
            if mat is None:
                bound = _bound_material(prim)
                mat = bound.GetPath() if bound is not None else None
        if mat is not None:
            found[prim.GetPath()] = mat
    loose = [p for p in found if "geo" not in p.pathString.split("/")[1:]]
    names = dict(zip(loose, mesh_prim_names([(p.name, p.pathString) for p in loose], sanitize_token)))
    out: dict[str, Sdf.Path] = {}
    for path, mat in found.items():
        parts = path.pathString.split("/")[1:]
        if "geo" in parts[1:]:
            rel = "/".join(parts[parts.index("geo", 1):])
        elif len(parts) == 1 and path not in gprims:
            rel = ""                                   # bound on the asset root itself
        else:
            rel = f"{GEO_RENDER_SCOPE}/{names[path]}"
        out[rel] = mat
    return out


def _binding_report(stage: Usd.Stage) -> str:
    """What an export holds about bindings, for an error without any binding."""
    pred = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)
    prims = list(stage.Traverse(pred))
    rels = [(p.GetPath(), r) for p in prims for r in p.GetRelationships()
            if r.GetName().startswith("material:binding")]
    geo = sum(1 for p in prims if p.IsA(UsdGeom.Gprim))
    sample = ", ".join(f"{path} -> {[str(t) for t in r.GetTargets()]}" for path, r in rels[:3])
    return (f"{len(prims)} prims, {geo} geometries, {len(rels)} relations material:binding"
            + (f" ({sample})" if sample else ""))


def _find_assign_sets(stage: Usd.Stage) -> list[tuple[Sdf.Path, str, list[str], str]]:
    """Variant sets authored in the export itself whose variants change material
    bindings: [(prim path, set name, variants, selection)].

    Only the export's own layer stack counts: the variant sets a referenced component
    brings (FLUX Import toggles, look block variants) are never an assignment."""
    local = UsdUtils.FlattenLayerStack(stage)
    candidates: list[tuple[Sdf.Path, str, list[str]]] = []

    def _walk(spec: Sdf.PrimSpec) -> None:
        for name, vset in spec.variantSets.items():
            names = [v.name for v in vset.variantList]
            if len(names) > 1:
                candidates.append((spec.path, name, names))
        for child in spec.nameChildren:
            _walk(child)

    for root in local.rootPrims:
        _walk(root)
    if not candidates:
        return []
    found = []
    session = stage.GetSessionLayer()
    with Usd.EditContext(stage, session):
        for path, name, names in candidates:
            vset = stage.GetPrimAtPath(path).GetVariantSet(name)
            selection = vset.GetVariantSelection() or names[0]
            seen = set()
            for v in names:
                vset.SetVariantSelection(v)
                seen.add(tuple(sorted(_binding_map(stage).items())))
            vset.SetVariantSelection(selection)
            if len(seen) > 1:
                found.append((path, name, names, selection))
    session.Clear()
    return found


def _no_material(stage: Usd.Stage) -> str:
    """Error of an export without UsdShade material, with what it does hold."""
    roots = [p.GetName() for p in stage.GetPseudoRoot().GetChildren()][:8]
    n = sum(1 for _ in stage.Traverse())
    kinds = sorted({p.GetTypeName() for p in stage.Traverse() if p.GetTypeName()})[:8]
    return ("aucun materiau dans l'export : rien a publier dans le departement look "
            f"({n} prims, racines : {', '.join(roots) or 'aucune'} ; types : {', '.join(kinds) or 'aucun'}). "
            "Verifier le node LOP exporte (node selectionne, sinon node affiche de /stage) : il doit "
            "etre apres la Material Library")


def _over_chain(parent: Sdf.PrimSpec, rel_path: str) -> Sdf.PrimSpec:
    """Over specs for each part of *rel_path* below *parent* (existing ones reused)."""
    spec = parent
    for part in [p for p in rel_path.split("/") if p]:
        spec = spec.nameChildren.get(part) or Sdf.PrimSpec(spec, part, Sdf.SpecifierOver)
    return spec


def _bind_spec(spec: Sdf.PrimSpec, material: str) -> None:
    spec.SetInfo("apiSchemas", Sdf.TokenListOp.Create(prependedItems=["MaterialBindingAPI"]))
    rel = spec.relationships.get("material:binding") or \
        Sdf.RelationshipSpec(spec, "material:binding", False)
    rel.targetPathList.explicitItems = [Sdf.Path(material)]


def _variants_of_stage(src_stage: Usd.Stage, found: list) -> tuple[list, str, list[str]]:
    """[(variant, flattened layer)], default, warnings: each variant of the export's
    assign set composed once (selection in the session layer, the file is untouched)."""
    warnings: list[str] = []
    path, set_name, names, selection = found[0]
    for other in found[1:]:
        warnings.append(f"variantSet {other[1]} ({other[0]}) ignore : un seul jeu d'assign par look, "
                        f"{set_name} garde")
    flats = []
    session = src_stage.GetSessionLayer()
    with Usd.EditContext(src_stage, session):
        vset = src_stage.GetPrimAtPath(path).GetVariantSet(set_name)
        for raw in names:
            vset.SetVariantSelection(raw)
            flats.append((raw, src_stage.Flatten()))
    session.Clear()
    return flats, selection, warnings


def _variants_of_files(files: dict[str, str | Path]) -> list:
    """[(variant, flattened layer)] from one DCC export per variant (Houdini writes each
    variant with its selection set, a flattened stage like the classic look export)."""
    out = []
    for name, path in files.items():
        stage = Usd.Stage.Open(str(path).replace("\\", "/"))
        if stage is None:
            raise ValueError(f"USD illisible (variante {name}) : {path}")
        out.append((name, stage.Flatten()))
    return out


def _author_assign_look(flats: list, selection: str, dest: Path, base: str, token: str,
                        fmt: str, prefer_tx: bool, source_dir: Path,
                        warnings: list[str] | None = None) -> dict:
    root_path = f"/{token}"
    mtl_root = f"{root_path}/{MTL_SCOPE}"
    warnings = list(warnings or [])
    variant_names = [sanitize_token(v) for v, _ in flats]
    default = sanitize_token(selection) if selection else variant_names[0]

    # 1. every variant: its bindings, and the materials it shows.
    stages = [Usd.Stage.Open(flat) for _, flat in flats]
    per_variant: dict[str, dict[str, Sdf.Path]] = {
        v: _binding_map(st) for v, st in zip(variant_names, stages)}
    flats = [flat for _, flat in flats]

    # 2. shaders layer: all the materials of all the variants, never a binding.
    mtl_p = dest / f"{base}_mtl.{fmt}"
    mtl_layer = _new_layer(mtl_p, fmt)
    mtl_stage = Usd.Stage.Open(mtl_layer)
    _define_scopes(mtl_stage, mtl_root)
    mtl_layer.GetPrimAtPath(root_path).specifier = Sdf.SpecifierOver
    moved: dict[Sdf.Path, Sdf.Path] = {}
    for flat in flats:
        flat_stage = Usd.Stage.Open(flat)          # kept alive while its prims are read
        for mat in _materials(flat_stage):
            if mat.GetPath() in moved:
                continue
            leaf = sanitize_token(mat.GetName())
            target = Sdf.Path(f"{mtl_root}/{leaf}")
            if mtl_layer.GetPrimAtPath(target):
                warnings.append(f"materiau en double ignore : {mat.GetPath()}")
                continue
            if not mat.GetChildren():
                warnings.append(f"materiau vide (aucun shader) : {mat.GetName()}")
            if not Sdf.CopySpec(flat, mat.GetPath(), mtl_layer, target):
                warnings.append(f"materiau non copie : {mat.GetPath()}")
                continue
            moved[mat.GetPath()] = target
    if not moved:
        raise ValueError(_no_material(stages[0]))
    for old, new in moved.items():
        _relink_connections(mtl_layer, old, new)
    # A material may carry a binding of its own (rare): the assign layer owns them all.
    mtl_stage = Usd.Stage.Open(mtl_layer)
    mtl_stage.SetDefaultPrim(mtl_stage.GetPrimAtPath(root_path))
    textures, tex_warnings = _retarget_textures(mtl_layer, source_dir, dest, prefer_tx=prefer_tx)
    warnings += tex_warnings
    mtl_layer.Save()
    _assert_no_geometry(mtl_layer)

    # 3. assign layer: a binding the same in every variant stays outside the variantSet
    # (a local opinion would beat a variant one), the others go in their variant.
    assign_p = dest / f"{base}_assign.{fmt}"
    assign_layer = _new_layer(assign_p, fmt)
    root = Sdf.PrimSpec(assign_layer, token, Sdf.SpecifierOver)
    vset_spec = Sdf.VariantSetSpec(root, ASSIGN_SET)
    bound = sorted({g for b in per_variant.values() for g in b})
    common = {g for g in bound
              if all(per_variant[v].get(g) == per_variant[variant_names[0]].get(g)
                     for v in variant_names)}
    bindings = 0
    skipped: set[Sdf.Path] = set()

    def _bind(parent: Sdf.PrimSpec, rel: str, material: Sdf.Path) -> bool:
        if material not in moved:
            skipped.add(material)
            return False
        spec = _over_chain(parent, rel)
        _bind_spec(spec, str(moved[material]))
        return True

    for g in sorted(common):
        bindings += _bind(root, g, per_variant[variant_names[0]][g])
    empty = []
    for v in variant_names:
        var = Sdf.VariantSpec(vset_spec, v)
        own = [g for g in sorted(per_variant[v]) if g not in common]
        bindings += sum(_bind(var.primSpec, g, per_variant[v][g]) for g in own)
        if not own and not common:
            empty.append(v)
    for mat in sorted(skipped):
        warnings.append(f"liaison vers un materiau non publie ignoree : {mat}")
    if empty:
        warnings.append("variante(s) d'assign sans aucune liaison : " + ", ".join(empty))
    if not bindings:
        raise ValueError("aucune geometrie liee dans les variantes d'assign : rien a publier ("
                         + _binding_report(stages[0]) + ")")
    root.variantSetNameList.prependedItems = [ASSIGN_SET]
    root.variantSelections[ASSIGN_SET] = default if default in variant_names else variant_names[0]
    assign_layer.defaultPrim = token
    assign_layer.Save()
    _assert_no_geometry(assign_layer)

    # 4. root file: assign over the shaders; the variants are listed for FLUX (component,
    # importer, Library) without composing the stage.
    info = {"variants": variant_names, "default": root.variantSelections[ASSIGN_SET]}
    root_p = dest / f"{base}.{fmt}"
    root_layer = _new_layer(root_p, fmt)
    root_layer.subLayerPaths = [assign_p.name, mtl_p.name]
    root_layer.defaultPrim = token
    # JSON string: USD dictionaries reject untyped lists (same as the component entry).
    root_layer.customLayerData = {"flux": {"assign": json.dumps(info, sort_keys=True)}}
    root_layer.Save()

    log.info("Authored look %s: %d materiaux, variantes d'assign %s (%d liaisons)",
             base, len(moved), ", ".join(variant_names), bindings)
    return {"look": mtl_p, "root": root_p, "mtl": mtl_p, "assign": assign_p,
            "assign_variants": variant_names, "assign_default": info["default"],
            "materials": len(moved), "bindings": bindings, "textures": textures,
            "warnings": warnings}


def assign_info(path: str | Path, _depth: int = 0) -> dict:
    """{"variants": [...], "default": v} of a look publish with assign variants (its root
    layer, or a LAST pointer / layer that sublayers it); {} otherwise."""
    try:
        layer = Sdf.Layer.FindOrOpen(str(path).replace("\\", "/"))
    except Exception:                                  # unreadable file: no variants
        return {}
    if layer is None:
        return {}
    info = dict(layer.customLayerData).get("flux", {}).get("assign")
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except ValueError:
            info = None
    if isinstance(info, dict) and info:
        return {"variants": list(info.get("variants") or []), "default": str(info.get("default") or "")}
    if _depth >= 3:
        return {}
    for sub in layer.subLayerPaths:
        found = assign_info(layer.ComputeAbsolutePath(sub), _depth + 1)
        if found:
            return found
    return {}


# ── public API ────────────────────────────────────────────────────────────────

def author_look_layer(source: str | Path, dest_dir: str | Path, base: str, *,
                      root_name: str | None = None, fmt: str = "usda",
                      prefer_tx: bool = True,
                      variant_sources: dict[str, str | Path] | None = None,
                      variant_default: str | None = None) -> dict:
    """Rewrite the DCC export *source* into the look layer of *base* inside *dest_dir*.

    Writes ``<base>_look.<fmt>`` (materials + bindings, no geometry) and the root
    ``<base>.<fmt>`` that sublayers it, exactly like the light export does for
    model / skel. *root_name* is the NAME token (the prim root, ADR 0019).

    Returns {"look": Path, "root": Path, "materials": int, "bindings": int,
    "textures": int, "warnings": [...]}. Raises ValueError when the export carries no
    material at all (nothing to publish in the look department).
    """
    src = Path(source)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    token = sanitize_token(root_name or base)
    root_path = f"/{token}"
    mtl_root = f"{root_path}/{MTL_SCOPE}"

    src_stage = Usd.Stage.Open(str(src).replace("\\", "/"))
    if src_stage is None:
        raise ValueError(f"USD illisible : {src}")
    if variant_sources:
        # ADR 0035, Houdini: one flattened export per assign variant.
        return _author_assign_look(_variants_of_files(variant_sources), variant_default or "",
                                   dest, base, token, fmt, prefer_tx, _source_dir(src_stage))
    found = _find_assign_sets(src_stage)
    if found:
        # ADR 0035: variant block of Assign Material kept in the export -> shaders + assign.
        flats, selection, warns = _variants_of_stage(src_stage, found)
        return _author_assign_look(flats, selection, dest, base, token, fmt, prefer_tx,
                                   _source_dir(src_stage), warns)
    flat = src_stage.Flatten()
    flat_stage = Usd.Stage.Open(flat)
    source_dir = _source_dir(src_stage)

    materials = _materials(flat_stage)
    if not materials:
        raise ValueError(_no_material(flat_stage))

    warnings: list[str] = []
    for mat in materials:
        if not mat.GetChildren():   # e.g. Maya's default lambert1, exported empty
            warnings.append(f"materiau vide (aucun shader) : {mat.GetName()}")
    look_p = dest / f"{base}_look.{fmt}"
    look_layer = _new_layer(look_p, fmt)
    look_stage = Usd.Stage.Open(look_layer)
    _define_scopes(look_stage, mtl_root)
    # Defining /<NAME>/mtl also defines its ancestors: keep the root an "over", the
    # model layer owns its type (SkelRoot / Xform).
    look_layer.GetPrimAtPath(root_path).specifier = Sdf.SpecifierOver

    # 1. materials, copied whole (shaders, node graphs, connections) under /<NAME>/mtl.
    moved: dict[Sdf.Path, Sdf.Path] = {}
    for mat in materials:
        leaf = sanitize_token(mat.GetName())
        target = Sdf.Path(f"{mtl_root}/{leaf}")
        if look_layer.GetPrimAtPath(target):
            warnings.append(f"materiau en double ignore : {mat.GetPath()}")
            continue
        if not Sdf.CopySpec(flat, mat.GetPath(), look_layer, target):
            warnings.append(f"materiau non copie : {mat.GetPath()}")
            continue
        moved[mat.GetPath()] = target
    # Sdf.CopySpec keeps connection targets verbatim: a shader connection still names
    # the pre-copy path (/Looks/x/shader), so move them by prefix to /<NAME>/mtl/x/...
    for old, new in moved.items():
        _relink_connections(look_layer, old, new)
    look_layer.Save()

    # 2. bindings: one "over" per bound mesh, at the FLUX prim path of the model layer.
    look_stage = Usd.Stage.Open(look_layer)
    bindings = 0
    for rel, mat in sorted(_binding_map(flat_stage).items()):
        if mat not in moved:
            warnings.append(f"liaison vers un materiau non publie ignoree : {mat}")
            continue
        over = look_stage.OverridePrim(f"{root_path}/{rel}".rstrip("/"))
        UsdShade.MaterialBindingAPI.Apply(over)
        UsdShade.MaterialBindingAPI(over).Bind(UsdShade.Material(look_stage.GetPrimAtPath(moved[mat])))
        bindings += 1
    if not bindings:
        warnings.append("aucune geometrie liee : le look publie ne contient que des materiaux ("
                        + _binding_report(flat_stage) + ")")

    look_stage.SetDefaultPrim(look_stage.GetPrimAtPath(root_path))
    look_layer.Save()

    # 3. textures -> relative, ".tx" when conformed.
    textures, tex_warnings = _retarget_textures(look_layer, source_dir, dest,
                                                prefer_tx=prefer_tx)
    warnings += tex_warnings
    look_layer.Save()

    _assert_no_geometry(look_layer)

    # 4. root file the resolver picks (same shape as the light export).
    root_p = dest / f"{base}.{fmt}"
    root_layer = _new_layer(root_p, fmt)
    root_layer.subLayerPaths = [look_p.name]
    root_layer.defaultPrim = token
    root_layer.Save()

    log.info("Authored look layer %s (%d materiaux, %d liaisons, %d textures)",
             base, len(moved), bindings, textures)
    return {"look": look_p, "root": root_p, "materials": len(moved), "bindings": bindings,
            "textures": textures, "warnings": warnings}


def _relink_connections(layer: Sdf.Layer, old: Sdf.Path, new: Sdf.Path) -> None:
    """Repoint attribute connections that still name the pre-copy prim path."""

    def _walk(spec: Sdf.PrimSpec) -> None:
        for attr in spec.attributes:
            paths = list(attr.connectionPathList.explicitItems)
            if not paths:
                continue
            fixed = [p.ReplacePrefix(old, new) if p.HasPrefix(old) else p for p in paths]
            if fixed != paths:
                attr.connectionPathList.explicitItems = fixed
        for child in spec.nameChildren:
            _walk(child)

    target = layer.GetPrimAtPath(new)
    if target is not None:
        _walk(target)


def _assert_no_geometry(layer: Sdf.Layer) -> None:
    """A look layer defines materials only: a defined Gprim would fight the model layer."""
    bad: list[str] = []

    def _walk(spec: Sdf.PrimSpec) -> None:
        if spec.specifier == Sdf.SpecifierDef and spec.typeName in ("Mesh", "BasisCurves",
                                                                    "Points", "NurbsCurves"):
            bad.append(str(spec.path))
        for child in spec.nameChildren:
            _walk(child)

    for root in layer.rootPrims:
        _walk(root)
    if bad:
        raise ValueError("le layer look contient de la geometrie definie : " + ", ".join(bad))


def publish_look_asset(source: str | Path, project_path: str | Path, *,
                       fmt: str = "usda", dest_dir: str | Path, base_name: str,
                       user: str = "", prefer_tx: bool = True,
                       variant_sources: dict[str, str | Path] | None = None,
                       variant_default: str | None = None) -> dict:
    """Publish the look department of an asset from a DCC export (ADR 0019 A1b).

    Same layout as ``publish_light_asset``: an immutable ``<base>_vNNN/`` folder holding
    the root + look layer, a ``<base>_LAST.<fmt>`` pointer beside it, then the asset
    (component) is regenerated from its departments.
    """
    from features.folder_manager.naming_validator import format_version
    from features.publisher import last_pointer as lp
    from features.publisher.publish_core import ensure_dir
    from features.publisher.publish_layout import (
        discard_rendered_version, reserve_version, sequence_folder,
    )

    from .departments import contribution

    contrib = contribution(base_name)
    if contrib is None or contrib["kind"] != "asset" or contrib["department"] != "look":
        raise ValueError(
            f"{base_name} n'est pas un publish de look : le departement look se publie "
            "avec la task SHADING d'un asset")

    parent = Path(dest_dir)
    ensure_dir(parent)
    ext = f".{fmt.lstrip('.')}"
    ver = reserve_version(parent, base_name, ext)
    folder = sequence_folder(parent, base_name, ver)
    try:
        authored = author_look_layer(source, folder, base_name,
                                     root_name=contrib["name"] or None,
                                     fmt=fmt.lstrip("."), prefer_tx=prefer_tx,
                                     variant_sources=variant_sources,
                                     variant_default=variant_default)
    except Exception:
        discard_rendered_version(parent, base_name, ext, ver, is_sequence=True)
        raise

    root = authored["root"]
    last = lp.write_last(parent, base_name, ext, folder, ver, lp.MODE_LAYER, user=user,
                         layer_target=f"{folder.name}/{root.name}")

    from features.publisher.usd_publish_hooks import after_usd_publish

    hooked = after_usd_publish(parent, base_name, ext, root, user=user)
    component = hooked["component"]

    version_str = format_version(ver)
    log.info("Published look %s (%s) -> %s", base_name, version_str, folder)
    for w in authored["warnings"]:
        log.warning("Look %s: %s", base_name, w)
    return {"root": last or root, "version": version_str, "folder": folder,
            "version_root": root,
            "layers": {k: authored[k] for k in ("look", "mtl", "assign") if k in authored} | {"root": root},
            "assign_variants": authored.get("assign_variants", []),
            "materials": authored["materials"], "bindings": authored["bindings"],
            "textures": authored["textures"],
            "component": component["version"] if component else None,
            "warnings": authored["warnings"]}
