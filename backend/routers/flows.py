# routers/flows.py — Flows v2 endpoints (01_ARCHITECTURE §14, ADR 0057 / 0058).
#
# Static routes are declared before /{name} so a flow can never shadow them
# (their names are reserved by flux_flows.model.RESERVED_NAMES).
# Reads are open to everyone; every mutation checks the TD / Team TD boxes of the
# local user first (flux_flows.rights, 01 §7: a guard, not security). Scope and
# project come from the query or the body; the user is the local config user.
# P2: runs (draft run, dry run, active version), run history, cancel, WS /flows/ws
# (01 §10). No validation gate yet (P4): the engine prechecks unknown nodes / events.

from __future__ import annotations

import asyncio
import socket
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from flux_flows import engine, events, locations, migrate_v1, patterns, resolver, rights, runs, store
from flux_flows.model import FlowSchemaError, parse_flow, to_document, v1_limit_issues
from flux_flows.store import FlowStoreError
from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeError

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


class PreviewBody(BaseModel):
    kind: str                           # resolve | pattern
    text: str = ""
    names: Optional[list[str]] = None   # pattern: names to filter
    variables: Optional[dict[str, Any]] = None  # resolve: ${name} values (flow variables, interface)
    path_field: bool = False            # resolve: $FLUX at the head is resolved
    scope: str = "team"
    project: Optional[str] = None


@router.post("/preview")
async def post_preview(body: PreviewBody) -> dict[str, Any]:
    """Live result of a token text or a pattern in the editor (01 §14). Never runs a node."""
    if body.kind == "pattern":
        try:
            return {"result": patterns.filter_names(body.text, body.names or []), "error": None}
        except patterns.PatternError as exc:
            return {"result": None, "error": exc.message, "code": patterns.ERROR_CODE}
    if body.kind != "resolve":
        raise HTTPException(status_code=400, detail={"message": f"kind inconnu `{body.kind}` (resolve, pattern)"})
    current = await asyncio.to_thread(rights.current_rights)
    project = body.project if body.scope == "project" else None
    context = await asyncio.to_thread(engine.base_context, current["user"], project, "preview", "preview")
    variables = body.variables or {}
    try:
        result = resolver.resolve(body.text, context, variables.__getitem__, list(variables),
                                  path_field=body.path_field)
    except NodeError as exc:
        return {"result": None, "error": exc.message, "code": exc.code, **exc.details}
    return {"result": result, "error": None}


# -- runs (static, before /{name})---------------------------------------------

def _run_folders(user: Optional[str], project: Optional[str]) -> list:
    folders = [runs.runs_dir("team"), runs.runs_dir("perso", user=user)]
    if project:
        folders.append(runs.runs_dir("project", project=project))
    return folders


def _matches(rec: dict[str, Any], **wanted: Optional[str]) -> bool:
    return all(value is None or rec.get(key) == value for key, value in wanted.items())


@router.get("/runs")
async def list_runs(flow: Optional[str] = None, scope: Optional[str] = None, project: Optional[str] = None,
                    status: Optional[str] = None, mode: Optional[str] = None,
                    limit: int = 50) -> list[dict[str, Any]]:
    """Run summaries, newest first: records on disk plus this backend's live and recent runs."""
    current = await asyncio.to_thread(rights.current_rights)
    limit = max(1, min(limit, 500))
    try:
        listed = await asyncio.to_thread(runs.list_runs, _run_folders(current["user"], project), flow=flow,
                                         status=status, mode=mode, scope=scope, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    mgr = engine.manager()
    by_id = {r["run_id"]: r for r in listed}
    # Memory wins: a live run is fresher than its last write; a run without folder is only here.
    for rec in [mgr.get(i) for i in list(mgr.live)] + list(mgr.finished.values()):
        if rec and _matches(rec, flow=flow, status=status, mode=mode, scope=scope):
            by_id[rec["run_id"]] = runs.summary(rec)
    return sorted(by_id.values(), key=lambda r: r["run_id"], reverse=True)[:limit]


async def _find_run(run_id: str, project: Optional[str]) -> dict[str, Any]:
    record = engine.manager().get(run_id)
    if record is None:
        current = await asyncio.to_thread(rights.current_rights)
        record = await asyncio.to_thread(runs.find_run, _run_folders(current["user"], project), run_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"message": f"run {run_id} introuvable"})
    return record


