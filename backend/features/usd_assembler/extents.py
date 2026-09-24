# extents.py — extentsHint for product entries (USD strategy R2).
#
# A component / assembly entry holds its content behind a payload. When the payload
# is not loaded (Houdini, usdview, farm preview), the only bound a client can draw or
# cull with is the model's `extentsHint`. We compute it once, when the version is
# written, and author it on the entry root prim.
#
# Never raises: a missing hint only costs a less precise viewport box.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger("usd_assembler.extents")

HINT_ATTR = "extentsHint"


def _has_hint(prim) -> bool:
    attr = prim.GetAttribute(HINT_ATTR)
    return bool(attr) and attr.HasAuthoredValue()


def compute_extents_hint(layer_path: str | Path):
    """Per-purpose extents (Vt.Vec3fArray) of the default prim of *layer_path*, or None.

    Models below the root that already carry an extentsHint are used as is and their
    payloads stay unloaded (an assembly never reads its components' geometry); the
    others are loaded so their real geometry counts.
    """
    try:
        from pxr import Usd, UsdGeom
    except ImportError:
        return None
    try:
        stage = Usd.Stage.Open(str(layer_path), Usd.Stage.LoadNone)
        root = stage.GetDefaultPrim() if stage is not None else None
        if not root:
            return None
        stage.Load(root.GetPath(), Usd.LoadWithoutDescendants)
        predicate = Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract
        for prim in Usd.PrimRange(root, predicate):
            if prim == root:
                continue
            if prim.IsModel() and _has_hint(prim):
                continue
            if prim.HasAuthoredPayloads() and not prim.IsLoaded():
                stage.Load(prim.GetPath(), Usd.LoadWithDescendants)
        return _purpose_hint(root, predicate)
    except Exception as exc:      # noqa: BLE001 - a hint is never worth a failed version
        log.warning("extentsHint skipped for %s: %s", Path(str(layer_path)).name, exc)
        return None


def _purpose_hint(root, predicate):
    """extentsHint layout: one (min, max) pair per purpose in GetOrderedPurposeTokens()
    order, trailing empty purposes dropped.

    Two sources, united per purpose, in *root* space:
    * BBoxCache with extent hints: gprims, and models (instances) that carry a hint;
    * rest points of every PointBased prim: a SkelRoot bound is computed from its
      joints only (UsdSkel), which misses the skinned meshes of a character.
    """
    from pxr import Gf, Usd, UsdGeom, Vt

    time = Usd.TimeCode.EarliestTime()
    purposes = list(UsdGeom.Imageable.GetOrderedPurposeTokens())
    ranges = {p: Gf.Range3d() for p in purposes}
    for p in purposes:
        cache = UsdGeom.BBoxCache(time, [p], useExtentsHint=True)
        ranges[p].UnionWith(cache.ComputeUntransformedBound(root).ComputeAlignedRange())
    xforms = UsdGeom.XformCache(time)
    for prim in Usd.PrimRange(root, predicate):
        if not prim.IsA(UsdGeom.PointBased):
            continue
        points = UsdGeom.PointBased(prim).GetPointsAttr().Get(time)
        if not points:
            continue
        ext = UsdGeom.PointBased.ComputeExtent(points)
        if not ext or len(ext) != 2:
            continue
        purpose = UsdGeom.Imageable(prim).ComputePurpose()
        if purpose not in ranges:
            continue
        matrix, _ = xforms.ComputeRelativeTransform(prim, root)
        box = Gf.BBox3d(Gf.Range3d(Gf.Vec3d(ext[0]), Gf.Vec3d(ext[1])), matrix)
        ranges[purpose].UnionWith(box.ComputeAlignedRange())
    while purposes and ranges[purposes[-1]].IsEmpty():
        purposes.pop()
    if not purposes:
        return None                 # no geometry yet: no hint rather than an inverted box
    values = []
    for p in purposes:
        rng = ranges[p]
        values += [Gf.Vec3f(rng.GetMin()), Gf.Vec3f(rng.GetMax())]
    return Vt.Vec3fArray(values)


def author_extents_hint(prim_spec, hint) -> bool:
    """Write *hint* as `uniform float3[] extentsHint` on an Sdf prim spec."""
    if hint is None:
        return False
    from pxr import Sdf

    attr = prim_spec.attributes.get(HINT_ATTR)
    if attr is None:
        attr = Sdf.AttributeSpec(prim_spec, HINT_ATTR, Sdf.ValueTypeNames.Float3Array,
                                 Sdf.VariabilityUniform)
    attr.default = hint
    return True
