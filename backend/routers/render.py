# render.py - farm render routes (ADR 0015): Tractor submission, jobs, farm occupation, team settings.
#
# The Tractor API is never imported here: features.render.tractor_bridge runs the external
# Python 2.7 bridge. Rendered images never go through this API (the UI opens the folder).
# Until the school phase 0 is done, render.json keeps dry_run = true: .alf + .json are written, nothing is spooled.

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.logger import get_logger
from features.render import farm_paths, farm_targets, freeze, job_builder, team_settings, tractor_bridge
from utils import project_utils

log = get_logger(__name__)
router = APIRouter()

# jid -> {project, title, output, user} of jobs seen running, to notify their end (process memory).
_running: dict[int, dict] = {}


def _ensure_project(project: str) -> Path:
    if not project_utils.project_exists(project):
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")
    return Path(project_utils.get_project_path(project))


def _user() -> str:
    return config.get_current_user() or "unknown"


def _bridge_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


# ── settings ────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(project: str):
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    return {"settings": settings, "warning": team_settings.priority_warning(settings)}


@router.put("/settings")
def put_settings(project: str, patch: dict):
    _ensure_project(project)
    try:
        team_settings.write_settings(project, patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return get_settings(project)


# ── shots ───────────────────────────────────────────────────────────────────

@router.get("/shots")
def shots(project: str):
    """Shots with their frame range, to pre-fill the submit form."""
    from features.usd_assembler import shot_stage

    root = _ensure_project(project)
    production, _ = shot_stage.load_project_production(root)
    out = []
    for item in shot_stage.list_shots(root, production):
        stage = shot_stage.last_file(root, item["seq"], item["shot"])
        rng = shot_stage.read_frame_range(production, item["seq"], item["shot"])
        if not rng and stage.is_file():
            rng = _usd_range(stage)
        out.append({"seq": item["seq"], "shot": item["shot"],
                    "frame_start": rng[0] if rng else None, "frame_end": rng[1] if rng else None,
                    "has_stage": stage.is_file()})
    return {"shots": out}


def _usd_range(path: Path) -> tuple[int, int] | None:
    """Frame range authored on the root layer (startTimeCode / endTimeCode), if any."""
    from features.publisher.last_pointer import read_usd_root_info

    try:
        info = read_usd_root_info(path)
    except Exception as exc:  # unreadable USD: the user types the range
        log.warning("Frame range unreadable on %s: %s", path, exc)
        return None
    if "startTimeCode" in info and "endTimeCode" in info:
        return int(float(info["startTimeCode"])), int(float(info["endTimeCode"]))
    return None


@router.get("/usd_range")
def usd_range(project: str, path: str):
    """Frame range of a published USD, to pre-fill the submit form."""
    _ensure_project(project)
    usd = Path(path)
    if not usd.is_file():
        raise HTTPException(status_code=404, detail=f"USD introuvable : {usd}")
    rng = _usd_range(usd)
    return {"frame_start": rng[0] if rng else None, "frame_end": rng[1] if rng else None}


# ── submit ──────────────────────────────────────────────────────────────────

class SubmitBody(BaseModel):
    project: str
    seq: Optional[str] = None
    shot: Optional[str] = None
    usd_path: Optional[str] = None  # a published USD instead of a shot
    frame_start: Optional[int] = None
    frame_end: Optional[int] = None
    renderer: Optional[str] = None
    freeze: Optional[bool] = None
    chunk_size: Optional[int] = None
    start_at: Optional[str] = None  # "YYYY-MM-DDTHH:MM": Tractor holds the job until then
    hosts: list[str] = []           # only these machines (empty = any)
    groups: list[str] = []          # team groups (render.json host_groups) or rooms (ROOM17)
    share_percent: Optional[int] = None  # % of the farm for this job, None = team default
    share_of: Optional[str] = None       # "alive" | "free"


# ── farm snapshot (shared by /farm, /submit and the team balancer) ──────────

_SNAPSHOT_TTL = 20.0
_snapshot: dict = {}


def _farm_snapshot(settings: dict, user: str) -> dict:
    """Classified blades, counts and rooms. Cached a few seconds: one engine query per poll at most."""
    key = settings.get("engine") or ""
    cached = _snapshot.get(key)
    if cached and time.time() - cached["at"] < _SNAPSHOT_TTL:
        return cached["data"]
    raw = tractor_bridge.blades(settings, user)
    blades = farm_targets.classify(raw.get("blades", []))
    data = {"blades": blades, "counts": farm_targets.counts(blades), "rooms": farm_targets.rooms(blades),
            "active_by_project": raw.get("active_by_project", {}), "dry_run": raw.get("dry_run", False)}
    _snapshot[key] = {"at": time.time(), "data": data}
    return data


def _min_cap(*caps: int) -> int:
    real = [c for c in caps if c > 0]
    return min(real) if real else 0


def _targeting(body: SubmitBody, settings: dict, renderer: str, user: str) -> tuple[str, int, int, list[str]]:
    """(service expression, job maxactive, own cap, notes) from the form and the team settings."""
    base = settings["service_karma"] if renderer == "karma" else settings["service_renderman"]
    notes: list[str] = []
    share = {**settings["job_share"]}
    if body.share_percent is not None:
        share["percent"] = body.share_percent
    if body.share_of:
        share["of"] = body.share_of
    team = settings["team_cap"]
    snap = None
    if body.groups or share["percent"] or team["percent"]:
        try:
            snap = _farm_snapshot(settings, user)
        except tractor_bridge.BridgeError as exc:
            notes.append(f"Etat de la farm indisponible ({exc}) : pourcentages ignores")
    rooms = snap["rooms"] if snap else {}
    counts = snap["counts"] if snap else {}
    try:
        include = farm_targets.resolve_hosts(body.hosts, body.groups, settings["host_groups"], rooms)
        service = farm_targets.service_expression(base, include, settings["exclude_hosts"])
        own = 0
        team_total = 0
        if snap:
            if not 0 <= int(share["percent"]) <= 100:
                raise ValueError("pourcentage entre 0 et 100")
            own = farm_targets.cap_from_percent(int(share["percent"]), share["of"], counts)
            team_total = farm_targets.cap_from_percent(team["percent"], team["of"], counts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if (body.hosts or body.groups) and not include:
        raise HTTPException(status_code=400, detail="Aucune machine dans la selection")
    if include and not farm_targets.FLUX_HOST_TARGETING_VERIFIED:
        notes.append("Ciblage par nom de machine pas encore valide sur la farm (job test a faire)")
    own = _min_cap(settings["maxactive"], own)
    # The team balancer refines this on the next farm poll; start under the team budget.
    return service, _min_cap(own, team_total), own, notes


def _farm(path: Path | str, what: str, simulate: bool) -> str:
    unc = farm_paths.to_farm_path(path)
    if unc is None:
        if simulate:
            return str(path).replace("\\", "/")
        raise HTTPException(status_code=400, detail=(
            f"{what} est sur un disque local ({path}) : la farm ne le voit pas. "
            "Ouvrir le root FLUX par son chemin reseau (UNC ou lecteur reseau)."))
    return unc


def _submit(body: SubmitBody, user: str) -> dict:
    from features.usd_assembler import shot_stage

    root = _ensure_project(body.project)
    settings = team_settings.effective_settings(body.project)
    simulate = settings["dry_run"] is True
    do_freeze = settings["freeze_by_default"] if body.freeze is None else body.freeze
    renderer = body.renderer or settings["renderer"]

    if not body.usd_path and not (body.seq and body.shot):
        raise HTTPException(status_code=400, detail="Choisir un shot ou un USD publie")
    rng = None
    if body.usd_path:
        # A published USD, or a stage written by the Houdini HDA (with its shot).
        usd = Path(body.usd_path)
        if not usd.is_file():
            raise HTTPException(status_code=404, detail=f"USD introuvable : {usd}")
        frozen = freeze.freeze_usd(usd, freeze=do_freeze)
        name, folder, rng = usd.stem.replace("_LAST", ""), usd.parent, _usd_range(usd)
    if body.seq and body.shot:
        seq, shot = body.seq.upper(), body.shot.upper()
        if not body.usd_path:
            try:
                frozen = freeze.freeze_shot(root, seq, shot, user=user, freeze=do_freeze)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
        name = shot_stage.entity(seq, shot)
        folder = shot_stage.shot_dir(root, seq, shot)
        production, _ = shot_stage.load_project_production(root)
        rng = shot_stage.read_frame_range(production, seq, shot) or rng

    start = body.frame_start if body.frame_start is not None else (rng[0] if rng else None)
    end = body.frame_end if body.frame_end is not None else (rng[1] if rng else None)
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="Plage de frames inconnue : la saisir")

    service, maxactive, own_cap, notes = _targeting(body, settings, renderer, user)
    out_dir = freeze.next_render_dir(folder)
    spec = job_builder.RenderJobSpec(
        title=f"{body.project} {name} {out_dir.name}",
        project=settings["tractor_project"],
        user=user,
        usd_path=_farm(frozen["usd"], "Le USD", simulate),
        output_pattern=_farm(out_dir / f"{name}.$F4.exr", "Le dossier de rendu", simulate),
        frame_start=start,
        frame_end=end,
        renderer=renderer,
        chunk_size=body.chunk_size or settings["chunk_size"],
        priority=settings["priority"],
        maxactive=maxactive,
        service=service,
        envkeys=settings["envkeys"],
        husk=settings["husk_path"],
        start_after=body.start_at or "",
        metadata={"flux_project": body.project, "entity": name, "user": user, "cap": str(own_cap),
                  "output": _farm(out_dir, "Le dossier de rendu", simulate), "frozen": "1" if frozen["frozen"] else "0"},
    )
    try:
        result = tractor_bridge.spool(spec, settings, user, out_dir / "_job")
    except job_builder.JobValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)
    if result.get("jid") is not None:
        _running[int(result["jid"])] = {"project": body.project, "title": spec.title,
                                        "output": str(out_dir), "user": user, "seen": time.time()}
    log.info("Render %s %s (%s) -> %s", "simulated" if result["dry_run"] else "spooled", spec.title,
             renderer, result.get("jid"))
    return {**result, "title": spec.title, "output": str(out_dir), "usd": frozen["usd"],
            "frozen": frozen["frozen"], "frames": [start, end], "start_at": spec.start_after,
            "service": service, "maxactive": maxactive, "warnings": frozen["warnings"] + notes,
            "priority_warning": team_settings.priority_warning(settings)}


