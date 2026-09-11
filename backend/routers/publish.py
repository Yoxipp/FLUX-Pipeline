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
    # Populated only when texture conform is enabled and the file was a texture.
    tx_paths: list[str] | None = None
    # Populated only when USD proxy is enabled and the file was a USD asset.
    proxy_path: str | None = None


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

    # Engine path (default; FLUX_LEGACY_PUBLISH falls back to legacy). Same UI,
    # same endpoint, same response shape. The runner runs publish.yml, which
    # resolves then reuses copy_publish, so both paths land the file identically.
    from flux_actions.switch import engine_publish_enabled

    if engine_publish_enabled("local"):
        from flux_actions.runner import run_publish_action

        dest = await loop.run_in_executor(
            None,
            lambda: run_publish_action(
                source, project_path, req.description, user, req.project_name, req.target_name
            ),
        )
    else:
        dest = await loop.run_in_executor(
            None,
            lambda: publish_file(source, project_path, req.description, user, req.project_name, req.target_name),
        )

    if dest is None:
        return PublishResult(success=False, dest_path=None, message="Publish échoué, voir les logs")

    # Post-publish optimisation hooks (both opt-in, both best-effort: a failure
    # here never fails the publish itself).
    #   texture -> mipped/tiled .tx so Karma stops re-mipmapping at render time.
    #   USD asset -> decimated purpose=proxy geometry for lighter viewports.
    tx_paths = await _maybe_conform_texture(Path(dest), loop)
    proxy_path = await _maybe_generate_proxy(Path(dest), loop)

    return PublishResult(
        success=True, dest_path=str(dest), message="Publish réussi",
        tx_paths=tx_paths, proxy_path=proxy_path,
    )


async def _maybe_conform_texture(dest: Path, loop) -> list[str] | None:
    """Conform the just-published file to .tx when the opt-in flag is on.

    Returns the .tx paths, or None when conform is off / the file is not a
    texture / conform failed (the publish already succeeded either way).
    """
    from flux_actions.switch import conform_tx_colorconvert, conform_tx_enabled
    from features.publisher.texture_conform import is_texture_source

    if not conform_tx_enabled() or not is_texture_source(dest):
        return None
    try:
        from flux_actions.runner import run_conform_texture_action

        result = await loop.run_in_executor(
            None,
            lambda: run_conform_texture_action(
                dest, out_dir=dest.parent, colorconvert=conform_tx_colorconvert()
            ),
        )
    except Exception:  # noqa: BLE001 - conform must never break a publish
        log.exception("Texture conform .tx a échoué pour %s", dest)
        return None
    if not result:
        log.warning("Texture conform .tx sans résultat pour %s", dest)
        return None
    tx_paths = result.get("tx_paths") or None
    log.info("Texture conform .tx: %s -> %s", dest.name, tx_paths)
    return tx_paths


async def _maybe_generate_proxy(dest: Path, loop) -> str | None:
    """Author a USD purpose=proxy layer when the opt-in flag is on.

    Returns the proxy layer path, or None when proxy is off / the file is not a
    USD asset / it has no render mesh / generation failed (the publish already
    succeeded either way).
    """
    from flux_actions.switch import proxy_usd_enabled, proxy_usd_reduction
    from features.publisher.usd_proxy import is_usd_asset

    if not proxy_usd_enabled() or not is_usd_asset(dest):
        return None
    try:
        from flux_actions.runner import run_generate_proxy_action

        result = await loop.run_in_executor(
            None,
            lambda: run_generate_proxy_action(
                dest, target_reduction=proxy_usd_reduction()
            ),
        )
    except Exception:  # noqa: BLE001 - proxy must never break a publish
        log.exception("USD proxy a échoué pour %s", dest)
        return None
    if not result or result.get("status") != "converted":
        # No render mesh, or nothing to do: not an error worth surfacing.
        return None
    proxy_path = result.get("proxy_path")
    log.info("USD proxy: %s -> %s (%s tris -> %s)",
             dest.name, proxy_path, result.get("tris_in"), result.get("tris_out"))
    return proxy_path
