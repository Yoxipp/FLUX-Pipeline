# routers/actions.py — declarative action engine endpoints (Phase 2).
#
# The front renders a generic form from an action's parameters instead of
# hardcoding one form per feature. Two read-only endpoints back that:
#   GET  /actions/publish/form     -> the fields to render
#   POST /actions/publish/preview  -> the resolved destination (no copy)
#
# This router is additive. The legacy /publish path stays the default; nothing
# here writes to disk.

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.logger import get_logger
from core.paths import get_project_path

from flux_actions import build_publish_form, preview_publish_action

log = get_logger(__name__)
router = APIRouter()


class FormResponse(BaseModel):
    action: str
    fields: list[dict[str, Any]]


@router.get("/publish/form", response_model=FormResponse)
async def publish_form() -> FormResponse:
    """Return the user-facing fields of the publish action, in run order."""
    return FormResponse(action="publish", fields=build_publish_form())


class PreviewRequest(BaseModel):
    source_path: str
    project_name: str
    user: str | None = None
    target_name: str | None = None


class PreviewResponse(BaseModel):
    resolved: bool
    dest_path: str | None
    message: str


@router.post("/publish/preview", response_model=PreviewResponse)
async def publish_preview(req: PreviewRequest) -> PreviewResponse:
    """Resolve where a publish would land, without copying anything."""
    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    user = req.user or config.get_current_user() or "unknown"

    # preview_publish_action drives the engine with asyncio.run internally, so it
    # must run off the request's event loop, in a worker thread.
    loop = asyncio.get_event_loop()
    dest = await loop.run_in_executor(
        None,
        lambda: preview_publish_action(
            source_path=req.source_path,
            project_path=project_path,
            user=user,
            project_name=req.project_name,
            target_name=req.target_name,
            logger=log,
        ),
    )

    if dest is None:
        return PreviewResponse(
            resolved=False,
            dest_path=None,
            message="Destination non résolue, vérifie le nom du fichier",
        )
    return PreviewResponse(resolved=True, dest_path=str(dest), message="Destination résolue")
