# routers/publish.py — publish pipeline endpoints.

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.executors import HEAVY
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
    tx_only: bool = False     # texture: publish its .tx instead of the image (lighter)


class PublishResult(BaseModel):
    success: bool
    dest_path: str | None
    message: str
    # Populated only when texture conform is enabled and the file was a texture.
    tx_paths: list[str] | None = None
    # Populated only when USD proxy is enabled and the file was a USD asset.
    proxy_path: str | None = None


@router.get("/destination")
def publish_destination(project: str, base: str, ext: str, sequence: bool = False) -> dict:
    """Read-only preview of the folder a publish of *base* + *ext* lands in."""
    from features.publisher.destination_preview import destination_preview

    project_path = get_project_path(project)
    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Projet introuvable : {project}")
    info = destination_preview(project_path, base, ext, sequence)
    if info is None:
        raise HTTPException(status_code=422, detail="Destination non résolue")
    return info


@router.get("/queue")
def publish_queue() -> dict:
    """Publish copies running / waiting in this backend (copy_limits caps)."""
    from features.publisher import copy_limits

    return copy_limits.status()


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

    loop = asyncio.get_running_loop()

    # "Only .tx": convert first, then publish the .tx itself (see convert_to_tx for
    # why the image is never published then deleted).
    tx_only_done = False
    if req.tx_only:
        source, target_name, tx_only_done = await loop.run_in_executor(
            None, lambda: _source_as_tx(source, req.target_name))
        req.target_name = target_name

    # Engine path (default; FLUX_LEGACY_PUBLISH falls back to legacy). Same UI,
    # same endpoint, same response shape. The runner runs publish.yml, which
    # resolves then reuses copy_publish, so both paths land the file identically.
    from flux_actions.switch import engine_publish_enabled

    if engine_publish_enabled("local"):
        from flux_actions.runner import run_publish_action

        dest = await loop.run_in_executor(
            HEAVY,
            lambda: run_publish_action(
                source, project_path, req.description, user, req.project_name, req.target_name
            ),
        )
    else:
        dest = await loop.run_in_executor(
            HEAVY,
            lambda: publish_file(source, project_path, req.description, user, req.project_name, req.target_name),
        )

    if dest is None:
        return PublishResult(success=False, dest_path=None,
                             message=_failure_reason(source, project_path, req.target_name))

    # Post-publish optimisation hooks (both opt-in, both best-effort: a failure
    # here never fails the publish itself).
    #   texture -> mipped/tiled .tx so Karma stops re-mipmapping at render time.
    #   USD asset -> decimated purpose=proxy geometry for lighter viewports.
    tx_paths = [str(dest)] if tx_only_done else await _maybe_conform_texture(Path(dest), loop)
    proxy_path = await _maybe_generate_proxy(Path(dest), loop)

    return PublishResult(
        success=True, dest_path=str(dest), message="Publish réussi",
        tx_paths=tx_paths, proxy_path=proxy_path,
    )


def _source_as_tx(source: Path, target_name: str | None) -> tuple[Path, str | None, bool]:
    """(file to publish, target name, converted) for an "only .tx" publish.

    A non-texture or a failed conform keeps the source as is. A target name carrying
    the image extension gets ".tx" instead, so the publish is named after the .tx.
    """
    from dcc.texture_publish import convert_to_tx
    from features.publisher.texture_conform import is_texture_source

    if not is_texture_source(source):
        return source, target_name, False
    files, _warnings = convert_to_tx([source], "Publish")
    tx = files[0]
    if tx.suffix.lower() != ".tx":
        return source, target_name, False
    if target_name and Path(target_name).suffix.lower() == source.suffix.lower():
        target_name = str(Path(target_name).with_suffix(".tx"))
    return tx, target_name, True


def _failure_reason(source: Path, project_path: Path, target_name: str | None) -> str:
    """Readable reason of a failed publish for the UI toast: an unresolved destination
    (unknown task token...) is named; anything else points to the logs."""
    from features.publisher.publish_core import (
        explain_unresolved_publish, resolve_publish_filename, resolve_publish_path,
    )
    try:
        filename = resolve_publish_filename(source, target_name)
        if resolve_publish_path(project_path, filename) is None:
            return explain_unresolved_publish(project_path, filename)
    except Exception:  # noqa: BLE001 - the reason is best-effort, never a second error
        log.exception("Cannot explain failed publish of %s", source)
    return "Publish échoué, voir les logs"


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
    """Proxy layer of this publish (purpose=proxy), or None when the flag is off.

    Authored beside the IMMUTABLE version, never beside LAST (ADR 0019): the asset
    references the proxy layer, and a LAST pointer must stay a pointer. The publish
    hook (features/publisher/usd_publish_hooks) usually wrote it already, in which
    case this only reports its path back to the UI.
    """
    from features.publisher import last_pointer as lp
    from features.publisher.usd_proxy import is_usd_asset
    from features.publisher.usd_publish_hooks import generate_proxy_layer, proxy_sibling
    from flux_actions.switch import proxy_usd_enabled

    dest = Path(dest)
    if not proxy_usd_enabled() or not is_usd_asset(dest):
        return None
    # A LAST pointer layer is not a source: follow it to the version it targets.
    source = dest
    stem, ext, _role = lp.parse_published_name(dest.name)
    info = await loop.run_in_executor(
        None, lambda: lp.read_last(dest.parent, stem.rsplit("_", 1)[0], ext))
    if info and info.get("target"):
        target = dest.parent / str(info["target"])
        if target.is_file():
            source = target
    existing = proxy_sibling(source)
    if existing.is_file():
        return str(existing)
    return await loop.run_in_executor(None, lambda: generate_proxy_layer(source))
