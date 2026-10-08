# routers/review.py — review players (Keyframe Pro, retake 09).
#
# GET  /review/keyframe/status : installed exe + state of the external API.
# POST /review/keyframe/open   : open pipeline videos (a single one, a version
#                                list, or the auto edit of the Timeline). Answers
#                                mode api | cli | none (+ code, message).
# Only files inside the project folder are accepted; nothing is copied.

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from core.paths import get_project_path, is_subpath
from features.review import keyframe

log = get_logger(__name__)
router = APIRouter()


class KeyframeItem(BaseModel):
    rel_path: str = ""      # project-relative file
    path: str = ""          # or absolute (must stay inside the project)
    label: str = ""         # source name shown in Keyframe (shot · task · version)


class KeyframeOpen(BaseModel):
    project: str
    items: list[KeyframeItem]
    title: str = "FLUX"
    siblings: bool = True   # import the other videos of the same folder(s)


@router.get("/keyframe/status")
async def keyframe_status() -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, keyframe.status)


def _resolve(project_root: Path, item: KeyframeItem) -> dict:
    raw = item.path or ""
    if not raw and item.rel_path:
        raw = str(project_root / item.rel_path.replace("\\", "/").lstrip("/"))
    path = Path(raw)
    if not raw or not is_subpath(path.resolve(), project_root.resolve()):
        return {"path": raw, "label": item.label, "outside": True}
    return {"path": str(path), "label": item.label}


@router.post("/keyframe/open")
async def keyframe_open(req: KeyframeOpen) -> dict:
    project_root = get_project_path(req.project)
    if not project_root.is_dir():
        raise HTTPException(status_code=404, detail="Projet introuvable")
    resolved = [_resolve(project_root, i) for i in req.items]
    outside = [r for r in resolved if r.get("outside")]
    items = [r for r in resolved if not r.get("outside")]
    log.info("Keyframe open '%s' (%s): %s", req.title, req.project, [r["path"] for r in resolved])
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: keyframe.open_media(items, req.title, req.siblings))
    except keyframe.KeyframeError as exc:
        # Expected failures (absent app, nothing playable, launch refused) are a
        # normal answer: the UI shows the message and offers its own fallback.
        log.warning("Keyframe open failed (%s): %s", exc.code, exc)
        result = {"mode": "none", "code": exc.code, "message": str(exc), "opened": [], "skipped": []}
    result["skipped"] = result.get("skipped", []) + [
        {"path": o["path"], "label": o.get("label", ""), "reason": "hors du projet"} for o in outside]
    return result
