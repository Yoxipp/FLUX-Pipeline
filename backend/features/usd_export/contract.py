# contract.py — plain data structures the DCC exporters fill and hand to the
# authoring core. Pure python, zero pxr (importable without USD installed).

from __future__ import annotations

from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]   # (x, y, z, w)
Mat4 = tuple[float, ...]                    # 16 floats, row-major


@dataclass
class MeshData:
    """A skinned mesh to author under the SkelRoot in the model layer."""

    name: str
    points: list[Vec3]
    face_vertex_counts: list[int]
    face_vertex_indices: list[int]
    # Skin binding (UsdSkelBindingAPI). joint_indices/weights are flattened,
    # influences_per_point values per point (constant elementSize).
    joint_indices: list[int] = field(default_factory=list)
    joint_weights: list[float] = field(default_factory=list)
    influences_per_point: int = 0
    geom_bind_transform: Mat4 | None = None   # identity when None
    # UV set, authored as an indexed faceVarying "st" primvar. uvs are the unique
    # (u, v) pairs; uv_indices is one index per face-vertex (parallel to
    # face_vertex_indices). Empty = no UVs authored.
    uvs: list[tuple[float, float]] = field(default_factory=list)
    uv_indices: list[int] = field(default_factory=list)
    # Full DCC path of the mesh ("|grp|body" in Maya), used only to tell apart two
    # meshes with the same leaf name (see mesh_prim_names). "" = unknown.
    path: str = ""


@dataclass
class SkeletonData:
    """UsdSkel skeleton topology and rest pose. All lists share joint order."""

    joints: list[str]                 # e.g. ["Root", "Root/Hip", "Root/Hip/Knee"]
    bind_transforms: list[Mat4]       # world-space bind pose, per joint
    rest_transforms: list[Mat4]       # local rest pose, per joint


@dataclass
class AnimData:
    """UsdSkelAnimation samples for the ANIMATED joints only (subset of skeleton).

    Per-time arrays are parallel to ``joints`` (one entry per animated joint).
    """

    joints: list[str]                 # animated subset, in skeleton order
    times: list[float]                # frame/time samples
    translations: list[list[Vec3]]    # [time][joint]
    rotations: list[list[Quat]]       # [time][joint]
    scales: list[list[Vec3]]          # [time][joint]
    fps: float | None = None          # scene frame rate (layer timeCodesPerSecond)


@dataclass
class CameraData:
    """A camera authored as a UsdGeom.Camera in the camera layer.

    focal_length / apertures are in millimetres (GfCamera convention); the backend
    passes them straight to UsdGeom.Camera.
    """

    name: str
    transform: Mat4                            # world matrix, row-major 16
    focal_length: float = 35.0                 # mm
    horizontal_aperture: float = 36.0          # mm
    vertical_aperture: float = 24.0            # mm
    clipping_range: tuple[float, float] = (0.1, 10000.0)
    projection: str = "perspective"            # "perspective" | "orthographic"
    fstop: float | None = None
    focus_distance: float | None = None


@dataclass
class LightData:
    """A light authored under UsdLux in the light layer."""

    name: str
    transform: Mat4                            # world matrix, row-major 16
    light_type: str = "distant"                # distant|point|spot|rect|disk|dome
    intensity: float = 1.0
    exposure: float = 0.0
    color: Vec3 = (1.0, 1.0, 1.0)
    normalize: bool = False
    radius: float | None = None                # point/disk/sphere
    width: float | None = None                 # rect
    height: float | None = None                # rect
    cone_angle: float | None = None            # spot (degrees)
    cone_softness: float | None = None         # spot


@dataclass
class LightAsset:
    """Full input to author_light_asset()."""

    asset: str                        # pipeline identity, e.g. "CHAR_hero"
    skeleton: SkeletonData
    meshes: list[MeshData] = field(default_factory=list)
    anim: AnimData | None = None      # None = rig only, no animation layer
    cameras: list[CameraData] = field(default_factory=list)
    lights: list[LightData] = field(default_factory=list)


# ── (de)serialisation — lets the DCC extract raw data (no pxr) and hand it to the
#    backend authoring core over JSON. Pure python. ──────────────────────────────

