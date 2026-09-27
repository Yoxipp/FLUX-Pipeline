# anim_apply.py — the layer the FLUX Anim HDA puts on the stage (2026-09-26).
#
# One FLUX Anim node applies the animations of SEVERAL characters: shot animations
# (SEQ_SHOT_ANIM_<NAME>) and asset clips (CLASS_ANIM_<NAME>_<CLIP>). The backend
# writes one small layer the HDA sublayers on its input:
#   over <target>  (references = @anim root file@</NAME>)   one per character
#   over <target>/skel/Anim.rotations                       optional rotation noise,
#        baked per frame (the crowd's noise: a still offset + two waves, root excluded)
# plus the union of the frame ranges and the fps, so the scene timeline follows.
# pxr, backend only.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger("importer.anim_apply")


def list_anims(project_path: str | Path) -> list[dict]:
    """Shot animations then asset clips, each with a unique ``key`` (its base name)
    and a menu ``label``."""
    from .shot_anim import list_asset_clips, list_shot_anims

    out = []
    shots = list_shot_anims(project_path)
    # The key stays the base when a character exists in one sub-task only: the FLUX Anim
    # nodes saved before the sub-tasks keep finding their animation.
    per_base: dict[str, int] = {}
    for item in shots:
        per_base[item["base"]] = per_base.get(item["base"], 0) + 1
    for item in shots:
        sub = (item.get("subtask") or "") if per_base[item["base"]] > 1 else ""
        out.append({**item, "key": item["base"] + (f"@{sub}" if sub else ""),
                    "label": f"PLAN {item['seq']}/{item['shot']}  {item['character']}"
                             + (f"  [{sub}]" if sub else "")})
    for item in list_asset_clips(project_path):
        out.append({**item, "key": item["base"], "label": f"CLIP {item['name']}  {item['clip']}"})
    return out


def anim_file(item: dict, version: str = "LAST") -> str:
    """Root file of *item* at *version* (LAST pointer, else the newest version)."""
    versions = item.get("versions") or {}
    if version and version != "LAST":
        return versions.get(version, "")
    return item.get("last") or (versions[sorted(versions)[-1]] if versions else "")


def anim_info(file: str | Path) -> dict:
    """{"root", "anim_path", "joints", "start", "end", "fps", "interpolation",
    "root_motion"} of a published motion-only animation, or {"error"}."""
    from pxr import Sdf, Usd, UsdSkel

    stage = Usd.Stage.Open(str(file))
    if stage is None:
        return {"error": f"illisible : {Path(file).name}"}
    root = stage.GetDefaultPrim()
    if not root:
        return {"error": f"{Path(file).name} sans defaultPrim"}
    # The root of a motion-only file is an "over": walk every prim, not only defined ones.
    anim = next((p for p in Usd.PrimRange(root, Usd.PrimAllPrimsPredicate)
                 if p.IsA(UsdSkel.Animation)), None)
    if anim is None:
        return {"error": f"{Path(file).name} : pas de SkelAnimation"}
    sa = UsdSkel.Animation(anim)
    times = list(sa.GetRotationsAttr().GetTimeSamples())
    layer = Sdf.Layer.FindOrOpen(str(file))
    fps = (layer.framesPerSecond if layer is not None and layer.HasFramesPerSecond() else 0) \
        or (layer.timeCodesPerSecond if layer is not None else 0) or 24.0
    start = layer.startTimeCode if layer is not None and layer.HasStartTimeCode() else (times[0] if times else 0)
    end = layer.endTimeCode if layer is not None and layer.HasEndTimeCode() else (times[-1] if times else 0)
    return {
        "root": root.GetName(),
        "anim_path": anim.GetPath().MakeRelativePath(root.GetPath()).pathString,
        "joints": len(sa.GetJointsAttr().Get() or []),
        "start": float(start), "end": float(end), "fps": float(fps),
        "interpolation": str(anim.GetCustomDataByKey("flux:interpolation") or "smooth"),
        "root_motion": sa.GetTranslationsAttr().GetNumTimeSamples() > 1,
    }


