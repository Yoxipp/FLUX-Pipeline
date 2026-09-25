# skel_export.py — author the light layered UsdSkel asset from plain data.
#
# pxr is imported at module load; this module is only imported by the DCC exporters
# and its tests, never at sidecar boot (keeps the FastAPI process pxr-free).

from __future__ import annotations

import hashlib
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel, Vt

from core.logger import get_logger

from ..usd_assembler.structure.naming import sanitize_token
from .contract import (
    AnimData, LightAsset, Mat4, MeshData, SkeletonData, filter_animated_joints, mesh_prim_names,
)

__all__ = ["ANIM_SUBPATH", "GEO_RENDER_SCOPE", "SKELETON_SUBPATH", "author_light_asset",
           "author_motion_only", "filter_animated_joints"]

log = get_logger("usd_export.skel")

_IDENTITY: Mat4 = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)

# Prim layout inside the root (ADR 0019, SideFX Component Builder + UsdSkel):
#   /<NAME>                 SkelRoot
#   /<NAME>/geo/render/<m>  meshes          /<NAME>/geo/proxy  (usd_proxy)
#   /<NAME>/skel/Skeleton   /<NAME>/skel/Anim
GEO_RENDER_SCOPE = "geo/render"
SKELETON_SUBPATH = "skel/Skeleton"
ANIM_SUBPATH = "skel/Anim"


# ── helpers ─────────────────────────────────────────────────────────────────────

def _mat(m: Mat4 | None) -> Gf.Matrix4d:
    return Gf.Matrix4d(*(m if m is not None else _IDENTITY))


def _new_stage(path: Path, fmt: str) -> Usd.Stage:
    # The `format` arg only accepts usda/usdc; a .usd extension is inferred (crate).
    args = {"format": fmt} if fmt in ("usda", "usdc") else {}
    layer = Sdf.Layer.CreateNew(str(path).replace("\\", "/"), args=args)
    return Usd.Stage.Open(layer)


# ── layer authoring ──────────────────────────────────────────────────────────────

def _define_scopes(stage: Usd.Stage, path: str) -> None:
    """Scope prims for every missing ancestor between the root and *path* (Solaris layout)."""
    parts = [p for p in path.split("/") if p]
    for i in range(2, len(parts)):
        sub = "/" + "/".join(parts[:i])
        if not stage.GetPrimAtPath(sub):
            UsdGeom.Scope.Define(stage, sub)


def _author_model_layer(
    path: Path, root_path: str, skel_path: str, asset: str,
    meshes: list[MeshData], fmt: str,
) -> None:
    """Model layer: the SkelRoot + skinned meshes under geo/render (the heavy geometry)."""
    stage = _new_stage(path, fmt)
    root = UsdSkel.Root.Define(stage, root_path)
    stage.SetDefaultPrim(root.GetPrim())
    render_path = f"{root_path}/{GEO_RENDER_SCOPE}"
    _define_scopes(stage, f"{render_path}/x")

    prim_names = mesh_prim_names([(m.name, m.path) for m in meshes], sanitize_token)
    for mesh, prim_name in zip(meshes, prim_names):
        mpath = f"{render_path}/{prim_name}"
        gmesh = UsdGeom.Mesh.Define(stage, mpath)
        points = Vt.Vec3fArray([Gf.Vec3f(*p) for p in mesh.points])
        gmesh.CreatePointsAttr(points)
        # Rest bound: bbox caches, viewport culling and the component extentsHint read it.
        extent = UsdGeom.PointBased.ComputeExtent(points) if len(points) else None
        if extent is not None:
            gmesh.CreateExtentAttr(extent)
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
    _define_scopes(stage, skel_path)
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
    _define_scopes(stage, anim_path)
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


def _author_camera_layer(path: Path, root_path: str, cameras, fmt: str) -> None:
    """Camera layer: a UsdGeom.Camera per DCC camera (mm apertures)."""
    stage = _new_stage(path, fmt)
    stage.OverridePrim(root_path)
    for cam in cameras:
        cpath = f"{root_path}/{sanitize_token(cam.name)}"
        ucam = UsdGeom.Camera.Define(stage, cpath)
        ucam.CreateProjectionAttr(cam.projection)
        ucam.CreateFocalLengthAttr(float(cam.focal_length))
        ucam.CreateHorizontalApertureAttr(float(cam.horizontal_aperture))
        ucam.CreateVerticalApertureAttr(float(cam.vertical_aperture))
        ucam.CreateClippingRangeAttr(Gf.Vec2f(float(cam.clipping_range[0]), float(cam.clipping_range[1])))
        if cam.fstop is not None:
            ucam.CreateFStopAttr(float(cam.fstop))
        if cam.focus_distance is not None:
            ucam.CreateFocusDistanceAttr(float(cam.focus_distance))
        UsdGeom.Xformable(ucam).AddTransformOp().Set(_mat(cam.transform))
    stage.SetDefaultPrim(stage.GetPrimAtPath(root_path))
    stage.GetRootLayer().Save()


