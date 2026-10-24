# routers/flows.py — Flows v2 endpoints (01_ARCHITECTURE §14, ADR 0057 / 0058).
#
# Static routes are declared before /{name} so a flow can never shadow them
# (their names are reserved by flux_flows.model.RESERVED_NAMES).
# Reads are open to everyone; every mutation checks the TD / Team TD boxes of the
# local user first (flux_flows.rights, 01 §7: a guard, not security). Scope and
# project come from the query or the body; the user is the local config user.
# P2: runs (draft run, dry run, active version), run history, cancel, WS /flows/ws
# (01 §10). P4: POST /flows/validate (flux_flows.validate is the truth); a save keeps
# ``valid`` in state.json (saving with errors is allowed); PUT / increment refuse a
# destructive node added without being in ``confirmed_destructive`` (409,
# E_DESTRUCTIVE_UNCONFIRMED); activation refuses a frozen version with errors; the
# engine refuses a run with errors (a type mismatch only blocks real runs, ADR 0058).
# P5: GET /flows/host (who runs the shared active flows), POST /flows/events/{kind}
# (scene_opened sent by a script in the DCC), activation gate (0 error, warnings
# acknowledged, dry run passed on the frozen version: GET /{name}/activation), WS
# ``host``, ``activation`` and ``flow_changed``; a dry run of version `current` that ends
# ``ok`` writes state.json ``dry_run_ok``.
# P6c: GET /flows/bridges (extension bridges + install state), POST
# /flows/bridges/{soft}/install | uninstall (this machine, never a silent overwrite),
# POST /flows/bridges/{soft}/flows (Team TD: its Instance and publish nodes in the team scope).

from __future__ import annotations

import asyncio
import re
import socket
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from flux_flows import (engine, events, locations, migrate_v1, page_data, page_inputs, page_links, page_store, pages,
                        patterns,
                        resolver, rights, runs, scheduler, store, validate)
from flux_flows.model import Flow, FlowSchemaError, parse_flow, to_document, v1_limit_issues
from flux_flows.store import FlowStoreError
from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeError

router = APIRouter()
TEAM_NODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


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


@router.get("/nodes/template")
async def get_node_template() -> dict[str, Any]:
    """The team node template to copy into CONFIG/extensions/nodes/ (reloaded per file, no restart)."""
    path = locations.shipped_dir() / "team_node_template.py"
    folder = locations.team_nodes_dir()
    return {"filename": path.name, "text": await asyncio.to_thread(path.read_text, encoding="utf-8"),
            "folder": str(folder) if folder else None}


class TeamNodeBody(BaseModel):
    name: str        # file name without .py
    code: str


@router.post("/nodes")
async def post_team_node(body: TeamNodeBody) -> dict[str, Any]:
    """Write a team Python node (NodeWriterDialog, P4): CONFIG/extensions/nodes/<name>.py,
    Team TD. The file is written even when it fails to load (the next save fixes it);
    ``error`` = the load error of this file, None when its nodes are in the catalogue."""
    await _require(rights.ADMIN, "team")
    if not TEAM_NODE_RE.match(body.name):
        raise HTTPException(status_code=400, detail={"message": "nom invalide : minuscules, chiffres, _ (2 a 41)"})
    if registry.MARKER not in body.code:
        raise HTTPException(status_code=400, detail={"message": f"le fichier doit contenir {registry.MARKER}"})
    folder = locations.team_nodes_dir()
    if folder is None:
        raise HTTPException(status_code=409, detail={"message": "FLUX_ROOT inconnu : pas de dossier des nodes d'equipe"})
    path = folder / f"{body.name}.py"

    def work() -> Optional[str]:
        store._write_text(path, body.code)
        errors = registry.catalog(folder)["node_errors"]
        return next((e["error"] for e in errors if e.get("file") == path.name), None)

    return {"file": str(path), "error": await asyncio.to_thread(work)}


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


# -- host and events (static, before /{name}) ------------------------------------------

@router.get("/host")
async def get_host() -> dict[str, Any]:
    """Who runs the shared active flows (host lock, 01 §9) and what this backend watches."""
    sched = scheduler.get()
    if sched is None:
        return {"enabled": scheduler.enabled(), "running": False, "holder": None, "me": socket.gethostname(),
                "is_holder": False, "since": None, "idle_reason": "planificateur arrete", "active_flows": [],
                "watchers": [], "over_cap": [], "max_watchers": scheduler.MAX_WATCHERS}
    return sched.info()


class EventBody(BaseModel):
    soft: str = "maya"
    scene: str = ""
    port: Optional[int] = None
    pid: Optional[int] = None