def light_asset_from_dict(d: dict) -> LightAsset:
    """Rebuild a LightAsset from a plain dict (e.g. json.load of an extractor's output)."""
    skel = d["skeleton"]
    skeleton = SkeletonData(
        joints=list(skel["joints"]),
        bind_transforms=[tuple(m) for m in skel["bind_transforms"]],
        rest_transforms=[tuple(m) for m in skel["rest_transforms"]],
    )
    meshes = [
        MeshData(
            name=m["name"],
            points=[tuple(p) for p in m["points"]],
            face_vertex_counts=list(m["face_vertex_counts"]),
            face_vertex_indices=list(m["face_vertex_indices"]),
            joint_indices=list(m.get("joint_indices", [])),
            joint_weights=list(m.get("joint_weights", [])),
            influences_per_point=int(m.get("influences_per_point", 0)),
            geom_bind_transform=(tuple(m["geom_bind_transform"])
                                 if m.get("geom_bind_transform") else None),
            uvs=[tuple(uv) for uv in m.get("uvs", [])],
            uv_indices=list(m.get("uv_indices", [])),
            path=str(m.get("path") or ""),
        )
        for m in d.get("meshes", [])
    ]
    anim = None
    a = d.get("anim")
    if a and a.get("joints"):
        anim = AnimData(
            joints=list(a["joints"]),
            times=[float(t) for t in a["times"]],
            translations=[[tuple(v) for v in row] for row in a["translations"]],
            rotations=[[tuple(q) for q in row] for row in a["rotations"]],
            scales=[[tuple(v) for v in row] for row in a["scales"]],
            fps=(float(a["fps"]) if a.get("fps") else None),
        )
    cameras = [
        CameraData(
            name=c["name"],
            transform=tuple(c["transform"]),
            focal_length=float(c.get("focal_length", 35.0)),
            horizontal_aperture=float(c.get("horizontal_aperture", 36.0)),
            vertical_aperture=float(c.get("vertical_aperture", 24.0)),
            clipping_range=tuple(c.get("clipping_range", (0.1, 10000.0))),  # type: ignore[arg-type]
            projection=str(c.get("projection", "perspective")),
            fstop=(float(c["fstop"]) if c.get("fstop") is not None else None),
            focus_distance=(float(c["focus_distance"]) if c.get("focus_distance") is not None else None),
        )
        for c in d.get("cameras", [])
    ]
    lights = [
        LightData(
            name=l["name"],
            transform=tuple(l["transform"]),
            light_type=str(l.get("light_type", "distant")),
            intensity=float(l.get("intensity", 1.0)),
            exposure=float(l.get("exposure", 0.0)),
            color=tuple(l.get("color", (1.0, 1.0, 1.0))),  # type: ignore[arg-type]
            normalize=bool(l.get("normalize", False)),
            radius=(float(l["radius"]) if l.get("radius") is not None else None),
            width=(float(l["width"]) if l.get("width") is not None else None),
            height=(float(l["height"]) if l.get("height") is not None else None),
            cone_angle=(float(l["cone_angle"]) if l.get("cone_angle") is not None else None),
            cone_softness=(float(l["cone_softness"]) if l.get("cone_softness") is not None else None),
        )
        for l in d.get("lights", [])
    ]
    return LightAsset(asset=d["asset"], skeleton=skeleton, meshes=meshes, anim=anim,
                      cameras=cameras, lights=lights)


def filter_animated_joints(
    joints: list[str],
    transforms_per_time: list[list[Mat4]],
    *,
    eps: float = 1e-6,
) -> list[str]:
    """Return the subset of *joints* whose local transform changes over time.

    *transforms_per_time* is shaped ``[time][joint]`` (parallel to *joints*).
    Fewer than two samples means nothing is animated (returns []). Pure python so
    the DCC extractor can use it without pxr.
    """
    if len(transforms_per_time) < 2:
        return []
    animated: list[str] = []
    for j, joint in enumerate(joints):
        first = transforms_per_time[0][j]
        moves = any(
            any(abs(a - b) > eps for a, b in zip(transforms_per_time[t][j], first))
            for t in range(1, len(transforms_per_time))
        )
        if moves:
            animated.append(joint)
    return animated


def _path_segments(path: str) -> list[str]:
    """DCC path -> segments without namespaces ("|ns:grp|body" / "/grp/body")."""
    return [seg.rsplit(":", 1)[-1] for seg in path.replace("|", "/").split("/") if seg]


def mesh_prim_names(items: list[tuple[str, str]], sanitize) -> list[str]:
    """Prim names under geo/render for meshes given as (leaf name, DCC path).

    Shared by the model layer and the look layer so a binding lands on the right mesh.
    A unique leaf name is kept as is. Meshes sharing a leaf name take the shortest
    unique tail of their path, joined by "_" ("|charA|body" -> "charA_body"). Without
    a usable path, "_2", "_3"... are appended in order (never overwrite a mesh).
    """
    leaves = [sanitize(name) for name, _ in items]
    out = list(leaves)
    groups: dict[str, list[int]] = {}
    for i, leaf in enumerate(leaves):
        groups.setdefault(leaf, []).append(i)
    taken = {leaf for leaf, idx in groups.items() if len(idx) == 1}
    for leaf, idx in groups.items():
        if len(idx) < 2:
            continue
        segs = {i: _path_segments(items[i][1]) for i in idx}
        depth = max((len(v) for v in segs.values()), default=0)
        chosen: dict[int, str] = {}
        for k in range(2, depth + 1):
            names = {i: sanitize("_".join(segs[i][-k:])) for i in idx if len(segs[i]) >= k}
            if len(names) == len(idx) and len(set(names.values())) == len(idx):
                chosen = names
                break
        n = 1
        for i in idx:
            name = chosen.get(i)
            if not name or name in taken:
                name = leaf if n == 1 else f"{leaf}_{n}"
                while name in taken:
                    n += 1
                    name = f"{leaf}_{n}"
                n += 1
            taken.add(name)
            out[i] = name
    return out