@router.get("/runs/{run_id}")
async def get_run(run_id: str, project: Optional[str] = None) -> dict[str, Any]:
    """Full record (nodes, links, logs, report): the truth after a WS reconnection."""
    return await _find_run(run_id, project)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, project: Optional[str] = None) -> dict[str, Any]:
    """Cancel a run of this backend: TD box, or the artist who launched it."""
    record = await _find_run(run_id, project)
    current = await asyncio.to_thread(rights.current_rights)
    if not current.get("td") and record.get("user") != current.get("user"):
        raise _http(rights.FlowRightsError("td"))
    status = engine.manager().cancel(run_id)
    if status is None:
        raise HTTPException(status_code=409, detail={"message": "run termine ou lance sur un autre poste",
                                                     "status": record.get("status")})
    return {"status": status}


@router.websocket("/ws")
async def flows_websocket(websocket: WebSocket) -> None:
    """Live run messages (01 §10). Client -> server: {"type": "subscribe", "run_id"?, "flow"?}."""
    await websocket.accept()
    sub = events.subscribe()

    async def reader() -> None:
        while True:
            msg = await websocket.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "subscribe":
                sub.set_filter(msg.get("run_id"), msg.get("flow"))

    read_task = asyncio.create_task(reader())
    try:
        await websocket.send_json({"type": "hello", "holder": None, "me": socket.gethostname(),
                                   "running": engine.manager().running()})
        while True:
            get_task = asyncio.create_task(sub.get())
            done, _ = await asyncio.wait({get_task, read_task}, return_when=asyncio.FIRST_COMPLETED)
            if get_task not in done:   # the client left
                get_task.cancel()
                break
            await websocket.send_json(get_task.result())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        read_task.cancel()
        events.unsubscribe(sub)


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


class RunBody(BaseModel):
    scope: Optional[str] = None
    project: Optional[str] = None
    event: Optional[str] = None               # start event id; None = the first manual / button
    values: dict[str, Any] = {}               # interface values (payload of the event)
    dry_run: bool = False                     # on the saved file, never on a draft (01 §5)
    draft: Optional[dict[str, Any]] = None    # editor document: runs without creating a version (A7)
    base_revision: Optional[int] = None       # revision the draft was loaded from (kept in the record)


@router.post("/{name}/run")
async def run(name: str, body: RunBody) -> dict[str, Any]:
    """Draft run (editor, TD), dry run (saved file, TD) or run of the active version (everyone).
    409 when the run is refused (errors), skipped (run_policy) or the flow is not active."""
    current = await asyncio.to_thread(rights.current_rights)
    roots = _roots(current["user"], body.project)
    scope = body.scope or await _call(store.resolve, roots, name)
    if scope is None:
        raise HTTPException(status_code=404, detail={"message": f"flow {name} introuvable"})
    version, draft, base_revision, mode = None, False, body.base_revision, "real"
    if body.draft is not None:
        if body.dry_run:
            raise HTTPException(status_code=400, detail={
                "message": "L'essai a blanc tourne sur le fichier enregistre : enregistre d'abord (Ctrl+S)"})
        await _require(rights.DRAFT, scope)
        flow, draft = _parse(body.draft, name), True
    elif body.dry_run:
        await _require(rights.DRAFT, scope)
        got = await _call(store.read_flow, roots, scope, name)
        flow, mode, base_revision = got["flow"], "dry", got["state"].get("revision")
    else:
        state = (await _call(store.read_flow, roots, scope, name))["state"]
        if not state.get("active") or not state.get("active_version"):
            raise HTTPException(status_code=409, detail={"message": "flow non actif"})
        version = state["active_version"]
        flow = (await _call(store.read_flow, roots, scope, name, version))["flow"]
    folder = runs.runs_dir(scope, project=body.project, user=current["user"])
    new_run = engine.Run(flow, scope=scope, project=body.project, user=current["user"], mode=mode,
                         draft=draft, version=version, base_revision=base_revision, event=body.event,
                         values=body.values, folder=folder)
    record = await engine.manager().submit(new_run)
    if record["status"] in ("refused", "skipped"):
        raise HTTPException(status_code=409, detail={
            "message": record["error"], "run_id": record["run_id"], "status": record["status"],
            "issues": record["issues"]})
    return {"run_id": record["run_id"], "status": record["status"], "mode": mode}
