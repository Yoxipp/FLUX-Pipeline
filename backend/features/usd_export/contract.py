# contract.py — plain data structures the DCC exporters fill and hand to the
# authoring core. Pure python, zero pxr (importable without USD installed).

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field, replace

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
    # Name of the UV primvar ("st" = USD convention, read by UsdPreviewSurface; "uv"
    # for a Houdini-only pipe). Attribute renamer of the Publisher (2026-09-26).
    uv_name: str = "st"
    # faceVarying normals, one per face-vertex (hard edges survive). Empty = none.
    normals: list[Vec3] = field(default_factory=list)
    # UsdGeom subdivisionScheme: "" = not authored (legacy, USD default catmullClark),
    # "none" = polygons as modelled (hard edges and normals honoured).
    subdivision_scheme: str = ""
    # Extra primvars (Maya color sets...): {"name", "type": "color3f"|"float3"|"float",
    # "interpolation": "faceVarying"|"vertex"|..., "values": [...]}.
    primvars: list[dict] = field(default_factory=list)
    # RIG department (ADR 0034): only the skin binding is authored, as an "over" on the
    # mesh the model department defines. points / topology stay for matching only.
    skin_only: bool = False


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
    # A static channel is authored as a default value (no time samples): the rows
    # list then holds ONE row. Rotations are always sampled (ANIM, 2026-09-26).
    translations_static: bool = False
    scales_static: bool = False
    # "smooth" (the DCC curves, baked) or "held" (step: each key holds until the next).
    interpolation: str = "smooth"


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
            uv_name=str(m.get("uv_name") or "st"),
            normals=[tuple(n) for n in m.get("normals", [])],
            subdivision_scheme=str(m.get("subdivision_scheme") or ""),
            primvars=[dict(pv) for pv in m.get("primvars", [])],
            skin_only=bool(m.get("skin_only", False)),
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
            translations_static=bool(a.get("translations_static", False)),
            scales_static=bool(a.get("scales_static", False)),
            interpolation=str(a.get("interpolation") or "smooth"),
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


# ── ANIM department helpers (2026-09-26). Pure python: Maya runs them. ────────

def _quat_dot(a: Quat, b: Quat) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]


def quat_angle(a: Quat, b: Quat) -> float:
    """Angle (radians) of the rotation between two unit quaternions (q and -q equal)."""
    d = min(1.0, abs(_quat_dot(a, b)))
    return 2.0 * math.acos(d)


def quat_slerp(a: Quat, b: Quat, t: float) -> Quat:
    """Spherical interpolation, shortest path: what a USD consumer does between two
    quaternion time samples (Gf.Slerp)."""
    d = _quat_dot(a, b)
    if d < 0.0:
        b = (-b[0], -b[1], -b[2], -b[3])
        d = -d
    if d > 0.9995:                       # nearly equal: lerp + normalise
        out = tuple(a[i] + (b[i] - a[i]) * t for i in range(4))
    else:
        theta = math.acos(d)
        s = math.sin(theta)
        wa, wb = math.sin((1.0 - t) * theta) / s, math.sin(t * theta) / s
        out = tuple(a[i] * wa + b[i] * wb for i in range(4))
    n = math.sqrt(sum(c * c for c in out)) or 1.0
    return tuple(c / n for c in out)     # type: ignore[return-value]


