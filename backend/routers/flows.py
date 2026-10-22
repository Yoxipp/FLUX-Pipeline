# routers/flows.py — Flows v2 endpoints (01_ARCHITECTURE §14, ADR 0057 / 0058).
#
# Static routes are declared before /{name} so a flow can never shadow them
# (their names are reserved by flux_flows.model.RESERVED_NAMES).

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from flux_flows import locations, migrate_v1, rights
from flux_flows.store import FlowStoreError
from flux_flows.nodes import registry

router = APIRouter()


def _http(exc: FlowStoreError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"message": str(exc), **exc.detail})


async def _require(action: str, scope: str) -> dict[str, Any]:
    """Rights of the local user, 403 without the box (a guard, not security)."""
    current = await asyncio.to_thread(rights.current_rights)
    try:
        rights.check(current, action, scope)
    except FlowStoreError as exc:
        raise _http(exc) from exc
    return current


@router.get("/catalog")
async def get_catalog() -> dict[str, Any]:
    """Node types, families, port types and the team node files that failed to load."""
    return await asyncio.to_thread(registry.catalog, locations.team_nodes_dir())


@router.get("/rights")
async def get_rights() -> dict[str, Any]:
    """TD / Team TD boxes of the current user and what they allow (01 §7). A guard, not security."""
    return rights.summary(await asyncio.to_thread(rights.current_rights))


class MigrateBody(BaseModel):
    dry_run: bool = True


@router.post("/migrate")
async def post_migrate(body: MigrateBody) -> dict[str, Any]:
    """v1 team actions -> team flows (01 §15). dry_run = report only; originals untouched."""
    current = await _require(rights.ADMIN, "team")
    try:
        return await asyncio.to_thread(migrate_v1.migrate_team_config, user=current["user"] or "", dry_run=body.dry_run)
    except FlowStoreError as exc:
        raise _http(exc) from exc
