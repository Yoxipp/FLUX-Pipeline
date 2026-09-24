# routers/usd_assembler.py — assemble published USD from a declarative recipe.
#
# pxr is heavy and, on Windows, can abort a worker thread on teardown, so it must
# NOT load at sidecar boot: the façade (which pulls pxr) is imported lazily inside
# the handler, and the long compose/write runs in a thread via run_in_executor.

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.logger import get_logger
from core.paths import get_project_path

log = get_logger(__name__)
router = APIRouter()

# Where assembled layers are written under the project (config-overridable).
_DEFAULT_OUTPUT_SUBDIR = "usd/assembly"
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / (
    "features/usd_assembler/recipe/schema.json"
)


class AssembleRequest(BaseModel):
    recipe: dict
    project: str | None = None
    strict: bool = True


def _resolve_project(project: str | None) -> tuple[str, Path]:
    """Return (project_name, project_path) for *project* or the last active one."""
    name = project or config.get_last_project()
    if not name:
        raise HTTPException(status_code=400, detail="no project selected")
    path = get_project_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"project not found: {name}")
    return name, path


def _run_assemble(recipe: dict, project_path: Path, strict: bool) -> dict:
    """Blocking assemble pass (runs in an executor thread). Imports pxr lazily."""
    from features.usd_assembler.resolve.flux_resolver import FluxResolver
    from features.usd_assembler.usd_assembler_core import AssemblyError, assemble

    ns = config.get("usd_assembler", {}) or {}
    resolver = FluxResolver(project_path, ns)
    dest_dir = project_path / ns.get("output_subdir", _DEFAULT_OUTPUT_SUBDIR)

    try:
        result = assemble(
            recipe, resolver=resolver, dest_dir=dest_dir, config=ns, strict=strict
        )
    except AssemblyError as exc:
        return {
            "success": False,
            "issues": [
                {"level": i.level, "msg": i.msg, "prim": i.prim} for i in exc.issues
            ],
        }

    return {
        "success": True,
        "root": str(result.root),
        "layers": [str(p) for p in result.layers],
        "issues": [
            {"level": i.level, "msg": i.msg, "prim": i.prim} for i in result.issues
        ],
    }


@router.post("/assemble")
async def assemble_recipe(req: AssembleRequest) -> dict:
    """Assemble a recipe into published USD and return the written layer paths."""
    _, project_path = _resolve_project(req.project)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: _run_assemble(req.recipe, project_path, req.strict)
        )
    except HTTPException:
        raise
    except Exception as exc:  # surface loader/resolver errors as 400s
        log.exception("assemble failed")
        raise HTTPException(status_code=400, detail=str(exc))

    # Mirror the outcome into the logger so full messages are readable in the Flux console.
    if result.get("success"):
        log.info("USD assembly OK -> %s", result.get("root"))
        for lyr in result.get("layers", []):
            log.info("USD assembly layer: %s", lyr)
    else:
        log.error("USD assembly failed")
    for iss in result.get("issues", []):
        prim = f" [{iss['prim']}]" if iss.get("prim") else ""
        (log.error if iss.get("level") == "error" else log.warning)(
            "USD assembly %s%s: %s", iss.get("level"), prim, iss.get("msg")
        )
    return result


