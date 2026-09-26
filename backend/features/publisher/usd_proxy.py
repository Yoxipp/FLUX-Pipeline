# usd_proxy.py - generate lightweight USD proxy geometry (purpose=proxy).
#
# Goal: give every render mesh a decimated sibling tagged purpose=proxy (and every
# render groom a thinned one, ADR 0026), so
# Solaris / usdview draw the light version in the viewport while the renderer
# still uses the full purpose=render mesh. Lighter viewports, no LOD system.
#
# 100% open source, NO license token: reading/writing USD uses pxr (already in
# Flux), decimation uses fast-simplification (MIT). Houdini is deliberately NOT
# used - hython/hbatch would consume a license the moment a SOP cooks.
#
# This is the feature core (like publish_core / texture_conform): the flux_actions
# "generate_proxy" command is a thin wrapper. Runnable offline for measurement:
#   python -m features.publisher.usd_proxy <asset.usd> [-o proxy.usda] [-r 0.9]
#
# Caveats (by design, see docs/CORRECT_BUG_V5/proxy_generation_prompt.md):
#   - fast-simplification does NOT preserve UVs. A purpose=proxy mesh is a
#     silhouette/viewport stand-in, not a finely textured asset. That is fine.
#   - The source must be readable by pxr (USD / Alembic via usdAbc). Houdini-only
#     .bgeo cannot be read here; the pipeline is USD-centred so the source is the
#     published USD.
#   - One proxy level only (YAGNI). No multi-level LOD.
#   - Groom (BasisCurves): the proxy keeps 1 curve in N (N from the reduction, 0.9 ->
#     1 in 10), whole curves, widths and skin kept, other primvars dropped (ADR 0026).

from __future__ import annotations

import argparse
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from pxr import Sdf, Usd, UsdGeom, UsdSkel, Vt

log = logging.getLogger(__name__)

# Below this triangle count a mesh is already cheap: decimating it is not worth
# the quality loss, so we copy it into the proxy unchanged.
DEFAULT_MIN_TRIS = 200
# Fraction of triangles removed by default (0.9 -> keep ~10%).
DEFAULT_REDUCTION = 0.9
# customLayerData key that carries the source hash for skip-if-unchanged.
_HASH_KEY = "flux_proxy_src_sha1"
_TOOL_KEY = "flux_proxy_tool"
# Bumped when the proxy content changes, so older proxies are rebuilt even if their
# source did not change (2: the skin binding follows the proxy, 2026-09-18;
# 3: flux:srcPoint for the RIG department's weights, ADR 0034).
_TOOL_TAG = "flux-usd-proxy/3"
# Per proxy point, the index of the render point it stands for (read by rig_skin).
PROXY_SOURCE_PRIMVAR = "flux:srcPoint"


# USD containers pxr can open for proxy generation.
_USD_EXTS = {".usd", ".usda", ".usdc"}


def is_usd_asset(path: Path) -> bool:
    """True if a path is a USD file we can try to proxy (by extension).

    A non-geometry USD (anim, camera, light layer) still passes this gate; the
    generator itself reports "no render mesh" and the caller skips it.
    """
    return Path(path).suffix.lower() in _USD_EXTS


@dataclass
class ProxyResult:
    """Outcome of proxy-ing one USD asset."""
    src: Path
    dst: Path
    status: str                 # "converted" | "skipped" | "failed"
    meshes: int = 0
    tris_in: int = 0
    tris_out: int = 0
    grooms: int = 0             # BasisCurves prims thinned (ADR 0026)
    curves_in: int = 0
    curves_out: int = 0
    error: str = ""


