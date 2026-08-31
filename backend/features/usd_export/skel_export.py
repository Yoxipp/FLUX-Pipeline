# skel_export.py — author the light layered UsdSkel asset from plain data.
#
# pxr is imported at module load; this module is only imported by the DCC exporters
# and its tests, never at sidecar boot (keeps the FastAPI process pxr-free).

from __future__ import annotations

from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel, Vt

from core.logger import get_logger

from ..usd_assembler.structure.naming import sanitize_token
from .contract import AnimData, LightAsset, Mat4, MeshData, SkeletonData, filter_animated_joints

__all__ = ["author_light_asset", "filter_animated_joints"]

log = get_logger("usd_export.skel")

_IDENTITY: Mat4 = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


# ── helpers ─────────────────────────────────────────────────────────────────────

def _mat(m: Mat4 | None) -> Gf.Matrix4d:
    return Gf.Matrix4d(*(m if m is not None else _IDENTITY))


def _new_stage(path: Path, fmt: str) -> Usd.Stage:
    # The `format` arg only accepts usda/usdc; a .usd extension is inferred (crate).
    args = {"format": fmt} if fmt in ("usda", "usdc") else {}
    layer = Sdf.Layer.CreateNew(str(path).replace("\\", "/"), args=args)
    return Usd.Stage.Open(layer)


# ── layer authoring ──────────────────────────────────────────────────────────────

def _author_model_layer(
    path: Path, root_path: str, skel_path: str, asset: str,
    meshes: list[MeshData], fmt: str,
) -> None:
    """Model layer: the SkelRoot + skinned meshes (the heavy geometry)."""
    stage = _new_stage(path, fmt)
    root = UsdSkel.Root.Define(stage, root_path)
    stage.SetDefaultPrim(root.GetPrim())

    for mesh in meshes:
        mpath = f"{root_path}/{sanitize_token(mesh.name)}"
        gmesh = UsdGeom.Mesh.Define(stage, mpath)
        gmesh.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(*p) for p in mesh.points]))
        gmesh.CreateFaceVertexCountsAttr(Vt.IntArray(mesh.face_vertex_counts))
        gmesh.CreateFaceVertexIndicesAttr(Vt.IntArray(mesh.face_vertex_indices))

        if mesh.uvs:
            st = UsdGeom.PrimvarsAPI(gmesh.GetPrim()).CreatePrimvar(
                "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
            )
            st.Set(Vt.Vec2fArray([Gf.Vec2f(u, v) for (u, v) in mesh.uvs]))
            if mesh.uv_indices:
                st.SetIndices(Vt.IntArray(mesh.uv_indices))

        if mesh.influences_per_point > 0:
            binding = UsdSkel.BindingAPI.Apply(gmesh.GetPrim())
            n = mesh.influences_per_point
            ji = binding.CreateJointIndicesPrimvar(False, n)
            ji.Set(Vt.IntArray(mesh.joint_indices))
            jw = binding.CreateJointWeightsPrimvar(False, n)
            jw.Set(Vt.FloatArray(mesh.joint_weights))
            binding.CreateGeomBindTransformAttr(_mat(mesh.geom_bind_transform))
            binding.CreateSkeletonRel().SetTargets([Sdf.Path(skel_path)])

    stage.GetRootLayer().Save()


def _author_skel_layer(
    path: Path, root_path: str, skel_path: str, skeleton: SkeletonData, fmt: str,
) -> None:
    """Skel layer: the Skeleton prim (topology + bind/rest pose)."""
    stage = _new_stage(path, fmt)
    stage.OverridePrim(root_path)   # SkelRoot type comes from the model layer
    skel = UsdSkel.Skeleton.Define(stage, skel_path)
    skel.CreateJointsAttr(Vt.TokenArray(skeleton.joints))
    skel.CreateBindTransformsAttr(Vt.Matrix4dArray([_mat(m) for m in skeleton.bind_transforms]))
    skel.CreateRestTransformsAttr(Vt.Matrix4dArray([_mat(m) for m in skeleton.rest_transforms]))
    stage.SetDefaultPrim(stage.GetPrimAtPath(root_path))
    stage.GetRootLayer().Save()