@router.post("/events/{kind}")
async def post_event(kind: str, body: EventBody) -> dict[str, Any]:
    """A local event sent by a script in the DCC (proposition of 01 §9): only scene_opened.
    Starts the active flows of this backend whose SceneOpened node matches the soft."""
    if kind != "scene_opened":
        raise HTTPException(status_code=400, detail={"message": f"evenement `{kind}` inconnu (scene_opened)"})
    if body.soft not in scheduler.SCENE_SOFTS:
        raise HTTPException(status_code=400, detail={"message": "soft : maya, houdini ou nuke"})
    sched = scheduler.get()
    if sched is None:
        raise HTTPException(status_code=409, detail={"message": "planificateur des flows arrete sur ce poste"})
    session = {"soft": body.soft, "port": body.port, "pid": body.pid}
    started = []
    for w in sched.scene_watchers(body.soft):
        rec = await sched.fire(w.af, w.node, {"scene": body.scene, "soft": body.soft, "session": session})
        started.append({"flow": w.af.name, "run_id": rec["run_id"], "status": rec["status"]})
    return {"started": started}


# -- validation (static, before /{name}) ------------------------------------------

def _validation_env(roots: dict, scope: str, name: str, project: Optional[str]) -> validate.Env:
    """Env of a flow of *scope*: its project, FlowCall loader, dry-run result, shipped copy."""
    def loader(other: str) -> Optional[Flow]:
        found = store.resolve(roots, other)
        return store.read_flow(roots, found, other)["flow"] if found else None

    state: dict[str, Any] = {}
    root = roots.get(scope)
    if root is not None and scope != "shipped":
        state = store.read_state(Path(root), name)
    done = state.get("dry_run_ok") or {}
    tested = done.get("nodes_simulated") if done.get("version") == state.get("current") else None
    return validate.default_env(project if scope == "project" else None, flow_loader=loader, tested=tested,
                                shipped_changed=store.shipped_changed(roots, scope, name),
                                page_links=_links_to(name, project),
                                page_lookup=lambda page_id: page_inputs.load_page(page_id, project))


def _links_to(name: str, project: Optional[str]) -> list[dict[str, Any]]:
    """Links of the TOOL pages to the flow *name* (W_PAGE_LINK_BROKEN, P7)."""
    try:
        return [l for l in page_links.all_links(locations.page_roots(project)) if l["flow"] == name]
    except (ValueError, OSError):
        return []


def _issues(roots: dict, scope: str, flow: Flow, project: Optional[str]) -> list[validate.Issue]:
    return validate.validate(flow, _validation_env(roots, scope, flow.name, project))


def _dicts(issues: list[validate.Issue]) -> list[dict[str, Any]]:
    return [i.to_dict() for i in issues]


class ValidateBody(BaseModel):
    flow: dict[str, Any]
    scope: str = "team"
    project: Optional[str] = None


@router.post("/validate")
async def post_validate(body: ValidateBody) -> dict[str, Any]:
    """Issues of an editor document (debounced by the editor). Never writes anything."""
    current = await asyncio.to_thread(rights.current_rights)
    roots = _roots(current["user"], body.project)

    def work() -> list[validate.Issue]:
        try:
            flow = parse_flow(body.flow)
        except FlowSchemaError:
            return validate.validate_document(body.flow)[1]
        return _issues(roots, body.scope, flow, body.project)

    issues = await asyncio.to_thread(work)
    return {"issues": _dicts(issues), "valid": not validate.errors(issues)}


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
                    status: Optional[str] = None, mode: Optional[str] = None, event: Optional[str] = None,
                    limit: int = 50) -> list[dict[str, Any]]:
    """Run summaries, newest first: records on disk plus this backend's live and recent runs."""
    current = await asyncio.to_thread(rights.current_rights)
    limit = max(1, min(limit, 500))
    try:
        listed = await asyncio.to_thread(runs.list_runs, _run_folders(current["user"], project), flow=flow,
                                         status=status, mode=mode, scope=scope, event=event, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    mgr = engine.manager()
    by_id = {r["run_id"]: r for r in listed}
    # Memory wins: a live run is fresher than its last write; a run without folder is only here.
    for rec in [mgr.get(i) for i in list(mgr.live)] + list(mgr.finished.values()):
        if rec and _matches(rec, flow=flow, status=status, mode=mode, scope=scope) \
                and (event is None or runs.trigger_matches(rec, event)):
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
        sched = scheduler.get()
        host = sched.info() if sched is not None else {"holder": None, "since": None}
        await websocket.send_json({"type": "hello", "holder": host.get("holder"), "me": socket.gethostname(),
                                   "since": host.get("since"), "running": engine.manager().running()})
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


# -- TOOL pages (04_PAGES_TOOL, ADR 0066) -------------------------------------
# Static, so declared before /{name}. Everyone reads and lists; creating, editing and
# deleting a page needs the Team TD box (rights.ADMIN, 01 §7). Running a page button
# is POST /flows/{flow}/run (everyone, active flow only).

def _page_roots(project: Optional[str]) -> dict:
    try:
        return locations.page_roots(project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc


def _parse_page(doc: dict[str, Any], page_id: Optional[str] = None) -> pages.Page:
    try:
        page = pages.parse_page(doc)
    except pages.PageSchemaError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc)}) from exc
    if page_id is not None and page.id != page_id:
        raise HTTPException(status_code=400, detail={"message": f"id {page.id} different de l'adresse {page_id}"})
    return page


