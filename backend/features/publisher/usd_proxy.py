# usd_proxy.py - generate lightweight USD proxy geometry (purpose=proxy).
#
# Goal: give every render mesh a decimated sibling tagged purpose=proxy, so
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

from __future__ import annotations

import argparse
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from pxr import Sdf, Usd, UsdGeom, Vt

log = logging.getLogger(__name__)

# Below this triangle count a mesh is already cheap: decimating it is not worth
# the quality loss, so we copy it into the proxy unchanged.
DEFAULT_MIN_TRIS = 200
# Fraction of triangles removed by default (0.9 -> keep ~10%).
DEFAULT_REDUCTION = 0.9
# customLayerData key that carries the source hash for skip-if-unchanged.
_HASH_KEY = "flux_proxy_src_sha1"
_TOOL_KEY = "flux_proxy_tool"
_TOOL_TAG = "flux-usd-proxy"


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
    import fast_simplification as fs

    if tri_faces.shape[0] == 0:
        return points, tri_faces
    reduction = min(max(target_reduction, 0.0), 0.99)
    if reduction <= 0.0:
        return points, tri_faces
    new_points, new_faces = fs.simplify(
        points.astype(np.float32), tri_faces.astype(np.int64), target_reduction=reduction
    )
    return np.asarray(new_points, dtype=np.float32), np.asarray(new_faces, dtype=np.int64)


def _iter_render_meshes(stage: Usd.Stage):
    """Yield UsdGeom.Mesh prims that are render geometry (not proxy/guide)."""
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        purpose = UsdGeom.Imageable(prim).GetPurposeAttr().Get()
        if purpose in (UsdGeom.Tokens.proxy, UsdGeom.Tokens.guide):
            continue
        yield UsdGeom.Mesh(prim)


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
    value = data.get(_HASH_KEY)
    return value if isinstance(value, str) and value else None


def generate_proxy(
    src_usd: Path,
    dst_usd: Optional[Path] = None,
    target_reduction: float = DEFAULT_REDUCTION,
    min_tris: int = DEFAULT_MIN_TRIS,
    force: bool = False,
) -> ProxyResult:
    """Author purpose=proxy siblings for every render mesh in a USD asset.

    The destination layer SUBLAYERS the source (so full render geometry is not
    duplicated), overrides each render mesh purpose=render, and adds a decimated
    "<name>_proxy" Mesh with purpose=proxy next to it. Skips if the source is
    unchanged since the last run.
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
    if next(_iter_render_meshes(src_stage), None) is None:
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
            else:
                proxy_points, proxy_faces = decimate(points, tri_faces, target_reduction)
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
            proxy.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(proxy_points))
            proxy.CreateFaceVertexCountsAttr(
                Vt.IntArray.FromNumpy(np.full(proxy_faces.shape[0], 3, dtype=np.int32))
            )
            proxy.CreateFaceVertexIndicesAttr(
                Vt.IntArray.FromNumpy(proxy_faces.astype(np.int32).reshape(-1))
            )
            proxy.CreateExtentAttr(_extent_of(proxy_points))
    except Exception as exc:  # noqa: BLE001 - report, do not crash the caller
        _drop_created(dst, created)
        return ProxyResult(src=src_usd, dst=dst, status="failed", error=str(exc))

    if meshes == 0:
        _drop_created(dst, created)
        return ProxyResult(src=src_usd, dst=dst, status="failed",
                           error="no render mesh found")

    dst_layer.customLayerData = {_HASH_KEY: src_hash, _TOOL_KEY: _TOOL_TAG}
    dst_stage.GetRootLayer().Save()
    return ProxyResult(
        src=src_usd, dst=dst, status="converted",
        meshes=meshes, tris_in=tris_in, tris_out=tris_out,
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