@router.post("/submit")
async def submit(body: SubmitBody):
    # Freezing writes a stage version and audits USD dependencies: off the event loop.
    return await asyncio.to_thread(_submit, body, _user())


# ── follow-up ───────────────────────────────────────────────────────────────

_FINAL_STATES = ("done", "error", "deleted")


def _notify_finished(jobs: list[dict], user: str) -> list[dict]:
    """The user's jobs seen running that reached a final state (or left the list): log them once."""
    by_jid = {j.get("jid"): j for j in jobs}
    for j in jobs:
        if (isinstance(j.get("jid"), int) and j["jid"] not in _running
                and j.get("flux_user") == user and j.get("state") not in _FINAL_STATES):
            _running[j["jid"]] = {"project": "", "title": j.get("title") or "", "output": "",
                                  "user": user, "seen": time.time()}
    finished = []
    for jid in [jid for jid, info in _running.items() if info["user"] == user
                and (jid not in by_jid or by_jid[jid].get("state") in _FINAL_STATES)]:
        info = _running.pop(jid)
        finished.append({"jid": jid, **info})
        try:
            from features.activity.activity_writer import log_event

            log_event(user, "render", info["project"], info["title"], dest_folder=info["output"] or None)
        except Exception as exc:  # noqa: BLE001 - a notification never fails the poll
            log.warning("Render notification failed: %s", exc)
    return finished


