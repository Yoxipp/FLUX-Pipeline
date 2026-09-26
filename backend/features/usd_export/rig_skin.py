# rig_skin.py — where the RIG department puts its skin weights (ADR 0034).
#
# The RIG publish carries the skeleton and the skin weights, authored as overrides on
# the meshes the model department defines (/<NAME>/geo/render/<mesh>) and on their
# purpose=proxy siblings (/<NAME>/geo/proxy/<mesh>), so the composed asset has its
# weights on its geometry (Houdini rebuilds boneCapture from them) and the proxy
# deforms in the viewport. This module reads the asset as published to find those
# prims. pxr + numpy, backend only. Never raises: a missing model only warns.

from __future__ import annotations

from pathlib import Path

import numpy as np

from core.logger import get_logger
from features.publisher.usd_proxy import PROXY_SOURCE_PRIMVAR

from ..usd_assembler.structure.naming import sanitize_token
from .contract import MeshData, mesh_prim_names
from .skel_export import GEO_RENDER_SCOPE

log = get_logger("usd_export.rig_skin")

_PROXY_SCOPE = "geo/proxy"
# Nearest-point search runs in chunks so a heavy mesh never allocates N x M at once
# (at most ~_NN_BUDGET distances per chunk, ~160 MB of float64).
_NN_BUDGET = 20_000_000


def nearest_points(src: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Index in *src* of the closest point to each point of *query* (brute force,
    chunked; numpy only, no scipy)."""
    out = np.empty(len(query), dtype=np.int64)
    src = np.asarray(src, dtype=np.float64)
    sq = np.einsum("ij,ij->i", src, src)
    chunk = max(1, _NN_BUDGET // max(len(src), 1))
    for start in range(0, len(query), chunk):
        q = np.asarray(query[start:start + chunk], dtype=np.float64)
        d = sq[None, :] - 2.0 * q @ src.T
        out[start:start + len(q)] = np.argmin(d, axis=1)
    return out


def _asset_geometry(entry: Path, name: str) -> tuple[dict, dict]:
    """({render prim name: (root-relative path, point count)},
    {proxy prim name: (root-relative path, points, source indices or None)})."""
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(str(entry))
    render: dict = {}
    proxies: dict = {}
    if stage is None:
        return render, proxies
    root = stage.GetDefaultPrim() or stage.GetPrimAtPath(f"/{sanitize_token(name)}")
    if not root or not root.IsValid():
        return render, proxies
    root_path = str(root.GetPath())
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        rel = str(prim.GetPath())[len(root_path) + 1:]
        mesh = UsdGeom.Mesh(prim)
        pts = mesh.GetPointsAttr().Get()
        purpose = UsdGeom.Imageable(prim).GetPurposeAttr().Get()
        if purpose == UsdGeom.Tokens.proxy or rel.startswith(_PROXY_SCOPE + "/"):
            src = UsdGeom.PrimvarsAPI(prim).GetPrimvar(PROXY_SOURCE_PRIMVAR)
            src_idx = np.asarray(src.Get(), dtype=np.int64) if src and src.HasValue() else None
            proxies[prim.GetName()] = (rel, np.asarray(pts or [], dtype=np.float64), src_idx)
        else:
            render[prim.GetName()] = (rel, len(pts or []))
    return render, proxies


def _match(render: dict, want: str, leaf: str, n_points: int) -> str | None:
    """Name of the model mesh the rig mesh *want* (leaf *leaf*) lands on."""
    if want in render:
        return want
    cands = [k for k in render if k == leaf or k.endswith("_" + leaf)]
    same = [k for k in cands if render[k][1] == n_points]
    if len(same) == 1:
        return same[0]
    return cands[0] if len(cands) == 1 else None


def skin_targets(project_path, name: str | None,
                 meshes: list[MeshData]) -> tuple[list[str], list[dict], list[str]]:
    """(targets, proxy_skins, warnings) for the skin-only meshes of a RIG publish.

    *targets* are root-relative prim paths parallel to *meshes* ("" = default
    geo/render/<mesh>); *proxy_skins* feed skel_export's proxy overrides.
    """
    warnings: list[str] = []
    names = mesh_prim_names([(m.name, m.path) for m in meshes], sanitize_token)
    targets = [f"{GEO_RENDER_SCOPE}/{n}" for n in names]
    if not meshes:
        return targets, [], warnings
    entry = None
    try:
        from features.usd_assembler.component_auto import component_dir

        folder = component_dir(project_path, name) if name else None
        cand = folder / f"{name}_LAST.usda" if folder is not None else None
        entry = cand if cand is not None and cand.is_file() else None
    except Exception as exc:        # noqa: BLE001 - a check never blocks a publish
        log.debug("rig skin: no component for %s: %s", name, exc)
    if entry is None:
        warnings.append(f"asset {name or '?'} sans GEO publie : les poids visent "
                        "geo/render/<mesh> sans verification (publie le GEO avant le RIG)")
        return targets, [], warnings
    try:
        render, proxies = _asset_geometry(entry, name or "")
    except Exception as exc:        # noqa: BLE001
        warnings.append(f"geometrie de {name} illisible, poids non verifies : {exc}")
        return targets, [], warnings

    proxy_skins: list[dict] = []
    for i, mesh in enumerate(meshes):
        leaf = sanitize_token(mesh.name)
        hit = _match(render, names[i], leaf, len(mesh.points))
        if hit is None:
            warnings.append(f"{mesh.name} : aucun mesh du GEO publie ne correspond, poids poses "
                            f"sur {targets[i]}")
            continue
        targets[i] = render[hit][0]
        if render[hit][1] != len(mesh.points):
            warnings.append(f"{mesh.name} : {len(mesh.points)} points dans le rig, "
                            f"{render[hit][1]} dans le GEO publie (topologie differente ?)")
            continue
        px = proxies.get(hit)
        if px is None or mesh.influences_per_point <= 0:
            continue
        rel, px_points, src_idx = px
        size = mesh.influences_per_point
        if src_idx is None or len(src_idx) != len(px_points) or (
                len(src_idx) and src_idx.max() >= len(mesh.points)):
            if not len(px_points) or not mesh.points:
                continue
            src_idx = nearest_points(np.asarray(mesh.points), px_points)
        ji = np.asarray(mesh.joint_indices, dtype=np.int64).reshape(-1, size)[src_idx]
        jw = np.asarray(mesh.joint_weights, dtype=np.float64).reshape(-1, size)[src_idx]
        proxy_skins.append({"path": rel, "indices": [int(v) for v in ji.reshape(-1)],
                            "weights": [float(v) for v in jw.reshape(-1)], "size": size,
                            "bind": mesh.geom_bind_transform})
    return targets, proxy_skins, warnings
