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


_PRIMVAR_TYPES = {
    "color3f": Sdf.ValueTypeNames.Color3fArray,
    "float3": Sdf.ValueTypeNames.Float3Array,
    "float2": Sdf.ValueTypeNames.Float2Array,
    "float": Sdf.ValueTypeNames.FloatArray,
}


def _author_extra_primvars(prim: Usd.Prim, mesh: MeshData) -> None:
    """Color sets and other extra primvars, under the name the artist chose."""
    api = UsdGeom.PrimvarsAPI(prim)
    for pv in mesh.primvars:
        name = str(pv.get("name") or "").strip()
        vtype = _PRIMVAR_TYPES.get(str(pv.get("type") or "color3f"))
        values = pv.get("values") or []
        if not name or vtype is None or not values:
            continue
        primvar = api.CreatePrimvar(sanitize_token(name), vtype,
                                    str(pv.get("interpolation") or UsdGeom.Tokens.faceVarying))
        if vtype == Sdf.ValueTypeNames.FloatArray:
            primvar.Set(Vt.FloatArray([float(v) for v in values]))
        elif vtype == Sdf.ValueTypeNames.Float2Array:
            primvar.Set(Vt.Vec2fArray([Gf.Vec2f(*v) for v in values]))
        else:
            primvar.Set(Vt.Vec3fArray([Gf.Vec3f(*v) for v in values]))


def _author_binding(prim: Usd.Prim, mesh: MeshData, skel_path: str) -> None:
    """UsdSkel skin of one mesh. Houdini rebuilds boneCapture from exactly these
    primvars (USD Skin Import / UsdSkel Character Import SOP): never rename them."""
    binding = UsdSkel.BindingAPI.Apply(prim)
    n = mesh.influences_per_point
    binding.CreateJointIndicesPrimvar(False, n).Set(Vt.IntArray(mesh.joint_indices))
    binding.CreateJointWeightsPrimvar(False, n).Set(Vt.FloatArray(mesh.joint_weights))
    binding.CreateGeomBindTransformAttr(_mat(mesh.geom_bind_transform))
    binding.CreateSkeletonRel().SetTargets([Sdf.Path(skel_path)])


def _author_model_layer(
    path: Path, root_path: str, skel_path: str, asset: str,
    meshes: list[MeshData], fmt: str,
) -> None:
    """Model layer: the meshes under geo/render (the heavy geometry).

    The root is a SkelRoot only when a mesh carries a skin (legacy GEO publishes,
    Houdini); a pure model (ADR 0034) is an Xform and the RIG department turns it into
    the SkelRoot with its skeleton and weights."""
    stage = _new_stage(path, fmt)
    skinned = any(m.influences_per_point > 0 for m in meshes)
    root = (UsdSkel.Root.Define(stage, root_path) if skinned
            else UsdGeom.Xform.Define(stage, root_path))
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
        if mesh.subdivision_scheme:
            gmesh.CreateSubdivisionSchemeAttr(mesh.subdivision_scheme)
        if mesh.normals and len(mesh.normals) == len(mesh.face_vertex_indices):
            gmesh.CreateNormalsAttr(Vt.Vec3fArray([Gf.Vec3f(*n) for n in mesh.normals]))
            gmesh.SetNormalsInterpolation(UsdGeom.Tokens.faceVarying)

        if mesh.uvs:
            st = UsdGeom.PrimvarsAPI(gmesh.GetPrim()).CreatePrimvar(
                sanitize_token(mesh.uv_name or "st"), Sdf.ValueTypeNames.TexCoord2fArray,
                UsdGeom.Tokens.faceVarying,
            )
            st.Set(Vt.Vec2fArray([Gf.Vec2f(u, v) for (u, v) in mesh.uvs]))
            if mesh.uv_indices:
                st.SetIndices(Vt.IntArray(mesh.uv_indices))
        _author_extra_primvars(gmesh.GetPrim(), mesh)

        if mesh.influences_per_point > 0:
            _author_binding(gmesh.GetPrim(), mesh, skel_path)

    stage.GetRootLayer().Save()


