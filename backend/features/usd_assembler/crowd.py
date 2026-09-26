# crowd.py — FLUX crowd: shared skeletons, animation clips, crowd layer (A6 / A7, ADR 0022).
#
# A6  Skeleton signature: the ordered joint list of an asset's skeleton, hashed. Assets
#     with the same signature share a rig (different geometry, same joints); an animation
#     clip (asset task ANIM, CHAR_ANIM_<NAME>_<clip>, motion only) fits every asset whose
#     skeleton holds all of its joints.
# A7  Crowd layer: one prim per agent under /crowd/<GROUP>, referencing an asset
#     (component) + its own SkelAnimation that references a clip with a layer offset
#     (time offset + speed), so agents share clips without baking. Agents are NOT
#     instanceable: an instance cannot carry its own skel:animationSource.
#     Published in the shot as SEQ_SHOT_CROWD[_GROUP] (department crowd of the stage).

from __future__ import annotations

import random
import re
from pathlib import Path

from core.logger import get_logger

from .component_auto import COMPONENT_EXT, _rel, component_dir
from .structure.naming import sanitize_token

log = get_logger("usd_assembler.crowd")

USD_EXTS = (".usd", ".usda", ".usdc")
CROWD_TYPE = "CROWD"
CROWD_TEMPLATE = "shot/{seq}/{shot}/crowd"
_VERSION_DIR = re.compile(r"^(?P<base>.+)_(?P<ver>v\d{3,})$")


# ── A6: skeletons and clips ──────────────────────────────────────────────────

def skeleton_signature(joints: list[str]) -> str:
    """12 hex chars of the ordered joint paths ("" without joints), as written at publish."""
    from features.usd_export.skel_export import skeleton_signature as _sig

    return _sig(joints)


def _first_skeleton_joints(path: Path) -> list[str]:
    from pxr import Usd, UsdSkel

    stage = Usd.Stage.Open(str(path), Usd.Stage.LoadAll)
    if stage is None:
        return []
    # Every active prim, "over" and instance proxies included: a skinned GEO export can
    # hold its skeleton under an over or an instance (OGRE read "pas de squelette FLUX").
    for prim in Usd.PrimRange.Stage(stage, _ALL_ACTIVE()):
        if prim.IsA(UsdSkel.Skeleton):
            return [str(j) for j in (UsdSkel.Skeleton(prim).GetJointsAttr().Get() or [])]
    return []


def _ALL_ACTIVE():
    from pxr import Usd

    return Usd.TraverseInstanceProxies(Usd.PrimIsActive)


def _clip_joints(path: Path) -> list[str]:
    from pxr import Usd, UsdSkel

    stage = Usd.Stage.Open(str(path))
    if stage is None:
        return []
    # A motion-only clip is an "over" root (the asset owns it): Traverse() would skip it.
    for prim in stage.TraverseAll():
        if prim.IsA(UsdSkel.Animation):
            return [str(j) for j in (UsdSkel.Animation(prim).GetJointsAttr().Get() or [])]
    return []


def component_skeleton(project_path: str | Path, name: str) -> dict:
    """{"signature", "joints"} of an asset's skeleton, read from its component LAST."""
    parent = component_dir(project_path, name)
    last = parent / f"{name}_LAST{COMPONENT_EXT}" if parent is not None else None
    if last is None or not last.is_file():
        return {"signature": "", "joints": []}
    try:
        joints = _first_skeleton_joints(last)
    except Exception as exc:      # noqa: BLE001 - unreadable asset = no skeleton
        log.warning("skeleton of %s unreadable: %s", name, exc)
        joints = []
    return {"signature": skeleton_signature(joints), "joints": joints}