def _author_anim_layer(
    path: Path, root_path: str, skel_path: str, anim_path: str,
    anim: AnimData, fmt: str,
) -> None:
    """Anim layer: a UsdSkelAnimation carrying ONLY the animated joints."""
    stage = _new_stage(path, fmt)
    stage.OverridePrim(root_path)
    uanim = UsdSkel.Animation.Define(stage, anim_path)
    uanim.CreateJointsAttr(Vt.TokenArray(anim.joints))

    t_attr = uanim.CreateTranslationsAttr()
    r_attr = uanim.CreateRotationsAttr()
    s_attr = uanim.CreateScalesAttr()
    for i, t in enumerate(anim.times):
        t_attr.Set(Vt.Vec3fArray([Gf.Vec3f(*v) for v in anim.translations[i]]), t)
        # Gf.Quatf(real, i, j, k); contract stores (x, y, z, w)
        r_attr.Set(
            Vt.QuatfArray([Gf.Quatf(q[3], q[0], q[1], q[2]) for q in anim.rotations[i]]), t
        )
        s_attr.Set(Vt.Vec3hArray([Gf.Vec3h(*v) for v in anim.scales[i]]), t)

    # Bind skeleton + animation source on the SkelRoot so a consumer resolves skinning.
    root_binding = UsdSkel.BindingAPI.Apply(stage.GetPrimAtPath(root_path))
    root_binding.CreateSkeletonRel().SetTargets([Sdf.Path(skel_path)])
    root_binding.CreateAnimationSourceRel().SetTargets([Sdf.Path(anim_path)])
    stage.SetDefaultPrim(stage.GetPrimAtPath(root_path))
    stage.GetRootLayer().Save()


# ── public API ────────────────────────────────────────────────────────────────

def author_light_asset(
    asset: LightAsset,
    dest_dir: str | Path,
    *,
    fmt: str = "usda",
    version_label: str | None = None,
) -> dict[str, Path]:
    """Author the light layered asset into *dest_dir*.

    Writes ``{asset}_model``, ``{asset}_skel``, optional ``{asset}_anim`` and a root
    ``{asset}`` that sublayers them strong->weak (anim, skel, model). The root's
    defaultPrim is the asset token. When *version_label* is given it is appended to
    every file name (e.g. ``{asset}_model_v001``); the default (None) uses plain names,
    which suits a per-version output folder.
    Returns a dict of {"model","skel","anim"(optional),"root"} -> Path.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    token = sanitize_token(asset.asset)
    root_path = f"/{token}"
    skel_path = f"{root_path}/Skeleton"
    anim_path = f"{root_path}/Anim"

    _suffix_ver = f"_{version_label}" if version_label else ""

    def _fname(suffix: str) -> str:
        return f"{asset.asset}_{suffix}{_suffix_ver}.{fmt}"

    paths: dict[str, Path] = {}
    has_skel = bool(asset.skeleton and asset.skeleton.joints)

    model_p = dest / _fname("model")
    _author_model_layer(model_p, root_path, skel_path, token, asset.meshes, fmt)
    paths["model"] = model_p

    sublayers = [model_p.name]               # strong -> weak (model is weakest)
    if has_skel:
        skel_p = dest / _fname("skel")
        _author_skel_layer(skel_p, root_path, skel_path, asset.skeleton, fmt)
        paths["skel"] = skel_p
        sublayers.insert(0, skel_p.name)     # skel above model

    if has_skel and asset.anim is not None and asset.anim.joints:
        anim_p = dest / _fname("anim")
        _author_anim_layer(anim_p, root_path, skel_path, anim_path, asset.anim, fmt)
        paths["anim"] = anim_p
        sublayers.insert(0, anim_p.name)      # anim is strongest

    # Root file the resolver picks: defaultPrim + sublayer stack.
    root_p = dest / f"{asset.asset}{_suffix_ver}.{fmt}"
    root_stage = _new_stage(root_p, fmt)
    root_layer = root_stage.GetRootLayer()
    root_layer.subLayerPaths = sublayers
    root_layer.defaultPrim = token
    root_layer.Save()
    paths["root"] = root_p

    log.info("Authored light asset %s (%d meshes, anim=%s) -> %s",
             asset.asset, len(asset.meshes), asset.anim is not None, root_p.name)
    return paths