def _page_issues(page: pages.Page, scope: Optional[str], user: Optional[str],
                 project: Optional[str]) -> list[dict[str, Any]]:
    lookup = page_store.flow_lookup(_roots(user, project))
    found = pages.validate_page(page, pages.PageEnv(scope=scope, flow_lookup=lookup))
    return [i.to_dict() for i in found]


@router.get("/pages")
async def list_pages(project: Optional[str] = None) -> dict[str, Any]:
    """Pages of team and project (TOOL), the shipped templates and whether the user may edit."""
    current = await asyncio.to_thread(rights.current_rights)
    roots = _page_roots(project)
    listed = await _call(page_store.list_pages, roots)
    templates = await _call(page_store.list_templates, roots)
    return {"pages": listed, "templates": templates,
            "can_edit": {scope: rights.allowed(current, rights.ADMIN, scope) for scope in pages.SCOPES}}


class PageValidateBody(BaseModel):
    page: dict[str, Any]
    scope: Optional[str] = None
    project: Optional[str] = None


@router.post("/pages/validate")
async def validate_page(body: PageValidateBody) -> dict[str, Any]:
    """P_* issues of a page being edited (debounced by the page editor, 04 §5)."""
    current = await asyncio.to_thread(rights.current_rights)
    page = _parse_page(body.page)
    issues = await asyncio.to_thread(_page_issues, page, body.scope, current["user"], body.project)
    return {"issues": issues}


@router.get("/pages/links")
async def get_page_links(project: Optional[str] = None) -> dict[str, Any]:
    """Reverse index {flow: [{page, scope, widget, kind, role, button_id | param | output}]} (04 §4)."""
    return await _call(page_links.index, _page_roots(project))


# -- InputsPageReader (ADR 0068): the flow picks its page ------------------------

@router.get("/pages/{page_id}/ports")
async def get_page_ports(page_id: str, project: Optional[str] = None) -> dict[str, Any]:
    """params.ports of an InputsPageReader node on this page (buttons, fields) and its defaults."""
    page = await _call(page_inputs.load_page, page_id, project)
    if page is None:
        raise HTTPException(status_code=404, detail={"message": f"page {page_id} introuvable"})
    return {**page_inputs.ports_of(page), "defaults": page_inputs.defaults_of(page), "label": page.label}


@router.get("/pages/{page_id}/flows")
async def get_page_flows(page_id: str, project: Optional[str] = None) -> dict[str, Any]:
    """Who uses this page: ``listeners`` {button: [active flows a click runs]} and ``uses``
    (every flow with an InputsPageReader on it, active or not)."""
    current = await asyncio.to_thread(rights.current_rights)
    roots = _roots(current["user"], project)
    return {"listeners": await _call(page_inputs.listeners, roots, page_id),
            "uses": await _call(page_inputs.uses, roots, page_id)}


class PageClickBody(BaseModel):
    button: str
    values: dict[str, Any] = {}
    project: Optional[str] = None


@router.post("/pages/{page_id}/click")
async def click_page(page_id: str, body: PageClickBody) -> dict[str, Any]:
    """A page button: every active flow listening to it runs its active version (409 when none)."""
    current = await asyncio.to_thread(rights.current_rights)
    roots = _roots(current["user"], body.project)
    targets = (await _call(page_inputs.listeners, roots, page_id)).get(body.button) or []
    if not targets:
        raise HTTPException(status_code=409, detail={
            "message": "Aucun flow actif ne reagit a ce bouton : un TD pose un InputsPageReader sur cette page, "
                       "relie le bouton et active le flow"})
    payload = {"page": page_id, "button": body.button, "values": body.values}
    out = []
    for t in targets:
        flow = (await _call(store.read_flow, roots, t["scope"], t["flow"], t["version"]))["flow"]
        folder = runs.runs_dir(t["scope"], project=body.project, user=current["user"])
        new_run = engine.Run(flow, scope=t["scope"], project=body.project, user=current["user"],
                             version=t["version"], event=t["node"], values=body.values, payload=payload,
                             folder=folder)
        record = await engine.manager().submit(new_run)
        out.append({"flow": t["flow"], "scope": t["scope"], "run_id": record["run_id"], "status": record["status"],
                    "error": record.get("error")})
    return {"runs": out}


@router.get("/pages/publish_panel/{soft}")
async def get_publish_panel(soft: str, project: Optional[str] = None) -> dict[str, Any]:
    """Generated Publisher panel of an extension software (04 §7): fields from the interface
    of its flow publish_<soft>, a Publier button (event publish_request), its issues."""
    from flux_flows.bridges import extension

    current = await asyncio.to_thread(rights.current_rights)

    def work() -> dict[str, Any]:
        ext = extension.get(soft)
        if ext is None or ext.manifest is None:
            raise FlowStoreError(f"logiciel d'extension {soft} inconnu", 404)
        lookup = page_store.flow_lookup(_roots(current["user"], project))
        page, issues = pages.generated_publish_page(soft, ext.manifest.label, lookup(pages.publish_flow_name(soft)))
        return {"soft": soft, "flow": pages.publish_flow_name(soft), "page": pages.to_document(page),
                "target": {"flow": pages.publish_flow_name(soft), "event": pages.PUBLISH_BUTTON},
                "issues": [i.to_dict() for i in issues]}

    return await _call(work)