def _lerp3(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _close3(a: Vec3, b: Vec3, eps: float) -> bool:
    return abs(a[0] - b[0]) <= eps and abs(a[1] - b[1]) <= eps and abs(a[2] - b[2]) <= eps


def rotation_moves(rows: list[Quat], eps: float = 1e-5) -> bool:
    """True when one joint's rotation changes over the samples."""
    return any(quat_angle(rows[0], q) > eps for q in rows[1:])


def vector_moves(rows: list[Vec3], eps: float = 1e-5) -> bool:
    return any(not _close3(rows[0], v, eps) for v in rows[1:])


def translation_roots(tokens: list[str], moving: list[str]) -> list[str]:
    """The joints whose translation carries the character (root motion), whatever the
    rig calls them (Root, COG, Sk_Cog...): among the joints whose translation moves,
    the ones highest in the hierarchy (smallest depth). [] when nothing translates."""
    moving_set = set(moving)
    depths = {t: t.count("/") for t in tokens if t in moving_set}
    if not depths:
        return []
    top = min(depths.values())
    return [t for t in tokens if depths.get(t) == top]


def hold_keys(anim: "AnimData", key_times: list[float]) -> "AnimData":
    """Step ("held") version of *anim*: every sample takes the pose of the last key at
    or before it, so the pose holds until the next key (blocking)."""
    keys = sorted({float(k) for k in key_times})
    if not keys or not anim.times:
        return replace(anim, interpolation="held")
    order = sorted(range(len(anim.times)), key=lambda i: anim.times[i])
    sorted_times = [anim.times[i] for i in order]

    def _held(i: int) -> int:
        t = anim.times[i]
        k = bisect.bisect_right(keys, t + 1e-6) - 1           # last key at or before t
        if k < 0:
            return i
        # Nearest sampled time at or before that key (keys may sit on sub-frames).
        s = bisect.bisect_right(sorted_times, keys[k] + 1e-6) - 1
        return order[s] if s >= 0 else i

    pick = [_held(i) for i in range(len(anim.times))]
    trans = anim.translations if anim.translations_static else [anim.translations[j] for j in pick]
    scales = anim.scales if anim.scales_static else [anim.scales[j] for j in pick]
    return replace(anim, rotations=[anim.rotations[j] for j in pick], translations=trans,
                   scales=scales, interpolation="held")


def reduce_samples(anim: "AnimData", *, eps_angle: float = 1e-4, eps_lin: float = 1e-5) -> "AnimData":
    """Drop the time samples a consumer rebuilds EXACTLY by interpolating the kept
    neighbours (linear for vectors, slerp for quaternions), never the others: the
    motion at every source frame is unchanged, a hold stays a hold (its last frame is
    kept) and a smooth curve keeps every sample that is not on a straight line.
    Every joint of a sample is checked together (one USD array per time)."""
    n = len(anim.times)
    if n <= 2:
        return anim
    t_rows = None if anim.translations_static else anim.translations
    s_rows = None if anim.scales_static else anim.scales

    def _ok(a: int, b: int, m: int) -> bool:
        """Sample m rebuilt from a and b."""
        ta, tb, tm = anim.times[a], anim.times[b], anim.times[m]
        u = (tm - ta) / (tb - ta) if tb != ta else 0.0
        for qa, qb, qm in zip(anim.rotations[a], anim.rotations[b], anim.rotations[m]):
            if quat_angle(quat_slerp(qa, qb, u), qm) > eps_angle:
                return False
        for rows in (t_rows, s_rows):
            if rows is None:
                continue
            for va, vb, vm in zip(rows[a], rows[b], rows[m]):
                if not _close3(_lerp3(va, vb, u), vm, eps_lin):
                    return False
        return True

    keep = [0]
    a = 0
    while a < n - 1:
        b = a + 1
        # Extend the segment as long as every sample inside it is rebuilt exactly.
        while b + 1 < n and all(_ok(a, b + 1, m) for m in range(a + 1, b + 1)):
            b += 1
        keep.append(b)
        a = b
    if len(keep) == n:
        return anim
    pick = keep
    return replace(
        anim,
        times=[anim.times[i] for i in pick],
        rotations=[anim.rotations[i] for i in pick],
        translations=anim.translations if anim.translations_static else [anim.translations[i] for i in pick],
        scales=anim.scales if anim.scales_static else [anim.scales[i] for i in pick],
    )


# ── RIG department helper: compact skin weights (ADR 0034). Pure python. ──────────

def compact_weights(
    influence_joints: list[int],
    weights_flat: list[float],
    num_points: int,
    *,
    max_influences: int = 0,
    threshold: float = 1e-4,
) -> tuple[list[int], list[float], int]:
    """Dense DCC weights (one value per influence per point, vertex-major) ->
    UsdSkel arrays keeping only the influences that matter.

    *influence_joints* maps each DCC influence to its skeleton joint index (-1 = not in
    the skeleton, its weight is dropped). Per point,
    weights under *threshold* are dropped, the strongest *max_influences* kept (0 = all
    non-zero) and the rest renormalised to sum 1. Every point gets the same element
    size (UsdSkel constant elementSize), padded with joint 0 / weight 0.
    Returns (joint_indices, joint_weights, element_size).
    """
    n_inf = len(influence_joints)
    if n_inf == 0 or num_points == 0:
        return [], [], 0
    rows: list[list[tuple[int, float]]] = []
    size = 1
    for p in range(num_points):
        base = p * n_inf
        pairs = [(influence_joints[i], float(weights_flat[base + i]))
                 for i in range(n_inf)
                 if influence_joints[i] >= 0 and float(weights_flat[base + i]) > threshold]
        # Two DCC influences on one joint (duplicate mapping): merge them.
        merged: dict[int, float] = {}
        for j, w in pairs:
            merged[j] = merged.get(j, 0.0) + w
        pairs = sorted(merged.items(), key=lambda jw: -jw[1])
        if max_influences > 0:
            pairs = pairs[:max_influences]
        total = sum(w for _, w in pairs)
        if total > 0:
            pairs = [(j, w / total) for j, w in pairs]
        rows.append(pairs)
        size = max(size, len(pairs))
    indices: list[int] = []
    weights: list[float] = []
    for pairs in rows:
        pad = size - len(pairs)
        indices.extend([j for j, _ in pairs] + [0] * pad)
        weights.extend([w for _, w in pairs] + [0.0] * pad)
    return indices, weights, size