def _author_light_layer(path: Path, root_path: str, lights, fmt: str) -> None:
    """Light layer: a UsdLux light per DCC light. Each attr is guarded so UsdLux
    API differences across USD versions never break the whole export."""
    from pxr import UsdLux

    makers = {
        "distant": UsdLux.DistantLight,
        "point":   UsdLux.SphereLight,
        "spot":    UsdLux.SphereLight,
        "rect":    UsdLux.RectLight,
        "disk":    UsdLux.DiskLight,
        "dome":    UsdLux.DomeLight,
    }

    def _try(fn, *a):
        try:
            fn(*a)
        except Exception as exc:  # pragma: no cover - version guard
            log.warning("light attr skipped: %s", exc)

    stage = _new_stage(path, fmt)
    stage.OverridePrim(root_path)
    for lt in lights:
        maker = makers.get(lt.light_type, UsdLux.DistantLight)
        lpath = f"{root_path}/{sanitize_token(lt.name)}"
        ulight = maker.Define(stage, lpath)
        _try(ulight.CreateIntensityAttr, float(lt.intensity))
        _try(ulight.CreateExposureAttr, float(lt.exposure))
        _try(ulight.CreateColorAttr, Gf.Vec3f(*lt.color))
        _try(ulight.CreateNormalizeAttr, bool(lt.normalize))
        if lt.radius is not None and hasattr(ulight, "CreateRadiusAttr"):
            _try(ulight.CreateRadiusAttr, float(lt.radius))
        if lt.width is not None and hasattr(ulight, "CreateWidthAttr"):
            _try(ulight.CreateWidthAttr, float(lt.width))
        if lt.height is not None and hasattr(ulight, "CreateHeightAttr"):
            _try(ulight.CreateHeightAttr, float(lt.height))
        if lt.cone_angle is not None:
            try:
                shaping = UsdLux.ShapingAPI.Apply(ulight.GetPrim())
                shaping.CreateShapingConeAngleAttr(float(lt.cone_angle))
                if lt.cone_softness is not None:
                    shaping.CreateShapingConeSoftnessAttr(float(lt.cone_softness))
            except Exception as exc:  # pragma: no cover - version guard
                log.warning("spot shaping skipped: %s", exc)
        UsdGeom.Xformable(ulight).AddTransformOp().Set(_mat(lt.transform))
    stage.SetDefaultPrim(stage.GetPrimAtPath(root_path))
    stage.GetRootLayer().Save()


def _set_time_range(layer: Sdf.Layer, anim: AnimData) -> None:
    """Frame range + frame rate, so a DCC timeline knows how long the motion lasts."""
    if anim.times:
        layer.startTimeCode = float(min(anim.times))
        layer.endTimeCode = float(max(anim.times))
    if anim.fps:
        layer.timeCodesPerSecond = float(anim.fps)
        layer.framesPerSecond = float(anim.fps)


