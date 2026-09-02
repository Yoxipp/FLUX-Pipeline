# routers/publish.py — publish pipeline endpoints.

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.logger import get_logger
from core.paths import get_project_path
from features.publisher.publish_core import publish_file

log = get_logger(__name__)
router = APIRouter()


class PublishRequest(BaseModel):
    source_path: str          # absolute path to the file to publish
    project_name: str
    description: str = ""
    user: str | None = None   # defaults to current user
    target_name: str | None = None  # composed FLUX name when the source isn't token-named


class PublishResult(BaseModel):
    success: bool
    dest_path: str | None
    message: str


@router.post("", response_model=PublishResult)
async def publish(req: PublishRequest) -> PublishResult:
    """Publish a file into the pipeline folder structure."""
    user = req.user or config.get_current_user() or "unknown"
    source = Path(req.source_path)

    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Fichier source introuvable : {source}")

    project_path = get_project_path(req.project_name)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {req.project_name}")

    loop = asyncio.get_event_loop()
    dest = await loop.run_in_executor(
        None,
        lambda: publish_file(source, project_path, req.description, user, req.project_name, req.target_name),
    )

    if dest is None:
        return PublishResult(success=False, dest_path=None, message="Publish échoué, voir les logs")
    return PublishResult(success=True, dest_path=str(dest), message="Publish réussi")