def _author_skin_overs(
    stage: Usd.Stage, root_path: str, skel_path: str, meshes: list[MeshData],
    targets: list[str] | None, proxy_skins: list[dict] | None,
) -> None:
    """RIG department (ADR 0034): the skin as an "over" on the meshes the model
    department defines (/<NAME>/geo/render/<mesh>) and on their proxies, so the
    composed asset carries the weights on its geometry."""
    names = mesh_prim_names([(m.name, m.path) for m in meshes], sanitize_token)
    for i, mesh in enumerate(meshes):
        if mesh.influences_per_point <= 0:
            continue
        rel = (targets[i] if targets and i < len(targets) and targets[i]
               else f"{GEO_RENDER_SCOPE}/{names[i]}")
        prim = stage.OverridePrim(f"{root_path}/{rel}")
        _author_binding(prim, mesh, skel_path)
    for px in proxy_skins or []:
        prim = stage.OverridePrim(f"{root_path}/{px['path']}")
        binding = UsdSkel.BindingAPI.Apply(prim)
        n = int(px["size"])
        binding.CreateJointIndicesPrimvar(False, n).Set(Vt.IntArray(px["indices"]))
        binding.CreateJointWeightsPrimvar(False, n).Set(Vt.FloatArray(px["weights"]))
        binding.CreateGeomBindTransformAttr(_mat(px.get("bind")))
        binding.CreateSkeletonRel().SetTargets([Sdf.Path(skel_path)])


def _author_skel_layer(
    path: Path, root_path: str, skel_path: str, skeleton: SkeletonData, fmt: str,
    skin_meshes: list[MeshData] | None = None, skin_targets: list[str] | None = None,
    proxy_skins: list[dict] | None = None,
) -> None:
    """Skel layer: the SkelRoot + Skeleton prim (topology + bind/rest pose) and, for a
    RIG publish, the skin weights as overrides on the model's meshes."""
    stage = _new_stage(path, fmt)
    UsdSkel.Root.Define(stage, root_path)    # the model may be a plain Xform (ADR 0034)
    _define_scopes(stage, skel_path)
    skel = UsdSkel.Skeleton.Define(stage, skel_path)
    skel.CreateJointsAttr(Vt.TokenArray(skeleton.joints))
    skel.CreateBindTransformsAttr(Vt.Matrix4dArray([_mat(m) for m in skeleton.bind_transforms]))
    skel.CreateRestTransformsAttr(Vt.Matrix4dArray([_mat(m) for m in skeleton.rest_transforms]))
    if skin_meshes or proxy_skins:
        _author_skin_overs(stage, root_path, skel_path, skin_meshes or [], skin_targets, proxy_skins)
    stage.SetDefaultPrim(stage.GetPrimAtPath(root_path))
    stage.GetRootLayer().Save()