def build_anim_layer(out: str | Path, rows: list[dict], *, noise: dict | None = None) -> dict:
    """Write the FLUX Anim layer to *out*.

    *rows*: [{"file", "target", "label"}] (target = prim of the character on the
    stage). *noise*: {"amplitude" (degrees), "frequency" (cycles / s), "seed"}; an
    amplitude of 0 (or None) writes no noise. Returns {"layer", "rows": [{..., "info",
    "noise", "error"}], "range": {"start", "end", "fps"} | None}.
    """
    from pxr import Sdf, Vt

    from features.usd_assembler.crowd import _noise_at, _noise_curves, _read_rotations

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Written in memory then exported: rebuilding the same file is the normal case.
    layer = Sdf.Layer.CreateAnonymous(".usda")
    amp = float((noise or {}).get("amplitude") or 0.0)
    freq = float((noise or {}).get("frequency") or 0.0)
    seed = str((noise or {}).get("seed", 0))
    report: list[dict] = []
    start = end = fps = None
    for row in rows:
        entry = {"label": row.get("label", ""), "target": row.get("target", ""),
                 "file": row.get("file", ""), "info": None, "noise": False, "error": ""}
        report.append(entry)
        target, file = entry["target"], entry["file"]
        if not target or not Sdf.Path.IsValidPathString(target) or not Sdf.Path(target).IsAbsolutePath():
            entry["error"] = "prim cible invalide"
            continue
        if not file or not Path(file).is_file():
            entry["error"] = "fichier d'anim introuvable"
            continue
        info = anim_info(file)
        entry["info"] = info
        if info.get("error"):
            entry["error"] = info["error"]
            continue
        spec = Sdf.CreatePrimInLayer(layer, Sdf.Path(target))
        spec.specifier = Sdf.SpecifierOver
        spec.referenceList.Prepend(Sdf.Reference(str(file).replace("\\", "/"),
                                                 Sdf.Path("/" + info["root"])))
        start = info["start"] if start is None else min(start, info["start"])
        end = info["end"] if end is None else max(end, info["end"])
        fps = fps or info["fps"]
        if amp > 0:
            rot = _read_rotations(file, "/" + info["root"])
            if rot.get("error"):
                entry["error"] = "pas de noise : " + rot["error"]
                continue
            curves = _noise_curves(rot["joints"], amp, f"{seed}:{target}")
            anim_spec = Sdf.CreatePrimInLayer(layer, Sdf.Path(target).AppendPath(Sdf.Path(rot["path"])))
            anim_spec.specifier = Sdf.SpecifierOver
            attr = Sdf.AttributeSpec(anim_spec, "rotations", Sdf.ValueTypeNames.QuatfArray)
            for t, values in rot["samples"]:
                at = 0.0 if t is None else t
                wave = _noise_at(curves, amp, freq, at / (rot["fps"] or 24.0))
                noisy = Vt.QuatfArray([v * n for v, n in zip(values, wave)])
                if t is None:
                    attr.default = noisy
                else:
                    layer.SetTimeSample(attr.path, t, noisy)
            entry["noise"] = True
    if start is not None:
        layer.startTimeCode, layer.endTimeCode = start, end
        layer.timeCodesPerSecond = layer.framesPerSecond = fps
    layer.customLayerData = {"flux": {"tool": "flux_anim", "rows": len(rows)}}
    layer.Export(str(out))
    opened = Sdf.Layer.Find(str(out))
    if opened is not None:
        opened.Reload(force=True)
    log.info("FLUX Anim layer %s: %d anim(s), noise %.2f deg", out.name,
             sum(1 for r in report if r["info"] and not r["info"].get("error")), amp)
    return {"layer": str(out), "rows": report,
            "range": {"start": start, "end": end, "fps": fps} if start is not None else None}
