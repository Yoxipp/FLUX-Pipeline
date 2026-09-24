# maya_keys.py — frame range of the animation from its keyframes (U1, 2026-09-24).
#
# The Publisher fills Start / End of an animated export with the first and last key
# of what is exported (selection and its hierarchy, or the whole scene), instead of a
# fixed 1-100. Driven keys (animCurveU*: input is not time) are ignored. Without keys
# the playback range is used. Runs inside Maya (Python 3.10) through the commandPort.

from __future__ import annotations

import json
import math

try:
    import maya.cmds as cmds  # type: ignore[import]
except ImportError:
    cmds = None

# Time-driven anim curves only (animCurveUL / UA / UU / UT are driven keys).
TIME_CURVE_TYPES = ("animCurveTL", "animCurveTA", "animCurveTU", "animCurveTT")


def key_range(times: list[float] | None) -> tuple[int, int] | None:
    """(first, last) whole frames covering *times*, None without keys."""
    values = [float(t) for t in (times or [])]
    if not values:
        return None
    return int(math.floor(min(values))), int(math.ceil(max(values)))


def _time_curves(nodes: list[str] | None) -> list[str]:
    """Time-driven anim curves feeding *nodes* (and their hierarchy), or of the scene."""
    if nodes is None:
        return cmds.ls(type=list(TIME_CURVE_TYPES)) or []
    targets = set(cmds.ls(nodes, long=True) or [])
    for node in list(targets):
        targets.update(cmds.listRelatives(node, allDescendents=True, fullPath=True) or [])
    curves: set[str] = set()
    for node in targets:
        for curve in cmds.listConnections(node, source=True, destination=False,
                                          type="animCurve", skipConversionNodes=True) or []:
            if cmds.nodeType(curve) in TIME_CURVE_TYPES:
                curves.add(curve)
    return sorted(curves)


def anim_range(scope: str = "scene") -> dict:
    """{"start", "end", "source": "keys" | "timeline", "curves"} for *scope*."""
    selection = (cmds.ls(selection=True, long=True) or []) if scope == "selection" else []
    curves = _time_curves(selection if selection else None)
    found = key_range(cmds.keyframe(curves, query=True, timeChange=True) if curves else None)
    if found is not None:
        return {"start": found[0], "end": found[1], "source": "keys", "curves": len(curves)}
    return {"start": int(cmds.playbackOptions(query=True, minTime=True)),
            "end": int(cmds.playbackOptions(query=True, maxTime=True)),
            "source": "timeline", "curves": 0}


def run_anim_range(scope: str, result_path: str) -> None:
    """commandPort entry: write anim_range(scope) to *result_path* (JSON)."""
    try:
        res = {"ok": True, **anim_range(scope)}
    except Exception as exc:  # noqa: BLE001 - reported to the hub
        res = {"ok": False, "error": repr(exc)}
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(res, fh)
