# routers/flows.py — Flows v2 endpoints (01_ARCHITECTURE §14, ADR 0057 / 0058).
#
# Static routes are declared before /{name} so a flow can never shadow them
# (their names are reserved by flux_flows.model.RESERVED_NAMES).
# Reads are open to everyone; every mutation checks the TD / Team TD boxes of the
# local user first (flux_flows.rights, 01 §7: a guard, not security). Scope and
# project come from the query or the body; the user is the local config user.
# P1: no WS push (flow_changed arrives with P2), no validation gate (P4).

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from flux_flows import locations, migrate_v1, rights, store
from flux_flows.model import FlowSchemaError, parse_flow, to_document, v1_limit_issues
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
    except ValueError as exc:   # FlowRightsError, or an unknown scope
        if isinstance(exc, FlowStoreError):
            raise _http(exc) from exc
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
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


# -- CRUD (after every static route) ------------------------------------------

def _roots(user: Optional[str], project: Optional[str]) -> dict:
    try:
        return locations.roots_for(user=user, project=project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


def _category(scope: str) -> str:
    # ADR 0058: Ouvrir lists Pipe (shipped + team), Projet, Perso (TDs).
    return {"shipped": "pipe", "team": "pipe", "project": "project", "perso": "perso"}[scope]


async def _call(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except FlowStoreError as exc:
        raise _http(exc) from exc
    except FlowSchemaError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc)}) from exc


def _parse(doc: dict[str, Any], name: str):
    try:
        flow = parse_flow(doc)
    except FlowSchemaError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc)}) from exc
    if flow.name != name:
        raise HTTPException(status_code=400, detail={"message": "le nom du flow ne correspond pas a l'adresse"})
    return flow


class SaveBody(BaseModel):
    flow: dict[str, Any]
    scope: str
    project: Optional[str] = None
    base_revision: Optional[int] = None   # None = new flow (Nouveau, Enregistrer sous)
    force: bool = False                   # overwrite after a 409
    note: str = ""


class IncrementBody(BaseModel):
    flow: Optional[dict[str, Any]] = None   # None = freeze the working file as is
    scope: str
    project: Optional[str] = None
    base_revision: Optional[int] = None
    force: bool = False
    note: str = ""


class ScopeBody(BaseModel):
    scope: str
    project: Optional[str] = None


class RevertBody(ScopeBody):
    to_version: int


class CopyBody(BaseModel):
    from_scope: str
    to_scope: str
    project: Optional[str] = None
    new_name: Optional[str] = None


@router.get("")
async def list_flows(project: Optional[str] = None) -> list[dict[str, Any]]:
    """Every flow of every available scope, with its Ouvrir category."""
    current = await asyncio.to_thread(rights.current_rights)
    entries = await _call(store.list_flows, _roots(current["user"], project))
    return [{**e, "category": _category(e["scope"])} for e in entries]


@router.get("/{name}")
async def get_flow(name: str, scope: Optional[str] = None, project: Optional[str] = None,
                   version: Optional[int] = None) -> dict[str, Any]:
    """Working file (or frozen *version*) of *name*; without scope, the winning one."""
    current = await asyncio.to_thread(rights.current_rights)
    roots = _roots(current["user"], project)
    if scope is None:
        scope = await _call(store.resolve, roots, name)
        if scope is None:
            raise HTTPException(status_code=404, detail={"message": f"flow {name} introuvable"})
    got = await _call(store.read_flow, roots, scope, name, version)
    flow = got["flow"]
    return {"scope": scope, "category": _category(scope), "name": name, "version": version,
            "flow": to_document(flow), "state": got["state"], "legacy": name.startswith(store.LEGACY_PREFIX),
            "issues": v1_limit_issues(flow)}


@router.get("/{name}/versions")
async def get_versions(name: str, scope: str, project: Optional[str] = None) -> dict[str, Any]:
    current = await asyncio.to_thread(rights.current_rights)
    return await _call(store.list_versions, _roots(current["user"], project), scope, name)


@router.put("/{name}")
async def save(name: str, body: SaveBody) -> dict[str, Any]:
    """Enregistrer: overwrite the working file (409 on a revision conflict)."""
    current = await _require(rights.WRITE, body.scope)
    flow = _parse(body.flow, name)
    state = await _call(store.save_flow, _roots(current["user"], body.project), body.scope, flow,
                        user=current["user"] or "", base_revision=body.base_revision, force=body.force,
                        note=body.note)
    return {"state": state, "issues": v1_limit_issues(flow)}


@router.post("/{name}/increment")
async def increment(name: str, body: IncrementBody) -> dict[str, Any]:
    """Enregistrer et incrementer: optional save, then a frozen version if the content changed."""
    current = await _require(rights.WRITE, body.scope)
    flow = _parse(body.flow, name) if body.flow is not None else None
    return await _call(store.increment_flow, _roots(current["user"], body.project), body.scope, name,
                       user=current["user"] or "", flow=flow, base_revision=body.base_revision,
                       force=body.force, note=body.note)


@router.post("/{name}/revert")
async def revert(name: str, body: RevertBody) -> dict[str, Any]:
    current = await _require(rights.WRITE, body.scope)
    return await _call(store.revert_flow, _roots(current["user"], body.project), body.scope, name,
                       body.to_version, user=current["user"] or "")


@router.post("/{name}/activate")
async def activate(name: str, body: ScopeBody) -> dict[str, Any]:
    """Refused for legacy_* flows (the publish runs on v1 until P8) and without a frozen version."""
    current = await _require(rights.WRITE, body.scope)
    return await _call(store.set_active, _roots(current["user"], body.project), body.scope, name, True,
                       user=current["user"] or "")


@router.post("/{name}/deactivate")
async def deactivate(name: str, body: ScopeBody) -> dict[str, Any]:
    current = await _require(rights.WRITE, body.scope)
    return await _call(store.set_active, _roots(current["user"], body.project), body.scope, name, False,
                       user=current["user"] or "")


@router.post("/{name}/copy")
async def copy(name: str, body: CopyBody) -> dict[str, Any]:
    """Enregistrer sous to another scope / name, or unlock a shipped flow (copy to team, Team TD)."""
    action = rights.ADMIN if body.from_scope == "shipped" and body.to_scope == "team" else rights.WRITE
    current = await _require(action, body.to_scope)
    return await _call(store.copy_flow, _roots(current["user"], body.project), name, body.from_scope,
                       body.to_scope, user=current["user"] or "", new_name=body.new_name)


@router.delete("/{name}")
async def delete(name: str, scope: str, project: Optional[str] = None) -> dict[str, Any]:
    """To <scope>/_trash/; on a team copy of a shipped flow = Revenir au defaut."""
    current = await _require(rights.WRITE, scope)
    return await _call(store.delete_flow, _roots(current["user"], project), scope, name,
                       user=current["user"] or "")