def sha1_of_file(path: Path, chunk: int = 1 << 20) -> str:
    """Content hash of the source USD, used as the skip key."""
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def triangulate(counts: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Fan-triangulate polygons given USD faceVertexCounts / faceVertexIndices.

    Returns an (M, 3) int array of triangle vertex indices. A polygon of n
    vertices becomes n-2 triangles (v0, v[k], v[k+1]).
    """
    tris: List[Tuple[int, int, int]] = []
    offset = 0
    for count in counts:
        count = int(count)
        if count >= 3:
            base = int(indices[offset])
            for k in range(1, count - 1):
                tris.append((base, int(indices[offset + k]), int(indices[offset + k + 1])))
        offset += count
    if not tris:
        return np.empty((0, 3), dtype=np.int64)
    return np.asarray(tris, dtype=np.int64)


def decimate(
    points: np.ndarray, tri_faces: np.ndarray, target_reduction: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Quadric-decimate a triangle mesh. Returns (points, tri_faces).

    target_reduction is the fraction of triangles removed (clamped to a sane
    open interval). Falls back to the input when there is nothing to reduce.
    """
    new_points, new_faces, _ = decimate_with_mapping(points, tri_faces, target_reduction)
    return new_points, new_faces


def decimate_with_mapping(
    points: np.ndarray, tri_faces: np.ndarray, target_reduction: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``decimate`` plus, for every source point, the index of the proxy point it
    collapsed into (lets per-point data such as skin weights follow the proxy)."""
    import fast_simplification as fs

    identity = np.arange(points.shape[0], dtype=np.int64)
    if tri_faces.shape[0] == 0:
        return points, tri_faces, identity
    reduction = min(max(target_reduction, 0.0), 0.99)
    if reduction <= 0.0:
        return points, tri_faces, identity
    pts = points.astype(np.float32)
    faces = tri_faces.astype(np.int64)
    _, _, collapses = fs.simplify(pts, faces, target_reduction=reduction, return_collapses=True)
    new_points, new_faces, mapping = fs.replay_simplification(pts, faces, collapses)
    return (np.asarray(new_points, dtype=np.float32), np.asarray(new_faces, dtype=np.int64),
            np.asarray(mapping, dtype=np.int64))


def source_representatives(mapping: np.ndarray, n_proxy_points: int) -> np.ndarray:
    """Per proxy point, the first source point that collapsed into it (mapping is
    source -> proxy, -1 = dropped)."""
    rep = np.zeros(n_proxy_points, dtype=np.int64)
    order = np.nonzero(mapping >= 0)[0][::-1]
    rep[mapping[order]] = order
    return rep


def _copy_skin_binding(src: UsdGeom.Gprim, proxy: UsdGeom.Gprim, mapping: np.ndarray,
                       n_proxy_points: int) -> bool:
    """Give the proxy the skin of its source mesh: same skeleton, same bind transform,
    and per proxy point the joint indices / weights of one source point that collapsed
    into it. Without it a viewport showing proxies (Houdini) keeps the mesh rigid while
    the skeleton animates. A source point mapped to -1 was dropped (thinned groom).
    Returns True when a binding was copied."""
    prim = src.GetPrim()
    if not prim.HasAPI(UsdSkel.BindingAPI):
        return False
    s = UsdSkel.BindingAPI(prim)
    ji, jw = s.GetJointIndicesPrimvar(), s.GetJointWeightsPrimvar()
    if not ji or not jw or ji.Get() is None or jw.Get() is None:
        return False
    d = UsdSkel.BindingAPI.Apply(proxy.GetPrim())
    size = ji.GetElementSize()
    indices = np.asarray(ji.Get(), dtype=np.int32)
    weights = np.asarray(jw.Get(), dtype=np.float32)
    if ji.GetInterpolation() == UsdGeom.Tokens.constant:        # rigid binding
        d.CreateJointIndicesPrimvar(True, size).Set(Vt.IntArray.FromNumpy(indices))
        d.CreateJointWeightsPrimvar(True, size).Set(Vt.FloatArray.FromNumpy(weights))
    else:
        rep = source_representatives(mapping, n_proxy_points)
        per_point_i = indices.reshape(-1, size)[rep].reshape(-1)
        per_point_w = weights.reshape(-1, size)[rep].reshape(-1)
        d.CreateJointIndicesPrimvar(False, size).Set(Vt.IntArray.FromNumpy(per_point_i))
        d.CreateJointWeightsPrimvar(False, size).Set(Vt.FloatArray.FromNumpy(per_point_w))
    targets = s.GetSkeletonRel().GetTargets() if s.GetSkeletonRel() else []
    if targets:
        d.CreateSkeletonRel().SetTargets(targets)
    bind = s.GetGeomBindTransformAttr()
    if bind and bind.HasAuthoredValue():
        d.CreateGeomBindTransformAttr(bind.Get())
    joints = s.GetJointsAttr()
    if joints and joints.HasAuthoredValue():
        d.CreateJointsAttr(joints.Get())
    return True


def _iter_render_meshes(stage: Usd.Stage):
    """Yield UsdGeom.Mesh prims that are render geometry (not proxy/guide)."""
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        purpose = UsdGeom.Imageable(prim).GetPurposeAttr().Get()
        if purpose in (UsdGeom.Tokens.proxy, UsdGeom.Tokens.guide):
            continue
        yield UsdGeom.Mesh(prim)


def _iter_render_curves(stage: Usd.Stage):
    """Yield UsdGeom.BasisCurves prims that are render groom (not proxy/guide)."""
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.BasisCurves):
            continue
        purpose = UsdGeom.Imageable(prim).GetPurposeAttr().Get()
        if purpose in (UsdGeom.Tokens.proxy, UsdGeom.Tokens.guide):
            continue
        yield UsdGeom.BasisCurves(prim)


def curve_keep_every(target_reduction: float) -> int:
    """1 curve kept in N: 0.9 -> 10, 0.5 -> 2, 0 -> 1 (every curve)."""
    keep = max(1.0 - float(target_reduction), 1e-3)
    return max(1, int(round(1.0 / keep)))


def thin_curves(counts: np.ndarray, keep_every: int) -> tuple[np.ndarray, np.ndarray]:
    """(kept curve indices, source point -> proxy point mapping, -1 when dropped).

    Whole curves are kept (1 in keep_every, the first one always), so a thinned
    groom keeps its silhouette and its per-curve shape."""
    kept = np.arange(0, counts.shape[0], keep_every, dtype=np.int64)
    keep_curve = np.zeros(counts.shape[0], dtype=bool)
    keep_curve[kept] = True
    keep_point = np.repeat(keep_curve, counts)
    mapping = np.full(keep_point.shape[0], -1, dtype=np.int64)
    mapping[keep_point] = np.arange(int(keep_point.sum()), dtype=np.int64)
    return kept, mapping


def _author_curves_proxy(dst_stage: Usd.Stage, src: UsdGeom.BasisCurves,
                         keep_every: int) -> tuple[int, int]:
    """Author "<curves>_proxy" (purpose=proxy, 1 curve in keep_every) next to *src*,
    overriding *src* purpose=render. Returns (curves in, curves out), (0, 0) if empty."""
    points_attr = src.GetPointsAttr().Get()
    counts_attr = src.GetCurveVertexCountsAttr().Get()
    if not points_attr or not counts_attr:
        return 0, 0
    points = np.asarray(points_attr, dtype=np.float32)
    counts = np.asarray(counts_attr, dtype=np.int64)
    if int(counts.sum()) != points.shape[0]:
        return 0, 0                      # inconsistent curve: leave it alone
    kept, mapping = thin_curves(counts, keep_every)
    keep_point = mapping >= 0

    src_path = src.GetPath()
    UsdGeom.BasisCurves(dst_stage.OverridePrim(src_path)).CreatePurposeAttr(UsdGeom.Tokens.render)
    proxy = UsdGeom.BasisCurves.Define(dst_stage, src_path.GetParentPath().AppendChild(src_path.name + "_proxy"))
    proxy.CreatePurposeAttr(UsdGeom.Tokens.proxy)
    for getter, creator in ((src.GetTypeAttr, proxy.CreateTypeAttr),
                            (src.GetBasisAttr, proxy.CreateBasisAttr),
                            (src.GetWrapAttr, proxy.CreateWrapAttr)):
        attr = getter()
        if attr and attr.HasAuthoredValue():
            creator(attr.Get())
    proxy_points = points[keep_point]
    proxy.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(proxy_points))
    proxy.CreateCurveVertexCountsAttr(Vt.IntArray.FromNumpy(counts[kept].astype(np.int32)))
    widths = src.GetWidthsAttr().Get()
    if widths is not None and len(widths):
        w = np.asarray(widths, dtype=np.float32)
        interp = src.GetWidthsInterpolation()
        if interp in (UsdGeom.Tokens.vertex, UsdGeom.Tokens.varying) and w.shape[0] == points.shape[0]:
            w = w[keep_point]
        elif interp == UsdGeom.Tokens.uniform and w.shape[0] == counts.shape[0]:
            w = w[kept]
        elif interp != UsdGeom.Tokens.constant:
            w = None                     # unknown layout: the default width is fine for a proxy
        if w is not None:
            proxy.CreateWidthsAttr(Vt.FloatArray.FromNumpy(w))
            proxy.SetWidthsInterpolation(interp)
    proxy.CreateExtentAttr(_extent_of(proxy_points))
    _copy_skin_binding(src, proxy, mapping, proxy_points.shape[0])
    return int(counts.shape[0]), int(kept.shape[0])


def _extent_of(points: np.ndarray) -> Vt.Vec3fArray:
    """Axis-aligned bounds as USD extent (two Vec3f: min, max)."""
    lo = points.min(axis=0)
    hi = points.max(axis=0)
    return Vt.Vec3fArray([tuple(float(v) for v in lo), tuple(float(v) for v in hi)])


def _read_stored_hash(dst: Path) -> Optional[str]:
    """Return the source hash stored in an existing proxy layer, or None."""
    if not dst.exists():
        return None
    layer = Sdf.Layer.FindOrOpen(str(dst))
    if layer is None:
        return None
    data = layer.customLayerData or {}
    if data.get(_TOOL_KEY) != _TOOL_TAG:
        return None                      # built by an older proxy tool: rebuild
    value = data.get(_HASH_KEY)
    return value if isinstance(value, str) and value else None


def generate_proxy(
    src_usd: Path,
    dst_usd: Optional[Path] = None,
    target_reduction: float = DEFAULT_REDUCTION,
    min_tris: int = DEFAULT_MIN_TRIS,
    force: bool = False,
) -> ProxyResult:
    """Author purpose=proxy siblings for every render mesh (and groom) in a USD asset.

    The destination layer SUBLAYERS the source (so full render geometry is not
    duplicated), overrides each render mesh purpose=render, and adds a decimated
    "<name>_proxy" Mesh with purpose=proxy next to it. Skips if the source is
    unchanged since the last run. A render groom (BasisCurves) gets a thinned
    "<name>_proxy" sibling (1 curve kept in N, ADR 0026).
    """
    src_usd = Path(src_usd)
    dst = Path(dst_usd) if dst_usd else src_usd.with_suffix(".proxy.usda")

    src_hash = sha1_of_file(src_usd)
    if not force and _read_stored_hash(dst) == src_hash:
        return ProxyResult(src=src_usd, dst=dst, status="skipped")

    src_stage = Usd.Stage.Open(str(src_usd))
    if src_stage is None:
        return ProxyResult(src=src_usd, dst=dst, status="failed",
                           error=f"cannot open USD: {src_usd}")

    # Nothing to decimate (rig, look, anim layer): fail before touching the disk, an
    # empty proxy file would be picked by the asset instead of the publish.
    if next(_iter_render_meshes(src_stage), None) is None and             next(_iter_render_curves(src_stage), None) is None:
        return ProxyResult(src=src_usd, dst=dst, status="failed",
                           error="no render mesh found")

    # Fresh destination layer that composes the source as a sublayer.
    created = not dst.exists()
    dst_stage = Usd.Stage.CreateNew(str(dst)) if created else Usd.Stage.Open(str(dst))
    if dst_stage is None:
        dst_stage = Usd.Stage.CreateNew(str(dst))
    dst_layer = dst_stage.GetRootLayer()
    rel = os.path.relpath(str(src_usd), str(dst.parent)).replace("\\", "/")
    dst_layer.subLayerPaths = [rel]

    default_prim = src_stage.GetDefaultPrim()
    if default_prim and default_prim.IsValid():
        dst_stage.SetDefaultPrim(dst_stage.OverridePrim(default_prim.GetPath()))

    meshes = 0
    tris_in = 0
    tris_out = 0
    grooms = curves_in = curves_out = 0
    try:
        for mesh in _iter_render_meshes(src_stage):
            points_attr = mesh.GetPointsAttr().Get()
            counts_attr = mesh.GetFaceVertexCountsAttr().Get()
            indices_attr = mesh.GetFaceVertexIndicesAttr().Get()
            if not points_attr or not counts_attr or not indices_attr:
                continue

            points = np.asarray(points_attr, dtype=np.float32)
            counts = np.asarray(counts_attr, dtype=np.int64)
            indices = np.asarray(indices_attr, dtype=np.int64)
            tri_faces = triangulate(counts, indices)
            if tri_faces.shape[0] == 0:
                continue

            meshes += 1
            tris_in += tri_faces.shape[0]

            # Keep tiny meshes as-is; decimate the rest.
            if tri_faces.shape[0] <= min_tris:
                proxy_points, proxy_faces = points, tri_faces
                mapping = np.arange(points.shape[0], dtype=np.int64)
            else:
                proxy_points, proxy_faces, mapping = decimate_with_mapping(
                    points, tri_faces, target_reduction)
            tris_out += proxy_faces.shape[0]

            # The source mesh is render geometry.
            src_path = mesh.GetPath()
            render_over = UsdGeom.Mesh(dst_stage.OverridePrim(src_path))
            render_over.CreatePurposeAttr(UsdGeom.Tokens.render)

            # Author the decimated proxy: /<asset>/geo/proxy/<mesh> for the Solaris layout
            # (ADR 0019, meshes under geo/render), else a "<mesh>_proxy" sibling.
            parent = src_path.GetParentPath()
            if parent.name == "render" and parent.GetParentPath().name == "geo":
                proxy_scope = parent.GetParentPath().AppendChild("proxy")
                UsdGeom.Scope.Define(dst_stage, proxy_scope)
                proxy_path = proxy_scope.AppendChild(src_path.name)
            else:
                proxy_path = parent.AppendChild(src_path.name + "_proxy")
            proxy = UsdGeom.Mesh.Define(dst_stage, proxy_path)
            proxy.CreatePurposeAttr(UsdGeom.Tokens.proxy)
            # Triangles as decimated, never subdivided (USD's default is catmullClark).
            proxy.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
            proxy.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(proxy_points))
            proxy.CreateFaceVertexCountsAttr(
                Vt.IntArray.FromNumpy(np.full(proxy_faces.shape[0], 3, dtype=np.int32))
            )
            proxy.CreateFaceVertexIndicesAttr(
                Vt.IntArray.FromNumpy(proxy_faces.astype(np.int32).reshape(-1))
            )
            proxy.CreateExtentAttr(_extent_of(proxy_points))
            # Which render point each proxy point stands for: a RIG published later
            # gives the proxy the exact weights of those points (ADR 0034).
            UsdGeom.PrimvarsAPI(proxy.GetPrim()).CreatePrimvar(
                PROXY_SOURCE_PRIMVAR, Sdf.ValueTypeNames.IntArray, UsdGeom.Tokens.vertex,
            ).Set(Vt.IntArray.FromNumpy(
                source_representatives(mapping, proxy_points.shape[0]).astype(np.int32)))
            _copy_skin_binding(mesh, proxy, mapping, proxy_points.shape[0])

        keep_every = curve_keep_every(target_reduction)
        for curves in _iter_render_curves(src_stage):
            n_in, n_out = _author_curves_proxy(dst_stage, curves, keep_every)
            if n_in:
                grooms += 1
                curves_in += n_in
                curves_out += n_out
    except Exception as exc:  # noqa: BLE001 - report, do not crash the caller
        _drop_created(dst, created)
        return ProxyResult(src=src_usd, dst=dst, status="failed", error=str(exc))

    if meshes == 0 and grooms == 0:
        _drop_created(dst, created)
        return ProxyResult(src=src_usd, dst=dst, status="failed",
                           error="no render mesh found")

    dst_layer.customLayerData = {_HASH_KEY: src_hash, _TOOL_KEY: _TOOL_TAG}
    dst_stage.GetRootLayer().Save()
    return ProxyResult(
        src=src_usd, dst=dst, status="converted",
        meshes=meshes, tris_in=tris_in, tris_out=tris_out,
        grooms=grooms, curves_in=curves_in, curves_out=curves_out,
    )


def _drop_created(dst: Path, created: bool) -> None:
    """Remove a proxy file this run created but could not fill."""
    if not created:
        return
    layer = Sdf.Layer.Find(str(dst))
    if layer is not None:
        layer.Clear()
    try:
        dst.unlink()
    except OSError:
        pass


def _fmt_kb(n: int) -> str:
    return f"{n / 1024:.0f} KB"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate USD purpose=proxy geometry (pxr + fast-simplification)."
    )
    parser.add_argument("src", help="Source USD asset (readable by pxr).")
    parser.add_argument("-o", "--out", default=None,
                        help="Proxy layer path (default: <src>.proxy.usda).")
    parser.add_argument("-r", "--reduction", type=float, default=DEFAULT_REDUCTION,
                        help="Fraction of triangles removed (0-0.99, default 0.9).")
    parser.add_argument("--min-tris", type=int, default=DEFAULT_MIN_TRIS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    result = generate_proxy(
        Path(args.src),
        Path(args.out) if args.out else None,
        target_reduction=args.reduction,
        min_tris=args.min_tris,
        force=args.force,
    )
    if result.status == "failed":
        print(f"[FAIL] {result.src.name}: {result.error}")
        return 1
    if result.status == "skipped":
        print(f"[skip] {result.src.name} (unchanged)")
        return 0
    src_kb = result.src.stat().st_size
    dst_kb = result.dst.stat().st_size
    print(f"[ok]   {result.src.name} -> {result.dst.name}")
    print(f"       {result.meshes} mesh(es), {result.tris_in} -> {result.tris_out} tris "
          f"({100 * result.tris_out / max(result.tris_in, 1):.1f}% kept)")
    print(f"       proxy layer {_fmt_kb(dst_kb)} (source {_fmt_kb(src_kb)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
