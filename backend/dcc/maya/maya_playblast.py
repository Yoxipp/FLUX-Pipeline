# maya_playblast.py — playblast of the active viewport (Flows node mayPlayblast, P6a).
#
# Runs INSIDE Maya (imported from the backend root like maya_update / maya_keys, through
# the session of the flow). A playblast needs a visible viewport: Live session only
# (E_LIVE_ONLY in headless). Python 3.10 (Maya 2024), maya.cmds only.
# NOT validated in Maya by a test: to check live (P6a "Verification live par le mainteneur" 3).
#
# Formats: "sequence" = PNG images <out>.####.png ; "mov" / "mp4" = Maya's "qt" movie with
# H.264 (needs the H.264 codec of the Maya build; the error says so when it is missing).

from __future__ import annotations

import json
import os


def _active_panel(cmds):
    panel = cmds.getPanel(withFocus=True)
    if not panel or cmds.getPanel(typeOf=panel) != "modelPanel":
        visible = [p for p in (cmds.getPanel(visiblePanels=True) or []) if cmds.getPanel(typeOf=p) == "modelPanel"]
        if not visible:
            raise RuntimeError("aucune vue 3D visible : ouvre un viewport (session Live)")
        panel = visible[0]
    return panel


def playblast(out_path, start=None, end=None, width=0, height=0, fmt="mov", camera="", overwrite=False):
    """Capture the active viewport; returns the written file (or the first image)."""
    import maya.cmds as cmds

    panel = _active_panel(cmds)
    if camera:
        if not cmds.objExists(camera):
            raise RuntimeError("camera introuvable : %s" % camera)
        cmds.lookThru(panel, camera)
    start = cmds.playbackOptions(q=True, minTime=True) if start in (None, "") else float(start)
    end = cmds.playbackOptions(q=True, maxTime=True) if end in (None, "") else float(end)
    base, ext = os.path.splitext(out_path)
    if fmt == "sequence":
        kwargs = {"format": "image", "compression": "png"}
        target = base
        first = "%s.%04d.png" % (base, int(start))
    else:
        kwargs = {"format": "qt", "compression": "H.264"}
        target = base + ("." + fmt)
        first = target
    if os.path.exists(first) and not overwrite:
        raise RuntimeError("%s existe deja : coche overwrite" % first)
    folder = os.path.dirname(target)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    size = {"widthHeight": (int(width), int(height))} if width and height else {"percent": 100}
    written = cmds.playblast(filename=target, startTime=start, endTime=end, viewer=False, showOrnaments=False,
                             forceOverwrite=bool(overwrite), offScreen=True, clearCache=True, quality=100,
                             editorPanelName=panel, **kwargs, **size)
    if fmt == "sequence":
        return first
    return written or target


def run_playblast(config_json, result_path):
    """Session entry: config = {out, start, end, width, height, fmt, camera, overwrite}."""
    try:
        cfg = json.loads(config_json)
        out = {"ok": True, "file": playblast(cfg["out"], cfg.get("start"), cfg.get("end"), cfg.get("width") or 0,
                                             cfg.get("height") or 0, cfg.get("fmt") or "mov", cfg.get("camera") or "",
                                             bool(cfg.get("overwrite")))}
    except Exception as exc:  # noqa: BLE001 - reported to the flow
        out = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
