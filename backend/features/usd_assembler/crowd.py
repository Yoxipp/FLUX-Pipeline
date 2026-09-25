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
    for prim in stage.Traverse():
        if prim.IsA(UsdSkel.Skeleton):
            return [str(j) for j in (UsdSkel.Skeleton(prim).GetJointsAttr().Get() or [])]
    return []


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


def author_crowd_layer(dest: str | Path, project_path: str | Path, group: str, agents: list[dict],
                       clip_files: dict[str, Path], *, freeze: bool = False) -> dict:
    """Write the crowd layer *dest*: /crowd/<GROUP>/agent_NNNN (relative references only).

    Returns {"path", "agents", "warnings"}."""
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel

    project = Path(project_path)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    grp = sanitize_token(group) or "crowd"
    layer = Sdf.Layer.CreateNew(str(dest)) if not dest.exists() else Sdf.Layer.FindOrOpen(str(dest))
    layer.Clear()
    stage = Usd.Stage.Open(layer)
    for scope in ("/crowd", f"/crowd/{grp}"):
        # group kind: the agents (components) stay a valid model hierarchy.
        Usd.ModelAPI(UsdGeom.Scope.Define(stage, scope).GetPrim()).SetKind("group")
    targets: dict[str, str] = {}
    starts: dict[str, float] = {}
    written = 0
    for a in agents:
        comp = a["component"]
        if comp not in targets:
            parent = component_dir(project, comp)
            last = parent / f"{comp}_LAST{COMPONENT_EXT}" if parent is not None else None
            if last is None or not last.is_file():
                warnings.append(f"{comp} : pas d'USD d'asset, agents ignores")
                targets[comp] = ""
            else:
                # A publish is frozen (ADR 0017): the farm renders the versions of today,
                # not whatever LAST points to later. The preview follows LAST.
                if freeze:
                    from .component_auto import _latest_entry

                    last = _latest_entry(parent, comp) or last
                targets[comp] = _rel(last, dest.parent)
        if not targets[comp]:
            continue
        path = f"/crowd/{grp}/{a['name']}"
        prim = stage.DefinePrim(path)          # typeless: the component's SkelRoot comes through
        prim.GetReferences().AddReference(targets[comp])
        Usd.ModelAPI(prim).SetKind("component")
        xf = UsdGeom.Xformable(prim)
        xf.AddTranslateOp().Set(Gf.Vec3d(*a["p"]))
        if a.get("ry"):
            xf.AddRotateYOp().Set(float(a["ry"]))
        if a.get("scale", 1.0) != 1.0:
            xf.AddScaleOp().Set(Gf.Vec3f(a["scale"]))
        clip = a.get("clip")
        if clip:
            src = clip_files.get(clip)
            if src is None:
                warnings.append(f"clip {clip} introuvable")
            else:
                if freeze:
                    src = _frozen(src)
                anim_path = f"{path}/crowd_anim"
                anim = stage.DefinePrim(anim_path)
                clip_root = _clip_root(src)
                # Speed 2 = the clip plays twice as fast, around its FIRST frame (not frame 0,
                # which pushed a 1001 clip to frame ~500: agents frozen during the shot):
                # stage time = start + offset + (clip time - start) / speed.
                start = starts.setdefault(str(src), _clip_start(src, clip_root))
                scale = 1.0 / a["speed"]
                anim.GetReferences().AddReference(
                    _rel(src, dest.parent), Sdf.Path(f"/{clip_root}/skel/Anim"),
                    Sdf.LayerOffset(a["offset"] + start * (1.0 - scale), scale))
                UsdSkel.BindingAPI.Apply(prim).CreateAnimationSourceRel().SetTargets([Sdf.Path(anim_path)])
        written += 1
    # FLUX layer contract (ADR 0011): default prim, meters, Y up.
    stage.SetDefaultPrim(stage.GetPrimAtPath("/crowd"))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    layer.customLayerData = {"flux": {"role": "crowd", "group": grp, "agents": str(written)}}
    layer.Save()
    return {"path": dest, "agents": written, "warnings": warnings}


def _clip_start(path: Path, root: str) -> float:
    """First frame of a clip: its stage start, else its first joint sample, else 0."""
    from pxr import Usd

    try:
        clip = Usd.Stage.Open(str(path), Usd.Stage.LoadNone)
        if clip.HasAuthoredTimeCodeRange():
            return float(clip.GetStartTimeCode())
        anim = clip.GetPrimAtPath(f"/{root}/skel/Anim")
        for attr in (anim.GetAttributes() if anim else []):
            samples = attr.GetTimeSamples()
            if samples:
                return float(samples[0])
    except Exception:           # noqa: BLE001 - the offset falls back to frame 0
        pass
    return 0.0


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
                clip_weights: dict[str, float] | None = None) -> dict:
    """Preview (work file in the shot) or publish (SEQ_SHOT_CROWD[_GROUP], vNNN + LAST) a crowd.

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
    base = f"{ss.entity(seq, shot)}_{CROWD_TYPE}" + ("" if grp.lower() == "crowd" else f"_{grp.upper()}")
    if not publish:
        dest = ss.stage_dir(project, seq, shot) / "crowd_work" / f"{base}.usda"
        res = author_crowd_layer(dest, project, grp, agents, by_base)
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
        res = author_crowd_layer(folder / f"{base}.usda", project, grp, agents, by_base, freeze=True)
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
