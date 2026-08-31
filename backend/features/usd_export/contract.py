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


@dataclass
class LightAsset:
    """Full input to author_light_asset()."""

    asset: str                        # pipeline identity, e.g. "CHAR_hero"
    skeleton: SkeletonData
    meshes: list[MeshData] = field(default_factory=list)
    anim: AnimData | None = None      # None = rig only, no animation layer


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
        )
    return LightAsset(asset=d["asset"], skeleton=skeleton, meshes=meshes, anim=anim)


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
