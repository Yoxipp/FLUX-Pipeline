# routers/flows.py — Flows v2 endpoints (01_ARCHITECTURE §14, ADR 0057 / 0058).
#
# Static routes are declared before /{name} so a flow can never shadow them
# (their names are reserved by flux_flows.model.RESERVED_NAMES).

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from flux_flows import locations
from flux_flows.nodes import registry

router = APIRouter()


@router.get("/catalog")
async def get_catalog() -> dict[str, Any]:
    """Node types, families, port types and the team node files that failed to load."""
    return await asyncio.to_thread(registry.catalog, locations.team_nodes_dir())