_SCOPES = ("all", "team", "mine")


def _jobs(project: str, scope: str, days: int, user: str) -> dict:
    """Every Tractor job (all states, all owners) like the Dashboard; the UI filters further."""
    _ensure_project(project)
    if scope not in _SCOPES:
        raise HTTPException(status_code=400, detail=f"Filtre inconnu : {scope}")
    settings = team_settings.effective_settings(project)
    try:
        out = tractor_bridge.jobs(settings, user, mine=(scope == "mine"), days=max(1, min(days, 365)),
                                  project=settings["tractor_project"] if scope == "team" else None)
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)
    # A team-filtered list can miss a running job of the user: notify only on the full list.
    full = scope != "team" and tractor_bridge.is_configured(settings)
    out["finished"] = _notify_finished(out.get("jobs", []), user) if full else []
    out["tractor_project"] = settings["tractor_project"]
    return out


@router.get("/jobs")
async def jobs(project: str, scope: str = "all", days: int = 30):
    return await asyncio.to_thread(_jobs, project, scope, days, _user())


def _tasks(project: str, jid: int, user: str) -> dict:
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    try:
        return tractor_bridge.tasks(settings, user, jid)
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)


@router.get("/jobs/{jid}/tasks")
async def job_tasks(jid: int, project: str):
    return await asyncio.to_thread(_tasks, project, jid, _user())