@router.get("/schema")
async def get_recipe_schema() -> dict:
    """Return the recipe JSON Schema (drives the frontend recipe builder)."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


@router.get("/layers")
async def list_usd_layers(
    asset: str, task: str, instance: str = "", project: str | None = None
) -> dict:
    """List published layered-USD versions for *asset*'s *task* (component slots).

    Feeds the frontend slot editor's version dropdown. Pure python (no pxr): the
    FluxResolver only globs the published layout. An unresolvable identity (asset
    with no NAME token, nothing published yet) returns an empty version map rather
    than an error, so the editor degrades gracefully while the user is still typing.
    """
    name, project_path = _resolve_project(project)
    from features.usd_assembler.resolve.base import ResolveError
    from features.usd_assembler.resolve.flux_resolver import FluxResolver

    ns = config.get("usd_assembler", {}) or {}
    resolver = FluxResolver(project_path, ns)
    try:
        versions = resolver.list_layer_versions(asset, task, instance)
    except ResolveError as exc:
        log.info("USD layers: %s (asset '%s', task '%s')", exc, asset, task)
        versions = {}
    except Exception as exc:  # unexpected — surface as a 400
        log.exception("list layers failed")
        raise HTTPException(status_code=400, detail=str(exc))

    return {"project": name, "asset": asset, "task": task, "versions": versions}


@router.get("/departments")
async def list_usd_departments() -> dict:
    """The one department table (ADR 0019): TYPE -> department + what FLUX exports.
    The Publisher reads it so backend and UI can never disagree."""
    from features.usd_export.departments import (
        DEPARTMENT_ORDER, SHOT_EXPORT_CONTENT, publisher_table,
    )

    return {"tasks": publisher_table(), "order": DEPARTMENT_ORDER,
            "shot_tasks": SHOT_EXPORT_CONTENT}


@router.get("/composition")
async def get_usd_composition(file: str, project: str | None = None) -> dict:
    """Read-only composition of a published USD entry: prims (type, kind, variants,
    references) and the layers it uses. Feeds the USD page "Composition" view."""
    _, project_path = _resolve_project(project)
    from core.paths import is_subpath

    # Security S5: only files of the project can be inspected (the UI passes absolute
    # paths coming from /usd/library, a relative one is taken under the project).
    raw = Path(file)
    target = raw if raw.is_absolute() else (project_path / file)
    if not is_subpath(target.resolve(), project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorise")
    from features.usd_assembler.inspect import composition

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: composition(target))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        log.exception("composition failed")
        raise HTTPException(status_code=400, detail=str(exc))


def _resolver_for(project: str | None):
    """Build a FluxResolver for *project* (or the active one). Pure python, no pxr."""
    name, project_path = _resolve_project(project)
    from features.usd_assembler.resolve.flux_resolver import FluxResolver

    ns = config.get("usd_assembler", {}) or {}
    return name, FluxResolver(project_path, ns)


@router.get("/tasks")
async def list_usd_tasks(asset: str, project: str | None = None) -> dict:
    """TYPE/task tokens published under *asset* — feeds the slot task combobox."""
    name, resolver = _resolver_for(project)
    try:
        tasks = resolver.list_tasks(asset)
    except Exception as exc:  # unresolvable identity → empty, editor keeps typing
        log.info("USD tasks: %s (asset '%s')", exc, asset)
        tasks = []
    return {"project": name, "asset": asset, "tasks": tasks}


@router.get("/instances")
async def list_usd_instances(
    asset: str, task: str = "", project: str | None = None
) -> dict:
    """Instance leaves published for *asset* (optionally scoped to *task*)."""
    name, resolver = _resolver_for(project)
    try:
        instances = resolver.list_instances(asset, task)
    except Exception as exc:
        log.info("USD instances: %s (asset '%s', task '%s')", exc, asset, task)
        instances = []
    return {"project": name, "asset": asset, "task": task, "instances": instances}


@router.get("/variantes")
async def list_usd_variantes(
    asset: str, task: str, instance: str = "", project: str | None = None
) -> dict:
    """VARIANTE tokens published for *asset*/*task* (optionally one *instance*)."""
    name, resolver = _resolver_for(project)
    try:
        variantes = resolver.list_variantes(asset, task, instance)
    except Exception as exc:
        log.info(
            "USD variantes: %s (asset '%s', task '%s', instance '%s')",
            exc, asset, task, instance,
        )
        variantes = []
    return {
        "project": name, "asset": asset, "task": task,
        "instance": instance, "variantes": variantes,
    }


class ComponentRefreshRequest(BaseModel):
    name: str
    project: str | None = None
    user: str = ""


class ComponentCreateRequest(BaseModel):
    name: str
    departments: list[str]
    project: str | None = None
    user: str = ""


class ComponentSaveRequest(BaseModel):
    name: str
    recipe: dict                    # see features/usd_assembler/component_recipe.py
    project: str | None = None
    user: str = ""


class ComponentCheckRequest(BaseModel):
    name: str
    version: str = "LAST"
    active: dict[str, bool] = {}    # the importer's own toggles (never saved in the component)
    project: str | None = None


class RelinkRequest(BaseModel):
    file: str
    prim: str
    component: str
    version: str = "LAST"
    project: str | None = None


def _library(project_path: Path) -> dict:
    from features.usd_assembler.library import build_library

    ns = config.get("usd_assembler", {}) or {}
    return build_library(project_path, ns.get("output_subdir", _DEFAULT_OUTPUT_SUBDIR))


@router.get("/library")
async def get_usd_library(project: str | None = None) -> dict:
    """Existing components (ADR 0018) and assemblies of the project (A2 default view)."""
    name, project_path = _resolve_project(project)
    loop = asyncio.get_running_loop()
    try:
        lib = await loop.run_in_executor(None, lambda: _library(project_path))
    except Exception as exc:
        log.exception("USD library failed")
        raise HTTPException(status_code=400, detail=str(exc))
    return {"project": name, **lib}


def _component_result(res: dict | None) -> dict:
    if res is None:
        return {"ok": True, "changed": False, "version": None, "warnings": []}
    return {"ok": True, "changed": True, "version": res["version"], "last": str(res["last"] or ""),
            "warnings": res.get("warnings", [])}


async def _component_call(fn) -> dict:
    loop = asyncio.get_running_loop()
    try:
        return _component_result(await loop.run_in_executor(None, fn))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("component operation failed")
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/component/refresh")
async def refresh_usd_component(req: ComponentRefreshRequest) -> dict:
    """Re-compose an existing component from its recipe (latest publishes followed)."""
    _, project_path = _resolve_project(req.project)
    from features.usd_assembler.component_auto import refresh_component

    return await _component_call(lambda: refresh_component(project_path, req.name, user=req.user))


@router.post("/component/create")
async def create_usd_component(req: ComponentCreateRequest) -> dict:
    """Create a component by hand (ADR 0023): the departments picked by the artist."""
    _, project_path = _resolve_project(req.project)
    from features.usd_assembler.component_auto import create_component

    res = await _component_call(lambda: create_component(project_path, req.name, req.departments, user=req.user))
    log.info("USD component %s created (%s)", req.name, ", ".join(req.departments))
    return res


@router.post("/component/add-proposed")
async def add_proposed_usd_component(req: ComponentRefreshRequest) -> dict:
    """"Tout ajouter": every proposed publish of the component's departments joins it."""
    _, project_path = _resolve_project(req.project)
    from features.usd_assembler.component_auto import add_proposed

    return await _component_call(lambda: add_proposed(project_path, req.name, user=req.user))


@router.post("/component/save")
async def save_usd_component(req: ComponentSaveRequest) -> dict:
    """New component version from its edited recipe (files, kinds, targets, proxies)."""
    _, project_path = _resolve_project(req.project)
    from features.usd_assembler.component_auto import save_component

    return await _component_call(lambda: save_component(project_path, req.name, req.recipe, user=req.user))


@router.post("/component/check")
async def check_usd_component(req: ComponentCheckRequest) -> dict:
    """Files, greyed ones and warnings of a component for the importer's current toggles."""
    _, project_path = _resolve_project(req.project)
    from features.usd_assembler.component_auto import component_files

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, lambda: component_files(project_path, req.name, req.version, req.active))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class AssemblyCreateRequest(BaseModel):
    name: str
    source: str | None = None       # duplicate this assembly's current instances
    project: str | None = None
    user: str = ""


class AssemblyEditRequest(BaseModel):
    name: str
    ops: list[dict]                 # see assembly_v2.apply_ops
    project: str | None = None
    user: str = ""


def _assembly_result(res: dict | None) -> dict:
    if not res or not res.get("version"):
        return {"ok": True, "changed": False, "version": None, "warnings": (res or {}).get("warnings", [])}
    return {"ok": True, "changed": True, "version": res["version"],
            "last": str(res.get("last") or ""), "warnings": res.get("warnings", [])}


@router.post("/assembly/create")
async def create_usd_assembly(req: AssemblyCreateRequest) -> dict:
    """New versioned assembly (A3), empty or duplicated from an existing one."""
    _, project_path = _resolve_project(req.project)
    from features.usd_assembler.assembly_v2 import create_assembly

    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: create_assembly(
            project_path, req.name, source=req.source, user=req.user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("assembly create failed")
        raise HTTPException(status_code=400, detail=str(exc))
    return _assembly_result(res)


@router.post("/assembly/edit")
async def edit_usd_assembly(req: AssemblyEditRequest) -> dict:
    """Add / remove / duplicate / rename / relink / version instances: new assembly version."""
    _, project_path = _resolve_project(req.project)
    from features.usd_assembler.assembly_v2 import edit_assembly

    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: edit_assembly(
            project_path, req.name, req.ops, user=req.user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("assembly edit failed")
        raise HTTPException(status_code=400, detail=str(exc))
    return _assembly_result(res)


class LayoutPublishRequest(BaseModel):
    name: str
    dcc: str                        # "houdini" | "maya"
    project: str | None = None
    user: str = ""


@router.post("/assembly/layout/publish")
async def publish_usd_assembly_layout(req: LayoutPublishRequest) -> dict:
    """Read instance placements from the open DCC, publish the layout vNNN + LAST,
    then a new assembly version pinned on it."""
    _, project_path = _resolve_project(req.project)
    dcc = req.dcc.lower()
    if dcc == "houdini":
        from dcc.houdini.houdini_layout import collect_layout
    elif dcc == "maya":
        from dcc.maya.maya_layout import collect_layout
    else:
        raise HTTPException(status_code=400, detail=f"DCC non gere pour le layout : {req.dcc}")
    from features.usd_assembler.layout_publish import publish_layout

    loop = asyncio.get_running_loop()
    collected = await loop.run_in_executor(None, lambda: collect_layout(req.name))
    if not collected.get("ok"):
        raise HTTPException(status_code=503, detail=collected.get("error") or f"{req.dcc} injoignable")
    placements = (collected.get("result") or {}).get("placements") or {}
    try:
        res = await loop.run_in_executor(None, lambda: publish_layout(
            project_path, req.name, placements, user=req.user, source=dcc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("layout publish failed")
        raise HTTPException(status_code=400, detail=str(exc))
    return {**_assembly_result(res), "layout_version": res["layout_version"],
            "layout": str(res["layout"]), "placements": len(placements)}


@router.post("/assembly/relink")
async def relink_usd_assembly_instance(req: RelinkRequest) -> dict:
    """Point one instance of an assembly at another component or version."""
    _, project_path = _resolve_project(req.project)
    from features.usd_assembler.library import relink_instance

    ns = config.get("usd_assembler", {}) or {}
    subdir = ns.get("output_subdir", _DEFAULT_OUTPUT_SUBDIR)
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: relink_instance(
            project_path, req.file, req.prim, req.component, req.version, subdir))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("assembly relink failed")
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, **res}


# ── shot stage (A4, ADR 0020) ────────────────────────────────────────────────

class ShotStageRequest(BaseModel):
    seq: str
    shot: str
    project: str | None = None
    user: str = ""
    frozen: bool = False            # "figer": every layer points at its vNNN (farm)


@router.get("/shots")
async def list_usd_shots(project: str | None = None) -> dict:
    """Every shot of Production with its stage state, casting, animations and layers."""
    name, project_path = _resolve_project(project)
    from features.usd_assembler.shot_stage import list_shots

    loop = asyncio.get_running_loop()
    try:
        shots = await loop.run_in_executor(None, lambda: list_shots(project_path))
    except Exception as exc:
        log.exception("USD shots failed")
        raise HTTPException(status_code=400, detail=str(exc))
    return {"project": name, "shots": shots}


@router.post("/shot/generate")
async def generate_usd_shot(req: ShotStageRequest) -> dict:
    """(Re)generate the shot stage: new version only when something changed."""
    _, project_path = _resolve_project(req.project)
    from features.usd_assembler.shot_stage import write_stage

    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: write_stage(
            project_path, req.seq, req.shot, user=req.user, frozen=req.frozen))
    except Exception as exc:
        log.exception("shot stage failed")
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "changed": bool(res["version"]), "version": res["version"],
            "last": str(res["last"]) if res["last"] and Path(res["last"]).is_file() else "",
            "warnings": res["warnings"], "auto_cast": res["auto_cast"]}


# ── crowd (A6 / A7, ADR 0022) ────────────────────────────────────────────────

@router.get("/crowd/compat")
async def crowd_compat(project: str | None = None) -> dict:
    """Assets with a skeleton (signature, same-rig assets, fitting clips) + the clips."""
    _, project_path = _resolve_project(project)
    from features.usd_assembler.crowd import compatibility

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: compatibility(project_path))
    except Exception as exc:
        log.exception("crowd compat failed")
        raise HTTPException(status_code=400, detail=str(exc))


# ── old Constructor files (V4, ADR 0019 point 7) ─────────────────────────────

class LegacyDeleteRequest(BaseModel):
    rel_path: str
    project: str | None = None
    user: str = ""


@router.get("/legacy")
async def list_usd_legacy(project: str | None = None) -> dict:
    """Old flat files of the removed Constructor (never proposed to DCC imports)."""
    _, project_path = _resolve_project(project)
    from features.importer.load_target import legacy_files

    loop = asyncio.get_running_loop()
    files = await loop.run_in_executor(None, lambda: legacy_files(project_path))
    return {"files": [{"name": f.name, "rel_path": f.relative_to(project_path).as_posix()} for f in files]}


@router.post("/legacy/delete")
async def delete_usd_legacy(req: LegacyDeleteRequest) -> dict:
    """Move an old Constructor file to <project>/_backup_flux/<date>/ (never a hard delete)."""
    _, project_path = _resolve_project(req.project)
    from core.paths import is_subpath
    from features.importer.load_target import delete_legacy_file

    target = (project_path / req.rel_path).resolve()
    if not is_subpath(target, project_path.resolve()):
        raise HTTPException(status_code=403, detail="Chemin non autorise")
    loop = asyncio.get_running_loop()
    try:
        backup = await loop.run_in_executor(None, lambda: delete_legacy_file(project_path, target, user=req.user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "backup": str(backup) if backup else ""}