def author_motion_only(asset: LightAsset, dest_dir: str | Path, *, fmt: str = "usda",
                       root_name: str | None = None) -> dict[str, Path]:
    """Motion only (2026-09-18): ``{asset}_anim`` holds the moving joints of the
    skeleton animation under ``/<root>/skel/Anim`` and binds it as the animation source
    of ``/<root>``; no skeleton, no geometry (they come from the asset's rig and model).
    Referenced onto an asset prim, it animates that asset. The root ``{asset}`` file
    sublayers it and carries the same frame range. Returns {"anim", "root"} -> Path.
    """
    if asset.anim is None or not asset.anim.joints:
        raise ValueError("aucune anim : rien ne bouge sur la plage demandee")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    token = sanitize_token(root_name or asset.asset)
    root_path = f"/{token}"
    anim_path = f"{root_path}/{ANIM_SUBPATH}"

    anim_p = dest / f"{asset.asset}_anim.{fmt}"
    stage = _new_stage(anim_p, fmt)
    stage.OverridePrim(root_path)
    _define_scopes(stage, anim_path)
    uanim = UsdSkel.Animation.Define(stage, anim_path)
    uanim.CreateJointsAttr(Vt.TokenArray(asset.anim.joints))
    t_attr = uanim.CreateTranslationsAttr()
    r_attr = uanim.CreateRotationsAttr()
    s_attr = uanim.CreateScalesAttr()
    for i, t in enumerate(asset.anim.times):
        t_attr.Set(Vt.Vec3fArray([Gf.Vec3f(*v) for v in asset.anim.translations[i]]), t)
        r_attr.Set(Vt.QuatfArray([Gf.Quatf(q[3], q[0], q[1], q[2])
                                  for q in asset.anim.rotations[i]]), t)
        s_attr.Set(Vt.Vec3hArray([Gf.Vec3h(*v) for v in asset.anim.scales[i]]), t)
    binding = UsdSkel.BindingAPI.Apply(stage.GetPrimAtPath(root_path))
    binding.CreateAnimationSourceRel().SetTargets([Sdf.Path(anim_path)])
    # Defining skel/Anim also defined its ancestors: the root stays an "over", the
    # asset it is referenced onto owns it.
    stage.GetRootLayer().GetPrimAtPath(root_path).specifier = Sdf.SpecifierOver
    stage.SetDefaultPrim(stage.GetPrimAtPath(root_path))
    _set_time_range(stage.GetRootLayer(), asset.anim)
    stage.GetRootLayer().Save()

    root_p = dest / f"{asset.asset}.{fmt}"
    root_layer = _new_stage(root_p, fmt).GetRootLayer()
    root_layer.subLayerPaths = [anim_p.name]
    root_layer.defaultPrim = token
    _set_time_range(root_layer, asset.anim)
    root_layer.Save()
    log.info("Authored motion-only anim %s (%d joints, %d frames) -> %s",
             asset.asset, len(asset.anim.joints), len(asset.anim.times), root_p.name)
    return {"anim": anim_p, "root": root_p}


def skeleton_signature(joints: list[str]) -> str:
    """12 hex chars of the ordered joint paths ("" without joints): same signature =
    same rig, whatever the geometry (crowd A6, ADR 0022)."""
    if not joints:
        return ""
    return hashlib.sha1("\n".join(str(j) for j in joints).encode("utf-8")).hexdigest()[:12]


# ── public API ────────────────────────────────────────────────────────────────

def author_light_asset(
    asset: LightAsset,
    dest_dir: str | Path,
    *,
    fmt: str = "usda",
    version_label: str | None = None,
    root_name: str | None = None,
) -> dict[str, Path]:
    """Author the light layered asset into *dest_dir*.

    Writes ``{asset}_model``, ``{asset}_skel``, optional ``{asset}_anim`` and a root
    ``{asset}`` that sublayers them strong->weak (anim, skel, model). The prim root
    (and defaultPrim) is *root_name* (the NAME token, ADR 0019), else the asset token;
    file names always use ``asset.asset``. When *version_label* is given it is appended to
    every file name (e.g. ``{asset}_model_v001``); the default (None) uses plain names,
    which suits a per-version output folder.
    Returns a dict of {"model","skel","anim"(optional),"root"} -> Path.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    token = sanitize_token(root_name or asset.asset)
    root_path = f"/{token}"
    skel_path = f"{root_path}/{SKELETON_SUBPATH}"
    anim_path = f"{root_path}/{ANIM_SUBPATH}"

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

    # Camera / light layers (disjoint prims under the root — order not critical).
    if asset.cameras:
        cam_p = dest / _fname("cam")
        _author_camera_layer(cam_p, root_path, asset.cameras, fmt)
        paths["cam"] = cam_p
        sublayers.append(cam_p.name)
    if asset.lights:
        light_p = dest / _fname("light")
        _author_light_layer(light_p, root_path, asset.lights, fmt)
        paths["light"] = light_p
        sublayers.append(light_p.name)

    # Root file the resolver picks: defaultPrim + sublayer stack.
    root_p = dest / f"{asset.asset}{_suffix_ver}.{fmt}"
    root_stage = _new_stage(root_p, fmt)
    root_layer = root_stage.GetRootLayer()
    root_layer.subLayerPaths = sublayers
    root_layer.defaultPrim = token
    if has_skel:
        # Crowd (A6, ADR 0022): assets with the same signature share a rig.
        root_layer.customLayerData = {"flux": {
            "skeleton_signature": skeleton_signature(asset.skeleton.joints),
            "joint_count": len(asset.skeleton.joints)}}
    root_layer.Save()
    paths["root"] = root_p

    log.info("Authored light asset %s (%d meshes, anim=%s) -> %s",
             asset.asset, len(asset.meshes), asset.anim is not None, root_p.name)
    return paths