@router.get("/pages/{page_id}")
async def get_page(page_id: str, scope: Optional[str] = None, project: Optional[str] = None) -> dict[str, Any]:
    """A page (without scope: the winning one, project > team; scope=shipped: a template)."""
    current = await asyncio.to_thread(rights.current_rights)
    roots = _page_roots(project)
    if scope is None:
        scope = await _call(page_store.resolve, roots, page_id)
        if scope is None:
            raise HTTPException(status_code=404, detail={"message": f"page {page_id} introuvable"})
    got = await _call(page_store.read_page, roots, scope, page_id)
    issues = await asyncio.to_thread(_page_issues, got["page"], scope, current["user"], project)
    return {"id": page_id, "scope": scope, "rev": got["rev"], "page": pages.to_document(got["page"]),
            "issues": issues, "can_edit": scope in pages.SCOPES and rights.allowed(current, rights.ADMIN, scope)}


class PageSaveBody(BaseModel):
    scope: str
    project: Optional[str] = None
    page: dict[str, Any]
    base_rev: Optional[str] = None    # rev read by the editor; None = a new page
    force: bool = False


@router.put("/pages/{page_id}")
async def save_page(page_id: str, body: PageSaveBody) -> dict[str, Any]:
    """Save a page (Team TD). Saving with errors is allowed: the page is shown invalid."""
    current = await _require(rights.ADMIN, body.scope if body.scope in pages.SCOPES else "team")
    page = _parse_page(body.page, page_id)
    roots = _page_roots(body.project)
    saved = await _call(page_store.save_page, roots, body.scope, page, user=current["user"] or "",
                        base_rev=body.base_rev, force=body.force)
    issues = await asyncio.to_thread(_page_issues, page, body.scope, current["user"], body.project)
    events.emit({"type": "page_changed", "page": page_id, "scope": body.scope, "project": body.project,
                 "rev": saved["rev"], "by": current["user"]})
    return {**saved, "issues": issues}


@router.delete("/pages/{page_id}")
async def delete_page(page_id: str, scope: str, project: Optional[str] = None) -> dict[str, Any]:
    current = await _require(rights.ADMIN, scope if scope in pages.SCOPES else "team")
    done = await _call(page_store.delete_page, _page_roots(project), scope, page_id, user=current["user"] or "")
    events.emit({"type": "page_changed", "page": page_id, "scope": scope, "project": project,
                 "rev": None, "by": current["user"]})
    return done


# -- page data (ADR 0066 n°3): one journal per author, merged on read ------------

def _page_and_spec(page_id: str, collection: str, project: Optional[str]):
    _page_roots(project)   # 400 on a bad project name
    folder, spec, _ = page_data.locate(page_id, collection, project)
    return folder, spec


@router.get("/pages/{page_id}/data/{collection}")
async def get_page_data(page_id: str, collection: str, project: Optional[str] = None,
                        etag: Optional[str] = None) -> dict[str, Any]:
    """Records of a collection; with the etag the reader has: {unchanged: true} when nothing moved."""
    def work() -> dict[str, Any]:
        folder, spec = _page_and_spec(page_id, collection, project)
        return {**page_data.read_records(folder, etag), "write": spec.write}

    return await _call(work)


class PageDataBody(BaseModel):
    project: Optional[str] = None
    ops: list[dict[str, Any]]


@router.post("/pages/{page_id}/data/{collection}")
async def post_page_data(page_id: str, collection: str, body: PageDataBody) -> dict[str, Any]:
    """put / del operations, appended to the journal of the local user (everyone, or Team TD
    when the collection says write: team_td)."""
    current = await asyncio.to_thread(rights.current_rights)

    def work() -> dict[str, Any]:
        folder, spec = _page_and_spec(page_id, collection, body.project)
        if not page_data.can_write(spec, current):
            raise rights.FlowRightsError("team_td")
        return page_data.write_ops(folder, spec, body.ops, user=current["user"] or "")

    done = await _call(work)
    events.emit({"type": "page_data", "page": page_id, "collection": collection, "project": body.project,
                 "etag": done["etag"], "by": current["user"]})
    return done


class PageMediaBody(BaseModel):
    project: Optional[str] = None
    path: str                       # a local file the user picked (copied, never uploaded: ADR 0005)


@router.post("/pages/{page_id}/data/{collection}/media")
async def post_page_media(page_id: str, collection: str, body: PageMediaBody) -> dict[str, Any]:
    current = await asyncio.to_thread(rights.current_rights)

    def work() -> dict[str, Any]:
        folder, spec = _page_and_spec(page_id, collection, body.project)
        if not page_data.can_write(spec, current):
            raise rights.FlowRightsError("team_td")
        return {"image": page_data.add_image(folder, body.path)}

    return await _call(work)