def list_clips(project_path: str | Path) -> list[dict]:
    """Animation clips of the project: asset ANIM publishes (motion only).

    [{"base", "asset", "clip", "last", "joints", "range", "fps"}]."""
    from features.folder_manager.tokens import load_tokens
    from features.publisher.last_pointer import read_usd_root_info
    from features.usd_export.departments import contribution

    project = Path(project_path)
    tokens = load_tokens(project) or {}
    out = []
    for name, rel in sorted((tokens.get("NAME") or {}).items()):
        folder = project / str(rel).replace("\\", "/") / (tokens.get("TYPE", {}).get("ANIM") or "anim")
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*/*_LAST.usd*")):
            if f.suffix.lower() not in USD_EXTS or ".proxy" in f.name:
                continue
            base = f.stem[:-5]
            contrib = contribution(base)
            if not contrib or contrib["kind"] != "clip":
                continue
            info = read_usd_root_info(f)
            try:
                joints = _clip_joints(f)
            except Exception:          # noqa: BLE001
                joints = []
            out.append({
                "base": base, "asset": name, "clip": contrib.get("instance") or "null",
                "last": str(f), "joints": joints,
                "range": ([int(info["startTimeCode"]), int(info["endTimeCode"])]
                          if "startTimeCode" in info and "endTimeCode" in info else None),
                "fps": float(info.get("framesPerSecond") or info.get("timeCodesPerSecond") or 24),
            })
    return out


def compatibility(project_path: str | Path, names: list[str] | None = None) -> dict:
    """Which assets share a skeleton and which clips fit them.

    {"assets": {NAME: {"signature", "joint_count", "compatible": [NAME], "clips": [base]}},
     "clips": [clip dicts]}. A clip fits an asset whose skeleton holds all of its joints."""
    from features.folder_manager.tokens import load_tokens

    project = Path(project_path)
    if names is None:
        names = sorted((load_tokens(project) or {}).get("NAME", {}))
    skels = {n: component_skeleton(project, n) for n in names}
    clips = list_clips(project)
    assets = {}
    for n, sk in skels.items():
        if not sk["signature"]:
            continue
        joints = set(sk["joints"])
        assets[n] = {
            "signature": sk["signature"], "joint_count": len(sk["joints"]),
            "compatible": sorted(m for m, o in skels.items() if m != n and o["signature"] == sk["signature"]),
            "clips": [c["base"] for c in clips if c["joints"] and set(c["joints"]) <= joints],
        }
    return {"assets": assets, "clips": clips}


# ── A7: crowd layer ──────────────────────────────────────────────────────────

def _weighted(rng: random.Random, items: list[str], weights: dict[str, float] | None) -> str:
    """One of *items*; with *weights* ({item: w >= 0}) the draw follows them (missing = 1)."""
    if not weights:
        return rng.choice(items)
    w = [max(0.0, float(weights.get(i, 1.0))) for i in items]
    if not any(w):
        return rng.choice(items)
    return rng.choices(items, weights=w, k=1)[0]


def plan_agents(points: list[dict], components: list[str], clips: list[str], *, seed: int = 0,
                offset: tuple[float, float] = (0.0, 0.0), speed: tuple[float, float] = (1.0, 1.0),
                component_weights: dict[str, float] | None = None,
                clip_weights: dict[str, float] | None = None,
                fits: dict[str, set[str]] | None = None) -> list[dict]:
    """One agent per point: component, clip, time offset and speed drawn with *seed*.

    *points*: [{"p": [x, y, z], "ry": degrees (optional), "scale": s (optional)}].
    *component_weights* / *clip_weights*: "more of this asset / this animation" (FLUX Crowd
    rows, 2026-09-25). *fits*: {component: clip bases its skeleton plays}; an agent
    only gets a clip that fits its asset (none fits: rest pose)."""
    if not components:
        raise ValueError("aucun asset pour la foule")
    comps = [c for c in components if not component_weights or float(component_weights.get(c, 1.0)) > 0] \
        or list(components)
    rng = random.Random(seed)
    agents = []
    for i, pt in enumerate(points):
        comp = _weighted(rng, comps, component_weights)
        usable = [c for c in clips if fits is None or c in fits.get(comp, set())]
        if clip_weights:
            usable = [c for c in usable if float(clip_weights.get(c, 1.0)) > 0]
        agents.append({
            "name": f"agent_{i + 1:04d}",
            "component": comp,
            "clip": _weighted(rng, usable, clip_weights) if usable else "",
            "p": [float(v) for v in (pt.get("p") or [0, 0, 0])[:3]],
            "ry": float(pt.get("ry") or 0.0),
            "scale": float(pt.get("scale") or 1.0),
            "offset": rng.uniform(*sorted(offset)),
            "speed": max(0.01, rng.uniform(*sorted(speed))),
        })
    return agents


def _frozen(path: Path) -> Path:
    """The vNNN a LAST pointer layer targets (ADR 0017), else *path* itself."""
    from pxr import Sdf

    if not Path(path).stem.endswith("_LAST"):
        return Path(path)
    layer = Sdf.Layer.FindOrOpen(str(path))
    subs = list(layer.subLayerPaths) if layer is not None else []
    if len(subs) == 1:
        target = (Path(path).parent / subs[0]).resolve()
        if target.is_file():
            return target
    return Path(path)


def _bound_anim(prim, root):
    """The SkelAnimation bound to *prim* (a Skeleton) or its nearest ancestor up to *root*."""
    from pxr import UsdSkel

    stage = prim.GetStage()
    p = prim
    while p and p.IsValid():
        rel = UsdSkel.BindingAPI(p).GetAnimationSourceRel()
        targets = rel.GetForwardedTargets() if rel else []
        if targets:
            anim = stage.GetPrimAtPath(targets[0])
            return anim if anim and anim.IsA(UsdSkel.Animation) else None
        if p == root:
            break
        p = p.GetParent()
    return None


def _anim_source(anim) -> dict | None:
    """{"file", "prim"} the SkelAnimation *anim* comes from: the file it references
    (a component's anims/<id>), else the file that defines it (a skinned GEO export)."""
    from pxr import Pcp, Usd

    try:
        for arc in Usd.PrimCompositionQuery(anim).GetCompositionArcs():
            if arc.GetArcType() not in (Pcp.ArcTypeReference, Pcp.ArcTypePayload):
                continue
            layer = arc.GetTargetLayer()
            if layer is not None and layer.realPath and not arc.GetTargetPrimPath().isEmpty:
                return {"file": layer.realPath, "prim": arc.GetTargetPrimPath().pathString}
    except Exception:           # noqa: BLE001 - falls back on the prim stack
        pass
    for spec in reversed(anim.GetPrimStack()):
        if spec.layer.realPath and not spec.path.ContainsPrimVariantSelection() and spec.typeName:
            return {"file": spec.layer.realPath, "prim": spec.path.pathString}
    return None


def probe_agent(target: Path, target_prim: str = "", variants: dict[str, str] | None = None,
                inactive: list[str] | None = None) -> dict:
    """What one agent of an asset brings, with the FLUX Import choices applied.

    {"skeletons": [path relative to the agent], "anim": {"file", "prim"} | None (the
    animation the asset itself plays), "anims": every animation checked in FLUX Import
    (the bound one first), "baked": points animated without a SkelAnimation}."""
    from pxr import Sdf, Usd, UsdGeom, UsdSkel

    stage = Usd.Stage.CreateInMemory()
    agent = stage.DefinePrim("/agent")
    if target_prim:
        agent.GetReferences().AddReference(str(target), Sdf.Path(target_prim))
    else:
        agent.GetReferences().AddReference(str(target))
    sets = agent.GetVariantSets()
    for name, sel in sorted((variants or {}).items()):
        sets.SetSelection(name, sel)
    for rel in inactive or []:
        if Sdf.Path.IsValidPathString(rel):
            stage.OverridePrim(agent.GetPath().AppendPath(Sdf.Path(rel))).SetActive(False)
    out = {"skeletons": [], "anim": None, "anims": [], "baked": False, "rest": None,
           "instanced": agent.IsInstance(), "instances": [], "joints": 0}
    others = []
    for prim in Usd.PrimRange(agent, _ALL_ACTIVE()):
        if prim.IsInstance():
            out["instances"].append(prim.GetPath().MakeRelativePath(agent.GetPath()).pathString)
        if prim.IsA(UsdSkel.Animation):
            src = _anim_source(prim)
            if src and src not in others:
                others.append(src)
        if prim.IsA(UsdSkel.Skeleton):
            out["skeletons"].append(prim.GetPath().MakeRelativePath(agent.GetPath()).pathString)
            if out["rest"] is None:
                out["rest"] = _rest_pose(UsdSkel.Skeleton(prim))
                out["joints"] = len(UsdSkel.Skeleton(prim).GetJointsAttr().Get() or [])
            if out["anim"] is None:
                anim = _bound_anim(prim, agent)
                if anim is not None:
                    out["anim"] = _anim_source(anim)
        elif prim.IsA(UsdGeom.PointBased) and not out["baked"]:
            out["baked"] = UsdGeom.PointBased(prim).GetPointsAttr().GetNumTimeSamples() > 1
    # Two animations checked: USD binds only one on the skeleton, the crowd shares the
    # agents between all of them (2026-09-26: only one of OGRE's two anims played).
    out["anims"] = ([out["anim"]] if out["anim"] else []) + [o for o in others if o != out["anim"]]
    return out


def _rest_pose(skel) -> dict | None:
    """{"joints", "translations", "rotations", "scales"} of a Skeleton's rest pose."""
    from pxr import UsdSkel

    joints = skel.GetJointsAttr().Get() or []
    rest = skel.GetRestTransformsAttr().Get() or skel.GetBindTransformsAttr().Get()
    if not joints or not rest or len(rest) != len(joints):
        return None
    t, r, s = UsdSkel.DecomposeTransforms(rest)
    return {"joints": [str(j) for j in joints], "translations": t, "rotations": r, "scales": s}


def _joint_noise(joints: list[str], amplitude: float, key: str) -> list:
    """One still rotation per joint (degrees, deterministic per *key*); the root stays put
    (a root rotation turns the whole body). Joints named without their path (flat
    list, some exports): only the first one is taken as the root."""
    return _noise_at(_noise_curves(joints, amplitude, key), amplitude, 0.0, 0.0)


def _noise_curves(joints: list[str], amplitude: float, key: str) -> list:
    """Per joint: None (root) or (axis, still part in [-1, 1], two (frequency factor,
    phase) waves). Deterministic per *key*: each agent gets its own noise."""
    import math

    from pxr import Gf

    rng = random.Random(key)
    pathed = any("/" in str(j) for j in joints)
    out = []
    for i, j in enumerate(joints):
        if ("/" not in str(j)) if pathed else i == 0:
            out.append(None)
            continue
        axis = Gf.Vec3d(rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))
        if axis.GetLength() < 1e-9:
            axis = Gf.Vec3d(0, 1, 0)
        out.append((axis.GetNormalized(), rng.uniform(-1.0, 1.0),
                    ((rng.uniform(0.6, 1.4), rng.uniform(0, 2 * math.pi)),
                     (rng.uniform(1.6, 2.6), rng.uniform(0, 2 * math.pi)))))
    return out


def _noise_at(curves: list, amplitude: float, frequency: float, seconds: float) -> list:
    """The rotation of each joint at *seconds*: a still offset plus two waves of
    *frequency* (cycles per second); *frequency* 0 = the still offset alone."""
    import math

    from pxr import Gf

    out = []
    for c in curves:
        if c is None:
            out.append(Gf.Quatf(1.0))
            continue
        axis, still, waves = c
        if frequency > 0:
            (f1, p1), (f2, p2) = waves
            wave = 0.6 * math.sin(2 * math.pi * frequency * f1 * seconds + p1) + \
                0.4 * math.sin(2 * math.pi * frequency * f2 * seconds + p2)
            value = 0.3 * still + 0.7 * wave
        else:
            value = still
        out.append(Gf.Quatf(Gf.Rotation(axis, amplitude * value).GetQuat()))
    return out


_MAX_NOISE_FRAMES = 20000


def _read_rotations(file: str | Path, prim: str) -> dict:
    """{"joints", "fps", "samples": [(time or None, [Quatf])]} of a SkelAnimation, one
    sample per frame between its first and last keys (a moving noise needs every frame,
    rotations between two keys are interpolated by USD), or {"error": why}.

    Read the way an agent sees it: a reference to *prim* of *file*, payloads loaded
    (2026-09-26, OGRE: opening the file without its payloads read nothing)."""
    import math

    from pxr import Sdf, Usd, UsdSkel

    stage = Usd.Stage.CreateInMemory()
    holder = stage.DefinePrim("/anim")
    holder.GetReferences().AddReference(str(file), Sdf.Path(prim) if prim else Sdf.Path())
    target = holder
    if not target.IsA(UsdSkel.Animation):
        # The reference may land on the clip root: its first SkelAnimation below.
        target = next((p for p in Usd.PrimRange(holder, Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate))
                       if p.IsA(UsdSkel.Animation)), None)
    if target is None:
        return {"error": f"{Path(file).name} {prim} n'est pas une SkelAnimation "
                         f"(type {holder.GetTypeName() or 'aucun'})"}
    anim = UsdSkel.Animation(target)
    joints = [str(j) for j in (anim.GetJointsAttr().Get() or [])]
    if not joints:
        return {"error": f"{Path(file).name} : SkelAnimation sans joints"}
    attr = anim.GetRotationsAttr()
    times = list(attr.GetTimeSamples())
    if times and times[-1] - times[0] < _MAX_NOISE_FRAMES:
        frames = range(math.floor(times[0]), math.ceil(times[-1]) + 1)
        times = sorted(set(times) | {float(f) for f in frames if times[0] <= f <= times[-1]})
    samples = [(t, list(attr.Get(t) or [])) for t in times] if times else [(None, list(attr.Get() or []))]
    if not any(len(v) == len(joints) for _, v in samples):
        return {"error": f"{Path(file).name} : rotations absentes ou pas une par joint "
                         f"({len(samples[0][1])} pour {len(joints)} joints)"}
    samples = [(t, v) for t, v in samples if len(v) == len(joints)]
    layer = Sdf.Layer.FindOrOpen(str(file))
    fps = (layer.timeCodesPerSecond if layer is not None and layer.HasTimeCodesPerSecond() else 0) or 24.0
    return {"joints": joints, "samples": samples, "fps": float(fps),
            "path": target.GetPath().MakeRelativePath(holder.GetPath()).pathString}


def author_crowd_layer(dest: str | Path, project_path: str | Path, group: str, agents: list[dict],
                       clip_files: dict[str, Path], *, freeze: bool = False,
                       sources: dict[str, dict] | None = None,
                       looks: dict[str, dict] | None = None, rot_noise: float = 0.0,
                       seed: int = 0, noise_freq: float = 1.0, variations: int = 0) -> dict:
    """Write the crowd layer *dest*: /crowd/<GROUP>/agent_NNNN (relative references only).

    *variations* > 0 (2026-09-26: unique agents lag): per asset and clip, that many
    prototypes (/crowd_protos/<GROUP>/<ASSET>_NNN, class prims: never drawn) each with its
    own animation, offset, speed and noise; every agent is an instance of one of them, so
    agents share geometry and skinning. 0 = every agent unique (heavy, one noise each).

    *sources* ({asset: {"file", "prim"}}, from FLUX Crowd input 1): used for an asset
    without a FLUX component, so it still shows (static mesh, 2026-09-26).
    *looks* ({asset: {"variants": {set: selection}, "inactive": [relative path]}}): the
    FLUX Import choices of input 1, applied on every agent: an animation unchecked there
    does not play in the crowd (2026-09-26).
    Each agent plays its crowd clip, else the animation its asset plays, with its time
    offset and speed; the binding is set on the skeleton itself (a component binds its
    animation there, which beat the agent's binding: offset / speed did nothing).
    *rot_noise* (degrees): a rotation per joint and per agent, moving at *noise_freq*
    cycles per second (0 = still), written in a ``<dest>_noise.usdc`` sublayer.

    Returns {"path", "agents", "warnings"}."""
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel, Vt

    project = Path(project_path)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    grp = sanitize_token(group) or "crowd"
    layer = Sdf.Layer.CreateNew(str(dest)) if not dest.exists() else Sdf.Layer.FindOrOpen(str(dest))
    layer.Clear()
    noise_path = dest.with_name(dest.stem + "_noise.usdc")
    noise_layer = None
    if rot_noise > 0:
        noise_layer = Sdf.Layer.CreateNew(str(noise_path)) if not noise_path.exists() \
            else Sdf.Layer.FindOrOpen(str(noise_path))
        noise_layer.Clear()
        layer.subLayerPaths.append("./" + noise_path.name)
    elif noise_path.exists():
        noise_path.unlink()
    stage = Usd.Stage.Open(layer)
    for scope in ("/crowd", f"/crowd/{grp}"):
        # group kind: the agents (components) stay a valid model hierarchy.
        Usd.ModelAPI(UsdGeom.Scope.Define(stage, scope).GetPrim()).SetKind("group")
    if variations > 0:
        stage.CreateClassPrim("/crowd_protos")
        stage.CreateClassPrim(f"/crowd_protos/{grp}")
    targets: dict[str, str] = {}
    target_prims: dict[str, Sdf.Path] = {}
    probes: dict[str, dict] = {}
    starts: dict[str, float] = {}
    rotations: dict[str, dict | None] = {}
    noise_skipped: set[str] = set()
    info: list[str] = []
    written = noised = 0
    protos: dict[tuple, str] = {}
    proto_noised: dict[tuple, bool] = {}

    def _body(prim, comp: str, look: dict, probe: dict, a: dict, name: str) -> bool:
        """The asset, the FLUX Import choices, the animation and the noise on *prim* (an
        agent, or a prototype its instances share). True when the noise was applied."""
        path = prim.GetPath().pathString
        did_noise = False
        if comp in target_prims:
            prim.GetReferences().AddReference(targets[comp], target_prims[comp])
        else:
            prim.GetReferences().AddReference(targets[comp])
        Usd.ModelAPI(prim).SetKind("component")
        # Never an instance: an instanceable asset made every agent one, and USD ignores
        # whatever is authored under an instance (clip, offset, speed, noise did nothing).
        prim.SetInstanceable(False)
        for rel in probe.get("instances") or []:
            if rel != ".":
                stage.OverridePrim(prim.GetPath().AppendPath(Sdf.Path(rel))).SetInstanceable(False)
        # The FLUX Import choices of input 1 (animations unchecked, rig off...).
        sets = prim.GetVariantSets()
        for vset_name, sel in sorted((look.get("variants") or {}).items()):
            sets.SetSelection(vset_name, sel)
        for rel in look.get("inactive") or []:
            if Sdf.Path.IsValidPathString(rel):
                stage.OverridePrim(prim.GetPath().AppendPath(Sdf.Path(rel))).SetActive(False)
        # The animation: the crowd clip, else the one the asset plays (checked in FLUX Import).
        src_file, src_prim = None, ""
        clip = a.get("clip")
        if clip:
            src = clip_files.get(clip)
            if src is None:
                warnings.append(f"clip {clip} introuvable")
            else:
                src_file = _frozen(src) if freeze else src
                src_prim = f"/{_clip_root(src_file)}/skel/Anim"
        if src_file is None and probe.get("anims"):
            pick = random.Random(f"{seed}:{name}:anim").choice(probe["anims"])
            src_file, src_prim = Path(pick["file"]), pick["prim"]
        if src_file is not None:
            key = f"{src_file}|{src_prim}"
            if key not in rotations:
                try:
                    rotations[key] = _read_rotations(src_file, src_prim)
                except Exception as exc:     # noqa: BLE001 - no noise on that clip
                    log.warning("crowd noise: %s unreadable: %s", src_file, exc)
                    rotations[key] = {"error": f"{Path(src_file).name} illisible : {exc}"}
            rot = rotations[key]
            if src_prim and rot.get("path") not in (None, "", "."):
                # The reference landed on the clip root: point at its SkelAnimation.
                src_prim = f"{src_prim.rstrip('/')}/{rot['path']}"
            anim_path = f"{path}/crowd_anim"
            anim = stage.DefinePrim(anim_path)
            # Speed 2 = the clip plays twice as fast, around its FIRST frame (not frame 0,
            # which pushed a 1001 clip to frame ~500: agents frozen during the shot):
            # stage time = start + offset + (clip time - start) / speed.
            start = starts.setdefault(key, _anim_start(src_file, src_prim))
            scale = 1.0 / a["speed"]
            shift = a["offset"] + start * (1.0 - scale)
            anim.GetReferences().AddReference(_rel(src_file, dest.parent), Sdf.Path(src_prim),
                                              Sdf.LayerOffset(shift, scale))
            # On the agent AND on each skeleton: a binding on the skeleton (the component's
            # own animation) beats one on an ancestor.
            for where in [path] + [f"{path}/{s}" for s in probe["skeletons"]]:
                over = stage.OverridePrim(where)
                UsdSkel.BindingAPI.Apply(over).CreateAnimationSourceRel().SetTargets([Sdf.Path(anim_path)])
            if noise_layer is not None:
                if rot.get("joints"):
                    # Its own noise per agent (and per clip), moving along the shot time.
                    curves = _noise_curves(rot["joints"], rot_noise, f"{seed}:{name}:{key}")
                    spec = Sdf.CreatePrimInLayer(noise_layer, anim_path)
                    attr = Sdf.AttributeSpec(spec, "rotations", Sdf.ValueTypeNames.QuatfArray)
                    for t, values in rot["samples"]:
                        at = shift + scale * t if t is not None else 0.0
                        noise = _noise_at(curves, rot_noise, noise_freq, at / rot["fps"])
                        noisy = Vt.QuatfArray([v * n for v, n in zip(values, noise)])
                        if t is None:
                            attr.default = noisy
                        else:
                            noise_layer.SetTimeSample(attr.path, at, noisy)
                    did_noise = True
                elif comp not in noise_skipped:
                    noise_skipped.add(comp)
                    warnings.append(f"{comp} : pas de noise, {rot.get('error') or 'rotations illisibles'}")
        elif noise_layer is not None and probe["skeletons"]:
            # No animation (unchecked in FLUX Import): the noise poses the rest pose, so a
            # still crowd is not a copy of one statue (2026-09-26: the noise did nothing).
            rest = probe.get("rest")
            if rest:
                anim_path = f"{path}/crowd_anim"
                anim = UsdSkel.Animation.Define(stage, anim_path)
                noise = _joint_noise(rest["joints"], rot_noise, f"{seed}:{name}")
                anim.CreateJointsAttr(Vt.TokenArray(rest["joints"]))
                anim.CreateTranslationsAttr(rest["translations"])
                anim.CreateRotationsAttr(Vt.QuatfArray([v * n for v, n in zip(rest["rotations"], noise)]))
                anim.CreateScalesAttr(rest["scales"])
                for where in [path] + [f"{path}/{s}" for s in probe["skeletons"]]:
                    over = stage.OverridePrim(where)
                    UsdSkel.BindingAPI.Apply(over).CreateAnimationSourceRel().SetTargets([Sdf.Path(anim_path)])
                did_noise = True
            elif comp not in noise_skipped:
                noise_skipped.add(comp)
                warnings.append(f"{comp} : squelette sans pose de repos, pas de noise")
        elif noise_layer is not None and comp not in noise_skipped:
            noise_skipped.add(comp)
            warnings.append(f"{comp} : pas de squelette, pas de noise")
        return did_noise

    for a in agents:
        comp = a["component"]
        look = (looks or {}).get(comp) or {}
        if comp not in targets:
            parent = component_dir(project, comp)
            last = parent / f"{comp}_LAST{COMPONENT_EXT}" if parent is not None else None
            src = (sources or {}).get(comp) or {}
            absolute = None
            if (last is None or not last.is_file()) and src.get("file") and Path(src["file"]).is_file():
                warnings.append(f"{comp} : pas de component FLUX, fichier de l'entree 1 utilise")
                absolute = Path(src["file"])
                if src.get("prim") and Sdf.Path.IsValidPathString(src["prim"]):
                    target_prims[comp] = Sdf.Path(src["prim"])
            elif last is None or not last.is_file():
                warnings.append(f"{comp} : pas d'USD d'asset, agents ignores")
            else:
                # A publish is frozen (ADR 0017): the farm renders the versions of today,
                # not whatever LAST points to later. The preview follows LAST.
                if freeze:
                    from .component_auto import _latest_entry

                    last = _latest_entry(parent, comp) or last
                absolute = last
            targets[comp] = _rel(absolute, dest.parent) if absolute is not None else ""
            if absolute is not None:
                try:
                    probes[comp] = probe_agent(absolute, str(target_prims.get(comp, "")),
                                               look.get("variants"), look.get("inactive"))
                except Exception as exc:      # noqa: BLE001 - the agent still shows
                    log.warning("crowd probe of %s failed: %s", comp, exc)
                    probes[comp] = {"skeletons": [], "anim": None, "anims": [], "baked": False, "rest": None}
                pr = probes[comp]
                info.append(f"{comp} : {len(pr['skeletons'])} squelette(s), {pr['joints']} joints, "
                            f"{len(pr['anims'])} anim(s)" + (", instance retiree" if pr.get("instanced")
                                                              or pr.get("instances") else ""))
                if pr["baked"] and pr["anim"] is None:
                    warnings.append(f"{comp} : anim cuite dans les points (pas de squelette anime), "
                                    "decalage / vitesse / noise sans effet")
        if not targets[comp]:
            continue
        probe = probes.get(comp) or {"skeletons": [], "anim": None, "anims": [], "baked": False, "rest": None}
        path = f"/crowd/{grp}/{a['name']}"
        if variations > 0:
            var = random.Random(f"{seed}:{a['name']}:variation").randrange(variations)
            pkey = (comp, a.get("clip") or "", var)
            if pkey not in protos:
                protos[pkey] = f"/crowd_protos/{grp}/{sanitize_token(comp) or 'asset'}_{len(protos) + 1:03d}"
                proto_noised[pkey] = _body(stage.DefinePrim(protos[pkey]), comp, look, probe, a,
                                           protos[pkey].rsplit("/", 1)[-1])
            prim = stage.DefinePrim(path)
            prim.GetReferences().AddInternalReference(protos[pkey])
            Usd.ModelAPI(prim).SetKind("component")
            prim.SetInstanceable(True)
            noised += int(proto_noised[pkey])
        else:
            prim = stage.DefinePrim(path)
            noised += int(_body(prim, comp, look, probe, a, a["name"]))
        xf = UsdGeom.Xformable(prim)
        xf.AddTranslateOp().Set(Gf.Vec3d(*a["p"]))
        if a.get("ry"):
            xf.AddRotateYOp().Set(float(a["ry"]))
        if a.get("scale", 1.0) != 1.0:
            xf.AddScaleOp().Set(Gf.Vec3f(a["scale"]))
        written += 1

    # FLUX layer contract (ADR 0011): default prim, meters, Y up.
    stage.SetDefaultPrim(stage.GetPrimAtPath("/crowd"))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    layer.customLayerData = {"flux": {"role": "crowd", "group": grp, "agents": str(written),
                                      "variations": str(len(protos))}}
    if noise_layer is not None:
        noise_layer.Save()
    layer.Save()
    first = next((f"/crowd/{grp}/{a['name']}" for a in agents if targets.get(a["component"])), "")
    if first:
        try:
            info += diagnose_agent(dest, first)
        except Exception as exc:        # noqa: BLE001 - diagnostics never fail a build
            log.warning("crowd diagnose failed: %s", exc)
    return {"path": dest, "agents": written, "warnings": warnings, "noised": noised, "info": info,
            "variations": len(protos)}


def diagnose_agent(layer_path: str | Path, agent_path: str) -> list[str]:
    """What really drives one agent of the written crowd layer, for the FLUX Crowd status
    (2026-09-26: noise 1000 did nothing): per skeleton, how many meshes it skins and
    which animation it plays; meshes whose points are animated without the skeleton."""
    from pxr import Usd, UsdGeom, UsdSkel

    out: list[str] = []
    stage = Usd.Stage.Open(str(layer_path))
    agent = stage.GetPrimAtPath(agent_path) if stage else None
    if not agent:
        return out
    name = agent.GetName()
    pred = Usd.TraverseInstanceProxies()
    roots = [p for p in Usd.PrimRange(agent, pred) if p.IsA(UsdSkel.Root)]
    if not roots:
        return [f"{name} : pas de SkelRoot, aucun mesh n'est skinne (la geo ne suit pas les bones)"]
    cache = UsdSkel.Cache()
    for root in roots[:1]:
        skel_root = UsdSkel.Root(root)
        cache.Populate(skel_root, pred)
        bindings = cache.ComputeSkelBindings(skel_root, pred)
        if not bindings:
            out.append(f"{name} : aucun mesh lie a un squelette (skel:skeleton absent), la geo ne suit pas les bones")
        for b in bindings:
            skel = b.GetSkeleton()
            query = cache.GetSkelQuery(skel)
            anim = query.GetAnimQuery() if query else None
            anim_name = anim.GetPrim().GetName() if anim else "aucune"
            out.append(f"{name} : {skel.GetPrim().GetName()} skinne {len(b.GetSkinningTargets())} mesh, "
                       f"anim {anim_name}")
    baked = sum(1 for p in Usd.PrimRange(agent, pred)
                if p.IsA(UsdGeom.Mesh) and UsdGeom.Mesh(p).GetPointsAttr().GetNumTimeSamples() > 1)
    if baked:
        out.append(f"{name} : {baked} mesh avec les points animes (anim cuite : le noise ne peut pas la changer)")
    return out


def _anim_start(path: str | Path, prim: str) -> float:
    """First frame of the SkelAnimation *prim* of *path*: stage start, else first sample, else 0."""
    from pxr import Usd

    try:
        clip = Usd.Stage.Open(str(path), Usd.Stage.LoadNone)
        if clip.HasAuthoredTimeCodeRange():
            return float(clip.GetStartTimeCode())
        anim = clip.GetPrimAtPath(prim)
        for attr in (anim.GetAttributes() if anim else []):
            samples = attr.GetTimeSamples()
            if samples:
                return float(samples[0])
    except Exception:           # noqa: BLE001 - the offset falls back to frame 0
        pass
    return 0.0


def _clip_start(path: Path, root: str) -> float:
    """First frame of a clip: its stage start, else its first joint sample, else 0."""
    return _anim_start(path, f"/{root}/skel/Anim")


def _clip_root(path: Path) -> str:
    from features.publisher.last_pointer import read_usd_root_info

    return str(read_usd_root_info(path).get("defaultPrim") or "")


def ensure_crowd_token(project_path: str | Path) -> None:
    """The shot TYPE CROWD (A7) in the project tokens, added once (auto-heal)."""
    from features.folder_manager.tokens import load_tokens, save_tokens

    project = Path(project_path)
    tokens = load_tokens(project) or {}
    shot_types = tokens.setdefault("TYPE_SHOT", {})
    if CROWD_TYPE not in shot_types:
        shot_types[CROWD_TYPE] = CROWD_TEMPLATE
        save_tokens(project, tokens)


def build_crowd(project_path: str | Path, seq: str, shot: str, group: str, points: list[dict], *,
                components: list[str], clips: list[str], seed: int = 0,
                offset: tuple[float, float] = (0.0, 0.0), speed: tuple[float, float] = (1.0, 1.0),
                publish: bool = False, user: str = "",
                component_weights: dict[str, float] | None = None,
                clip_weights: dict[str, float] | None = None,
                sources: dict[str, dict] | None = None, looks: dict[str, dict] | None = None,
                rot_noise: float = 0.0, noise_freq: float = 1.0, variations: int = 0) -> dict:
    """Preview (work file in the shot) or publish (SEQ_SHOT_CROWD[_GROUP], vNNN + LAST) a crowd.

    A preview needs no shot (2026-09-26: a project without shots must still show
    the agents): it is then written in <project>/shot/crowd_work. A publish needs one.

    Returns {"path", "agents", "warnings", "version" (publish only), "stage" (publish only)}."""
    from features.folder_manager.naming_validator import format_version

    from . import shot_stage as ss

    project = Path(project_path)
    by_base = {c["base"]: Path(c["last"]) for c in list_clips(project)}
    unknown = [c for c in clips if c not in by_base]
    known = [c for c in clips if c in by_base]
    # Each agent only plays a clip its asset's skeleton holds.
    compat = compatibility(project, list(components)).get("assets", {}) if known else {}
    fits = {c: set(compat.get(c, {}).get("clips", [])) for c in components} if known else None
    agents = plan_agents(points, components, known, seed=seed, offset=offset, speed=speed,
                         component_weights=component_weights, clip_weights=clip_weights, fits=fits)
    no_clip = sorted({c for c in components if fits is not None and not (fits.get(c, set()) & set(known))})
    grp = sanitize_token(group) or "crowd"
    suffix = "" if grp.lower() == "crowd" else f"_{grp.upper()}"
    has_shot = bool(seq and shot)
    if publish and not has_shot:
        raise ValueError("publier une foule demande une sequence et un shot")
    base = (f"{ss.entity(seq, shot)}_" if has_shot else "") + CROWD_TYPE + suffix
    if not publish:
        work = ss.stage_dir(project, seq, shot) if has_shot else project / "shot"
        dest = work / "crowd_work" / f"{base}.usda"
        res = author_crowd_layer(dest, project, grp, agents, by_base, sources=sources, looks=looks,
                                 rot_noise=rot_noise, seed=seed,
                                 noise_freq=noise_freq, variations=variations)
        res["warnings"] = ([f"clip inconnu : {c}" for c in unknown]
                           + [f"aucune anim ne va sur le rig de {c} : pose de repos" for c in no_clip]
                           + res["warnings"])
        return res

    from features.publisher import last_pointer as lp
    from features.publisher.publish_core import ensure_dir, resolve_publish_path
    from features.publisher.publish_layout import (
        discard_rendered_version, reserve_version, sequence_folder,
    )

    ensure_crowd_token(project)
    parent = resolve_publish_path(project, f"{base}.usda")
    if parent is None:
        raise ValueError(f"chemin de publish introuvable pour {base}")
    ensure_dir(parent)
    ver = reserve_version(parent, base, ".usda")
    folder = sequence_folder(parent, base, ver)
    try:
        res = author_crowd_layer(folder / f"{base}.usda", project, grp, agents, by_base, freeze=True,
                                 sources=sources, looks=looks, rot_noise=rot_noise, seed=seed,
                                 noise_freq=noise_freq, variations=variations)
    except Exception:
        discard_rendered_version(parent, base, ".usda", ver, is_sequence=True)
        raise
    root = folder / f"{base}.usda"
    lp.write_last(parent, base, ".usda", folder, ver, lp.MODE_LAYER, user=user,
                  layer_target=f"{folder.name}/{root.name}")
    from features.publisher.modif_log import append_log
    from features.publisher.usd_publish_hooks import after_usd_publish

    version = format_version(ver)
    append_log(parent, base, version, f"foule {grp} : {res['agents']} agent(s)", user or "flux")
    hooked = after_usd_publish(parent, base, ".usda", root, user=user)
    res.update(version=version, base=base, stage=(hooked.get("shot") or {}).get("version"))
    res["warnings"] = ([f"clip inconnu : {c}" for c in unknown]
                       + [f"aucune anim ne va sur le rig de {c} : pose de repos" for c in no_clip]
                       + res["warnings"])
    log.info("Crowd %s %s: %d agents", base, version, res["agents"])
    return res