def _task_log(project: str, jid: int, tid: int, user: str) -> dict:
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    try:
        return tractor_bridge.task_log(settings, user, jid, tid)
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)


@router.get("/jobs/{jid}/tasks/{tid}/log")
async def job_task_log(jid: int, tid: int, project: str):
    return await asyncio.to_thread(_task_log, project, jid, tid, _user())


_BALANCE_MAX_CHANGES = 20  # engine writes per poll, at most (never flood the engine)
_DONE_STATES = ("done", "deleted")


def _as_int(value) -> int:
    try:
        return max(0, int(str(value or "0")))
    except ValueError:
        return 0


def _balance_team(project: str, settings: dict, user: str, counts: dict) -> dict:
    """Split the team cap between the team's unfinished FLUX jobs (jattr maxactive).

    Every FLUX window of the team runs the same deterministic split, so they agree.
    Only jobs with metadata.flux_project == project and the team's Tractor project are touched.
    """
    team = settings["team_cap"]
    total = farm_targets.cap_from_percent(team["percent"], team["of"], counts) if team["percent"] else 0
    out = {"enabled": bool(total), "slots": total, "used": 0, "targets": {}, "changed": 0, "errors": []}
    if not total:
        return out
    listing = tractor_bridge.jobs(settings, user, project=settings["tractor_project"], days=30)
    team_jobs = [j for j in listing.get("jobs", [])
                 if j.get("metadata", {}).get("flux_project") == project and j.get("state") not in _DONE_STATES
                 and settings["tractor_project"] in (j.get("projects") or [])]
    out["used"] = sum(int(j.get("numActive") or 0) for j in team_jobs)
    live = [j for j in team_jobs if j.get("state") != "paused"]
    targets = farm_targets.split_team_cap(total, [
        {"jid": j["jid"], "remaining": int(j.get("numTasks") or 0) - int(j.get("numDone") or 0),
         "cap": _as_int(j.get("metadata", {}).get("cap"))} for j in live])
    out["targets"] = targets
    if settings.get("dry_run") is True:
        return out  # computed and shown, never applied in simulation
    current = {j["jid"]: int(j.get("maxactive") or 0) for j in live}
    for jid, value in sorted(targets.items()):
        if current.get(jid) == value:
            continue
        if out["changed"] >= _BALANCE_MAX_CHANGES:
            break
        try:
            tractor_bridge.set_maxactive(settings, user, jid, value)
            out["changed"] += 1
        except tractor_bridge.BridgeError as exc:
            out["errors"].append(f"{jid}: {exc}")
    return out


def _farm_state(project: str, user: str) -> dict:
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    try:
        out = dict(_farm_snapshot(settings, user))
        out["team_cap"] = _balance_team(project, settings, user, out["counts"])
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)
    out["schedule"] = settings["schedule"]
    out["tractor_project"] = settings["tractor_project"]
    out["host_groups"] = settings["host_groups"]
    out["exclude_hosts"] = settings["exclude_hosts"]
    out["host_targeting_verified"] = farm_targets.FLUX_HOST_TARGETING_VERIFIED
    return out


@router.get("/farm")
async def farm(project: str):
    return await asyncio.to_thread(_farm_state, project, _user())


_ACTIONS = {"kill": tractor_bridge.kill, "retry": tractor_bridge.retry,
            "pause": tractor_bridge.pause, "resume": tractor_bridge.resume}


def _action(project: str, jid: int, action: str, user: str) -> dict:
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    try:
        return _ACTIONS[action](settings, user, jid)
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)


@router.post("/jobs/{jid}/{action}")
async def job_action(jid: int, action: str, project: str):
    if action not in _ACTIONS:
        raise HTTPException(status_code=400, detail=f"Action inconnue : {action}")
    return await asyncio.to_thread(_action, project, jid, action, _user())