@router.get("/pages/{page_id}/data/{collection}/media/{name}")
async def get_page_media(page_id: str, collection: str, name: str, project: Optional[str] = None):
    """An image of a collection, for <img src> (display only, like production/ref)."""
    from fastapi.responses import FileResponse

    def work() -> Path:
        folder, _ = _page_and_spec(page_id, collection, project)
        return page_data.media_file(folder, name)

    path = await _call(work)
    return FileResponse(path, media_type=page_data.media_type(name))


@router.get("/pages/{page_id}/history")
async def get_page_history(page_id: str, scope: str, project: Optional[str] = None) -> list[dict[str, Any]]:
    return await _call(page_store.list_history, _page_roots(project), scope, page_id)


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
    confirmed_destructive: list[str] = [] # `!` nodes the user confirmed with the slider


class IncrementBody(BaseModel):
    flow: Optional[dict[str, Any]] = None   # None = freeze the working file as is
    scope: str
    project: Optional[str] = None
    base_revision: Optional[int] = None
    force: bool = False
    note: str = ""
    confirmed_destructive: list[str] = []


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


class BridgeInstallBody(BaseModel):
    exe: Optional[str] = None       # default: found by exe_hints
    overwrite: bool = False         # replace files FLUX did not write (after a backup)


def _bridge(soft: str):
    from flux_flows.bridges import extension

    ext = next((e for e in extension.load_all() if e.soft == soft), None)
    if ext is None:
        raise HTTPException(status_code=404, detail={"message": f"bridge d'extension `{soft}` introuvable"})
    return ext


@router.get("/bridges")
async def list_bridges() -> dict[str, Any]:
    """Extension bridges (P6c, CONFIG/extensions/bridges/): manifest, errors, exe found,
    install state on this machine."""
    from flux_flows.bridges import extension, installer

    def _do() -> dict[str, Any]:
        out = []
        for ext in extension.load_all():
            row = ext.to_dict()
            exe = extension.find_exe(ext) if ext.manifest else None
            row["exe"] = exe
            row["install"] = installer.status(ext, exe) if ext.ok else None
            out.append(row)
        folder = extension.bridges_dir()
        return {"dir": str(folder) if folder else None, "bridges": out}

    return await asyncio.to_thread(_do)


@router.post("/bridges/{soft}/install")
async def install_bridge(soft: str, body: BridgeInstallBody) -> dict[str, Any]:
    """Copy the dcc_side script into the soft's folder (this machine). A conflict without
    ``overwrite`` changes nothing: {success: false, conflicts}."""
    from flux_flows.bridges import extension, installer

    ext = _bridge(soft)
    got = await asyncio.to_thread(installer.install, ext, body.exe or extension.find_exe(ext),
                                  overwrite=body.overwrite)
    return got


@router.post("/bridges/{soft}/uninstall")
async def uninstall_bridge(soft: str, body: BridgeInstallBody) -> dict[str, Any]:
    from flux_flows.bridges import extension, installer

    ext = _bridge(soft)
    return await asyncio.to_thread(installer.uninstall, ext, body.exe or extension.find_exe(ext))


class BridgeFlowsBody(BaseModel):
    scene_ext: str = ".scene"       # extension of the soft's scene (.max): the publish template
    overwrite: bool = False