def _write_anim_samples(uanim: UsdSkel.Animation, anim: AnimData) -> None:
    """Translations / rotations / scales of the animated joints. A static channel is a
    default value (no samples); rotations are always sampled. The interpolation the
    artist chose is noted on the prim (held = step keys, already baked in the samples)."""
    t_attr = uanim.CreateTranslationsAttr()
    r_attr = uanim.CreateRotationsAttr()
    s_attr = uanim.CreateScalesAttr()

    def _t(row):
        return Vt.Vec3fArray([Gf.Vec3f(*v) for v in row])

    def _s(row):
        return Vt.Vec3hArray([Gf.Vec3h(*v) for v in row])

    if anim.translations_static and anim.translations:
        t_attr.Set(_t(anim.translations[0]))
    if anim.scales_static and anim.scales:
        s_attr.Set(_s(anim.scales[0]))
    for i, t in enumerate(anim.times):
        if not anim.translations_static:
            t_attr.Set(_t(anim.translations[i]), t)
        # Gf.Quatf(real, i, j, k); contract stores (x, y, z, w)
        r_attr.Set(Vt.QuatfArray([Gf.Quatf(q[3], q[0], q[1], q[2]) for q in anim.rotations[i]]), t)
        if not anim.scales_static:
            s_attr.Set(_s(anim.scales[i]), t)
    uanim.GetPrim().SetCustomDataByKey("flux:interpolation", anim.interpolation or "smooth")


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
    _write_anim_samples(uanim, anim)

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
        xform_op = UsdGeom.Xformable(ucam).AddTransformOp()
        if cam.times and cam.transforms:
            for t, m in zip(cam.times, cam.transforms):
                xform_op.Set(_mat(m), Usd.TimeCode(float(t)))
        else:
            xform_op.Set(_mat(cam.transform))
        if cam.times and cam.focal_lengths:
            focal = ucam.GetFocalLengthAttr()
            for t, f in zip(cam.times, cam.focal_lengths):
                focal.Set(float(f), Usd.TimeCode(float(t)))
    _set_sampled_range(stage.GetRootLayer(), cameras)
    stage.SetDefaultPrim(stage.GetPrimAtPath(root_path))
    stage.GetRootLayer().Save()


def _set_sampled_range(layer: Sdf.Layer, items) -> None:
    """Frame range + frame rate of animated cameras / lights (same rule as the anim layer)."""
    times = [t for it in items for t in (it.times or [])]
    fps = next((it.fps for it in items if it.fps), None)
    if times:
        layer.startTimeCode = float(min(times))
        layer.endTimeCode = float(max(times))
    if times and fps:
        layer.timeCodesPerSecond = float(fps)
        layer.framesPerSecond = float(fps)


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
        xform_op = UsdGeom.Xformable(ulight).AddTransformOp()
        if lt.times and lt.transforms:
            for t, m in zip(lt.times, lt.transforms):
                xform_op.Set(_mat(m), Usd.TimeCode(float(t)))
        else:
            xform_op.Set(_mat(lt.transform))
        if lt.times and lt.intensities:
            intensity = ulight.GetIntensityAttr()
            for t, i in zip(lt.times, lt.intensities):
                _try(intensity.Set, float(i), Usd.TimeCode(float(t)))
    _set_sampled_range(stage.GetRootLayer(), lights)
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
    _write_anim_samples(uanim, asset.anim)
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
    skin_targets: list[str] | None = None,
    proxy_skins: list[dict] | None = None,
) -> dict[str, Path]:
    """Author the light layered asset into *dest_dir*.

    Meshes flagged ``skin_only`` (RIG department, ADR 0034) are not geometry: their
    skin is authored in the skel layer as overrides on ``geo/render/<mesh>`` (or on
    *skin_targets*, root-relative prim paths parallel to them) plus *proxy_skins*
    ({"path", "indices", "weights", "size", "bind"}) on the model's proxies. A publish
    without geometry writes no model layer.

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

    geo_meshes = [m for m in asset.meshes if not m.skin_only]
    skin_meshes = [m for m in asset.meshes if m.skin_only]
    sublayers: list[str] = []                # strong -> weak (model is weakest)
    if geo_meshes or not (has_skel or asset.cameras or asset.lights):
        model_p = dest / _fname("model")
        _author_model_layer(model_p, root_path, skel_path, token, geo_meshes, fmt)
        paths["model"] = model_p
        sublayers.append(model_p.name)
    if has_skel:
        skel_p = dest / _fname("skel")
        _author_skel_layer(skel_p, root_path, skel_path, asset.skeleton, fmt,
                           skin_meshes=skin_meshes, skin_targets=skin_targets,
                           proxy_skins=proxy_skins)
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
    # Animated cameras / lights: the root carries their frame rate, so the sublayer's
    # time samples are not rescaled (timeCodesPerSecond mismatch) when composed.
    _set_sampled_range(root_layer, list(asset.cameras) + list(asset.lights))
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