@router.post("/bridges/{soft}/flows")
async def create_bridge_flows(soft: str, body: BridgeFlowsBody) -> dict[str, Any]:
    """Write <prefix>_instance and <prefix>_publish (team nodes) from the bridge (Team TD)."""
    from flux_flows.bridges import flow_templates

    current = await _require(rights.ADMIN, "team")
    ext = _bridge(soft)
    try:
        done = await _call(flow_templates.create_flows, ext, _roots(current["user"], None),
                           user=current["user"] or "", scene_ext=body.scene_ext, overwrite=body.overwrite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    for row in done:
        if row["status"] == "written":
            events.emit({"type": "flow_changed", "flow": row["name"], "scope": "team", "project": None,
                         "by": current["user"]})
    return {"flows": done}


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
    dcc = None
    if flow.node_type:   # a DCC node shipped as a locked subflow, or its team copy (P6a, 03 §8)
        from flux_flows import dcc_nodes

        shipped = await asyncio.to_thread(dcc_nodes.shipped_file, name)
        dcc = {"node_type": flow.node_type, "locked": scope == "shipped",
               "team_copy": scope == "team" and shipped is not None}
    return {"scope": scope, "category": _category(scope), "name": name, "version": version,
            "flow": to_document(flow), "state": got["state"], "legacy": name.startswith(store.LEGACY_PREFIX),
            "issues": v1_limit_issues(flow), "dcc": dcc}


@router.get("/{name}/versions")
async def get_versions(name: str, scope: str, project: Optional[str] = None) -> dict[str, Any]:
    current = await asyncio.to_thread(rights.current_rights)
    return await _call(store.list_versions, _roots(current["user"], project), scope, name)


def _check_confirmed(roots: dict, scope: str, flow: Flow, confirmed: list[str]) -> list[validate.Issue]:
    """E_DESTRUCTIVE_UNCONFIRMED against the working file of *scope* (none = a new file)."""
    try:
        previous = store.read_flow(roots, scope, flow.name)["flow"]
    except (FlowStoreError, FlowSchemaError):
        previous = None
    return validate.unconfirmed_destructive(flow, previous, confirmed)


async def _gate_save(roots: dict, scope: str, flow: Flow, confirmed: list[str],
                     project: Optional[str]) -> list[validate.Issue]:
    """409 when a `!` node was added without the slider; else the issues of *flow*."""
    refused = await asyncio.to_thread(_check_confirmed, roots, scope, flow, confirmed)
    if refused:
        raise HTTPException(status_code=409, detail={
            "message": "Des nodes destructifs doivent etre valides au curseur", "code": "E_DESTRUCTIVE_UNCONFIRMED",
            "issues": _dicts(refused)})
    return await asyncio.to_thread(_issues, roots, scope, flow, project)


def _changed(name: str, scope: str, project: Optional[str], state: dict[str, Any], user: Optional[str]) -> None:
    """WS flow_changed: an early conflict warning for the other editors (01 §10)."""
    events.emit({"type": "flow_changed", "flow": name, "scope": scope, "project": project,
                 "version": state.get("current"), "revision": state.get("revision"), "by": user})


@router.put("/{name}")
async def save(name: str, body: SaveBody) -> dict[str, Any]:
    """Enregistrer: overwrite the working file (409 on a revision conflict or an unconfirmed `!`).
    Saving with errors is allowed: state.json ``valid`` = false, the flow does not activate."""
    current = await _require(rights.WRITE, body.scope)
    flow = _parse(body.flow, name)
    roots = _roots(current["user"], body.project)
    issues = await _gate_save(roots, body.scope, flow, body.confirmed_destructive, body.project)
    valid = not validate.errors(issues)
    state = await _call(store.save_flow, roots, body.scope, flow, user=current["user"] or "",
                        base_revision=body.base_revision, force=body.force, note=body.note, valid=valid)
    _changed(name, body.scope, body.project, state, current["user"])
    return {"state": state, "issues": _dicts(issues), "valid": valid}


@router.post("/{name}/increment")
async def increment(name: str, body: IncrementBody) -> dict[str, Any]:
    """Enregistrer et incrementer: optional save, then a frozen version if the content changed."""
    current = await _require(rights.WRITE, body.scope)
    roots = _roots(current["user"], body.project)
    flow, issues, valid = None, [], None
    if body.flow is not None:
        flow = _parse(body.flow, name)
        issues = await _gate_save(roots, body.scope, flow, body.confirmed_destructive, body.project)
        valid = not validate.errors(issues)
    got = await _call(store.increment_flow, roots, body.scope, name, user=current["user"] or "", flow=flow,
                      base_revision=body.base_revision, force=body.force, note=body.note, valid=valid)
    _changed(name, body.scope, body.project, got["state"], current["user"])
    return {**got, "issues": _dicts(issues), "valid": got["state"].get("valid")}


@router.post("/{name}/revert")
async def revert(name: str, body: RevertBody) -> dict[str, Any]:
    current = await _require(rights.WRITE, body.scope)
    roots = _roots(current["user"], body.project)

    def is_valid(flow: Flow) -> bool:
        return not validate.errors(_issues(roots, body.scope, flow, body.project))

    got = await _call(store.revert_flow, roots, body.scope, name, body.to_version,
                      user=current["user"] or "", validator=is_valid)
    _changed(name, body.scope, body.project, got["state"], current["user"])
    return got


def _issue_key(issue: dict[str, Any]) -> tuple:
    return (issue.get("code"), issue.get("node"), issue.get("port"))


def _gate(roots: dict, scope: str, name: str, project: Optional[str]) -> dict[str, Any]:
    """Activation gate of 01 §8 on the frozen version ``current``: errors, warnings (with
    ``acked``), dry run. ``ready`` = what the Activer button needs (the acks it sends aside)."""
    got = store.read_flow(roots, scope, name)
    state, current = got["state"], got["state"].get("current") or 0
    out: dict[str, Any] = {"version": current, "active": bool(state.get("active")),
                           "active_version": state.get("active_version"), "legacy": name.startswith(store.LEGACY_PREFIX),
                           "errors": [], "warnings": [], "dry_run": {"ok": False, "run_id": None, "version": None},
                           "destructive": [], "ready": False}
    if not current:
        out["reason"] = "aucune version figee : Enregistrer et incrementer d'abord"
        return out
    frozen = store.read_flow(roots, scope, name, current)["flow"]
    issues = _dicts(_issues(roots, scope, frozen, project))
    ack = state.get("acked") if isinstance(state.get("acked"), dict) else {}
    acked = {_issue_key(a) for a in ack.get("items") or []} if ack.get("version") == current else set()
    out["errors"] = [i for i in issues if i["level"] == "error"]
    out["warnings"] = [{**i, "acked": _issue_key(i) in acked} for i in issues if i["level"] == "warning"]
    done = state.get("dry_run_ok") or {}
    out["dry_run"] = {"ok": done.get("version") == current, "run_id": done.get("run_id"),
                      "version": done.get("version")}
    out["destructive"] = sorted(nid for nid, node in frozen.nodes.items() if not node.bypass and
                                (spec := registry.get_node(node.type)) is not None and
                                registry.flag_on(spec.destructive, spec, node.params))
    out["ready"] = (not out["legacy"] and not out["errors"] and out["dry_run"]["ok"]
                    and all(w["acked"] for w in out["warnings"]))
    return out


@router.get("/{name}/activation")
async def get_activation(name: str, scope: str, project: Optional[str] = None) -> dict[str, Any]:
    """The three lines of the activation dialog (03 §5) for the frozen version ``current``."""
    current = await asyncio.to_thread(rights.current_rights)
    return await _call(_gate, _roots(current["user"], project), scope, name, project)


class ActivateBody(ScopeBody):
    acked: list[dict[str, Any]] = []   # warnings read: {code, node, port}, for the version ``current``


@router.post("/{name}/activate")
async def activate(name: str, body: ActivateBody) -> dict[str, Any]:
    """Activate the frozen version ``current`` (01 §8): refused for legacy_* flows (v1
    publish until P8), without a frozen version, with errors, with unacknowledged
    warnings or without a dry run passed on that version (409 ``gate``). The acks sent
    are kept in state.json for this version. The last elapsed Schedule slot is noted."""
    current = await _require(rights.WRITE, body.scope)
    roots = _roots(current["user"], body.project)
    if name.startswith(store.LEGACY_PREFIX):
        raise HTTPException(status_code=409, detail={
            "message": "un flow legacy_* ne s'active pas : le publish tourne encore sur les actions v1"})
    gate = await _call(_gate, roots, body.scope, name, body.project)
    version = gate["version"]
    if not version:
        raise HTTPException(status_code=409, detail={"message": gate.get("reason"), "gate": gate})
    sent = {_issue_key(a) for a in body.acked}
    missing = [w for w in gate["warnings"] if not w["acked"] and _issue_key(w) not in sent]
    problems = []
    if gate["errors"]:
        problems.append(f"{len(gate['errors'])} erreur(s) : corrige puis incremente")
    if missing:
        problems.append(f"{len(missing)} avertissement(s) a lire")
    if not gate["dry_run"]["ok"]:
        problems.append(f"essai a blanc a reussir sur v{version}")
    if problems:
        raise HTTPException(status_code=409, detail={"message": f"v{version} : " + ", ".join(problems), "gate": gate})
    root = Path(roots[body.scope])
    items = [{"code": w["code"], "node": w.get("node"), "port": w.get("port")} for w in gate["warnings"]]

    def finish() -> dict[str, Any]:
        def ack(state: dict[str, Any]) -> bool:
            state["acked"] = {"version": version, "items": items}
            return True

        store.update_state(root, name, ack)
        state = store.set_active(roots, body.scope, name, True, user=current["user"] or "")
        frozen = store.read_flow(roots, body.scope, name, state["active_version"])["flow"]
        scheduler.note_activation(root, name, frozen)
        return state

    state = await _call(finish)
    scheduler.request_refresh()
    events.emit({"type": "activation", "flow": name, "scope": body.scope, "project": body.project,
                 "active": True, "version": state["active_version"], "by": current["user"]})
    return state


@router.post("/{name}/deactivate")
async def deactivate(name: str, body: ScopeBody) -> dict[str, Any]:
    current = await _require(rights.WRITE, body.scope)
    state = await _call(store.set_active, _roots(current["user"], body.project), body.scope, name, False,
                        user=current["user"] or "")
    scheduler.request_refresh()
    events.emit({"type": "activation", "flow": name, "scope": body.scope, "project": body.project,
                 "active": False, "version": state.get("active_version"), "by": current["user"]})
    return state


@router.post("/{name}/copy")
async def copy(name: str, body: CopyBody) -> dict[str, Any]:
    """Enregistrer sous to another scope / name, or unlock a shipped flow (copy to team, Team TD)."""
    action = rights.ADMIN if body.from_scope == "shipped" and body.to_scope == "team" else rights.WRITE
    current = await _require(action, body.to_scope)
    from flux_flows import dcc_nodes

    got = await _call(store.copy_flow, _roots(current["user"], body.project), name, body.from_scope,
                      body.to_scope, user=current["user"] or "", new_name=body.new_name)
    dcc_nodes.reset_cache()
    return got


@router.post("/{name}/unlock")
async def unlock(name: str, body: ScopeBody) -> dict[str, Any]:
    """Deverrouiller a shipped flow or DCC node (decision 19, 03 §8): a team copy of the same
    name that replaces it for the whole team (Team TD). DELETE of the copy = Revenir au defaut."""
    from flux_flows import dcc_nodes

    current = await _require(rights.ADMIN, "team")
    got = await _call(store.copy_flow, _roots(current["user"], body.project), name, "shipped", "team",
                      user=current["user"] or "")
    dcc_nodes.reset_cache()
    events.emit({"type": "flow_changed", "flow": name, "scope": "team", "project": None,
                 "version": got["state"].get("current"), "revision": got["state"].get("revision"),
                 "by": current["user"]})
    return got


@router.delete("/{name}")
async def delete(name: str, scope: str, project: Optional[str] = None) -> dict[str, Any]:
    """To <scope>/_trash/; on a team copy of a shipped flow = Revenir au defaut."""
    from flux_flows import dcc_nodes

    current = await _require(rights.WRITE, scope)
    got = await _call(store.delete_flow, _roots(current["user"], project), scope, name,
                      user=current["user"] or "")
    dcc_nodes.reset_cache()
    return got


def _note_dry_run(run: engine.Run, root: Path, name: str, version: int) -> None:
    """When the dry run of *version* ends ``ok``: state.json dry_run_ok (activation, 01 §8)."""
    def done(_task: asyncio.Task) -> None:
        if run.record.get("status") != "ok":
            return
        note = {"version": version, "run_id": run.run_id, "nodes_simulated": list(run.record["nodes_simulated"]),
                "at": run.record.get("ended")}

        def change(state: dict[str, Any]) -> bool:
            state["dry_run_ok"] = note
            return True

        async def write() -> None:
            try:
                await asyncio.to_thread(store.update_state, root, name, change)
            except OSError:
                pass

        asyncio.get_running_loop().create_task(write())

    run.task.add_done_callback(done)


class RunBody(BaseModel):
    scope: Optional[str] = None
    project: Optional[str] = None
    event: Optional[str] = None               # start event id; None = the first manual / button
    values: dict[str, Any] = {}               # interface values (payload of the event)
    dry_run: bool = False                     # on the saved file, never on a draft (01 §5)
    draft: Optional[dict[str, Any]] = None    # editor document: runs without creating a version (A7)
    base_revision: Optional[int] = None       # revision the draft was loaded from (kept in the record)
    version: Optional[int] = None             # dry run of a frozen version (activation dialog)
    button: Optional[str] = None              # page flow: run as a click on this button, with values (T1)


def _page_click(flow: Flow, event: Optional[str], button: str,
                values: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """(start node, payload) of a Run / dry run that plays a click on a page button: the
    branch of any button, with the field values given (T1: else only the first button with
    the page defaults could be tested). 400 when no InputsPageReader has that button."""
    for nid, node in sorted(flow.nodes.items()):
        if node.type != page_inputs.PAGE_NODE or (event is not None and nid != event):
            continue
        outputs = (node.params.get("ports") or {}).get("outputs") or {}
        if outputs.get(button) == "exec":
            return nid, {"page": str(node.params.get("page") or ""), "button": button, "values": values}
    raise HTTPException(status_code=400, detail={
        "message": f"Aucun InputsPageReader de ce flow n'a de bouton `{button}`"})


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
        got = await _call(store.read_flow, roots, scope, name, body.version)
        flow, mode, base_revision = got["flow"], "dry", got["state"].get("revision")
        current_version = got["state"].get("current") or 0
        if body.version is not None:
            version = body.version
        elif current_version and scope != "shipped":
            # The saved working file equal to the frozen `current` counts for the activation.
            frozen = await _call(store.read_flow, roots, scope, name, current_version)
            if store.dump_flow(frozen["flow"]) == store.dump_flow(flow):
                version = current_version
    else:
        state = (await _call(store.read_flow, roots, scope, name))["state"]
        if not state.get("active") or not state.get("active_version"):
            raise HTTPException(status_code=409, detail={"message": "flow non actif"})
        version = state["active_version"]
        flow = (await _call(store.read_flow, roots, scope, name, version))["flow"]
    folder = runs.runs_dir(scope, project=body.project, user=current["user"])
    event, payload = body.event, None
    if body.button:
        event, payload = _page_click(flow, body.event, body.button, body.values)
    new_run = engine.Run(flow, scope=scope, project=body.project, user=current["user"], mode=mode,
                         draft=draft, version=version, base_revision=base_revision, event=event,
                         values=body.values, payload=payload, folder=folder)
    record = await engine.manager().submit(new_run)
    if mode == "dry" and version and scope != "shipped" and new_run.task is not None:
        _note_dry_run(new_run, Path(roots[scope]), name, version)
    if record["status"] in ("refused", "skipped"):
        raise HTTPException(status_code=409, detail={
            "message": record["error"], "run_id": record["run_id"], "status": record["status"],
            "issues": record["issues"]})
    return {"run_id": record["run_id"], "status": record["status"], "mode": mode}
