# render.py - farm render routes (ADR 0015): Tractor submission, jobs, farm occupation, team settings.
#
# The Tractor API is never imported here: features.render.tractor_bridge runs the external
# Python 2.7 bridge. Rendered images never go through this API (the UI opens the folder).
# render.json dry_run = true (opt-in simulation): .alf + .json are written, nothing is spooled. Default is the real farm.
# Studio-specific values (engine, blade paths, tags, rooms) come from the studio environment file
# (features.render.studio_env, linked from CONFIG/studio.json), never from this code.

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.logger import get_logger
from features.render import (exit_codes, farm_limits, farm_paths, farm_targets, freeze, job_builder, studio_env,
                             team_settings, tractor_bridge)
from features.roles import project_roles
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


def _require(project: str, action: str) -> None:
    """Project role check (lead / supervisor for these actions): HTTP 403 with the readable reason."""
    try:
        project_roles.require(project, action)
    except project_roles.RoleError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


# ── settings ────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(project: str):
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    shares = farm_limits.fetch_shares(settings["engine"])
    tag, default_share = settings["render_tag"], settings["default_share"]
    # Teams of the farm (engine limits.config, read only): Tractor shares the farm between them.
    return {"settings": settings, "warning": team_settings.priority_warning(settings), "user": _user(),
            "farm_teams": farm_limits.teams(shares, tag, default_share),
            # {team: {nominal, cap}} of FLUX's commands (render tag), default share = every other project. None = unknown.
            "farm_shares": (shares or {}).get(tag),
            "default_share": default_share,
            "team_warning": farm_limits.team_warning(settings["tractor_project"], shares, tag, default_share)}


# ── farm environment: the engine's limits.config (locked screen, 2026-10-23) ──
# Role lead or supervisor on the project (project_roles "farm_env") + the "Understand" phrase.

class EnvUnlock(BaseModel):
    phrase: str = ""


class EnvShares(EnvUnlock):
    teams: dict  # {team: {"nominal": 0..1, "cap": 0..1}}


@router.post("/env/state")
def env_state(project: str, body: EnvUnlock):
    """Shares as the engine serves them, and whether the configured folder holds that same file."""
    _ensure_project(project)
    _require(project, "farm_env")
    try:
        farm_limits.check_unlock(body.phrase)
    except farm_limits.LimitsError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    settings = team_settings.effective_settings(project)
    served = farm_limits.engine_text(settings["engine"])
    out = {"engine": settings["engine"], "config_dir": settings["engine_config_dir"],
           "engine_shares": farm_limits.parse_shares(served) if served else None, "folder_ok": False, "folder_error": None}
    try:
        _path, text = farm_limits.read_local(settings["engine_config_dir"])
        out["folder_ok"] = served is not None and farm_limits.same_text(served, text)
        if not out["folder_ok"]:
            out["folder_error"] = ("Moteur injoignable" if served is None
                                   else "Ce dossier ne contient pas le limits.config que sert le moteur")
    except (farm_limits.LimitsError, OSError, UnicodeDecodeError) as exc:
        out["folder_error"] = str(exc)
    return out


@router.put("/env/shares")
def env_shares(project: str, body: EnvShares):
    _ensure_project(project)
    _require(project, "farm_env")
    settings = team_settings.effective_settings(project)
    if settings["dry_run"] is True:
        raise HTTPException(status_code=400, detail="Mode simulation : la config de la farm n'est jamais modifiee")
    try:
        out = farm_limits.write_shares(settings["engine_config_dir"], settings["engine"], body.teams,
                                       body.phrase, settings["default_share"])
    except farm_limits.LimitsError as exc:
        raise HTTPException(status_code=403 if "verrouilles" in str(exc) else 400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Ecriture impossible : {exc}")
    log.warning("Farm limits.config Shares changed by %s (%s), backup %s", _user(), project, out["backup"])
    return out


@router.post("/env/reload")
def env_reload(project: str, body: EnvUnlock):
    _ensure_project(project)
    _require(project, "farm_env")
    try:
        farm_limits.check_unlock(body.phrase)
    except farm_limits.LimitsError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    settings = team_settings.effective_settings(project)
    try:
        out = tractor_bridge.reload_limits(settings, _user())
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)
    log.warning("Farm limits.config reloaded by %s (%s)", _user(), project)
    return out


# ── last launch form of each artist (follows the artist from desk to desk: stored in the project) ──

_LAST_MAX_BYTES = 20_000


def _last_path(project: str, user: str) -> Path:
    from core import paths

    safe = "".join(c for c in user if c.isalnum() or c in "_.-") or "unknown"
    return Path(paths.get_project_render_path(project)).parent / "render_last" / f"{safe}.json"


@router.get("/last")
def get_last(project: str):
    _ensure_project(project)
    from core.json_manager import read_json

    data = read_json(_last_path(project, _user()))
    return {"last": data if isinstance(data, dict) else {}}


@router.put("/last")
def put_last(project: str, last: dict):
    _ensure_project(project)
    from core.json_manager import write_json
    import json as _json

    if len(_json.dumps(last)) > _LAST_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Derniere saisie trop grande")
    target = _last_path(project, _user())
    target.parent.mkdir(parents=True, exist_ok=True)
    if not write_json(target, last):
        raise HTTPException(status_code=500, detail="Derniere saisie non enregistree")
    return {"ok": True}


@router.put("/settings")
def put_settings(project: str, patch: dict):
    _ensure_project(project)
    _require(project, "render_settings")
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
    freeze_when: Optional[str] = None  # scheduled job: "start" (on the blade) | "submit", None = team default
    hosts: list[str] = []           # only these machines (empty = any)
    groups: list[str] = []          # team groups (render.json host_groups) or rooms (ROOM17)
    share_percent: Optional[int] = None  # % of the farm for this job, None = team default
    share_of: Optional[str] = None       # "alive" | "free"
    priority: Optional[int] = None       # this job only, None = team default (higher = dispatched first)
    denoise: bool = False                # RenderMan denoise_batch after the render, same job
    denoise_crossframe: Optional[bool] = None  # None = team default


# ── farm snapshot (shared by /farm, /submit and the team balancer) ──────────

_SNAPSHOT_TTL = 20.0
_snapshot: dict = {}


def _farm_snapshot(settings: dict, user: str) -> dict:
    """Classified blades, counts and rooms. Cached a few seconds: one engine query per poll at most."""
    key = (settings.get("engine") or "") + "|" + (settings.get("room_pattern") or "")
    cached = _snapshot.get(key)
    if cached and time.time() - cached["at"] < _SNAPSHOT_TTL:
        return cached["data"]
    raw = tractor_bridge.blades(settings, user)
    blades = farm_targets.classify(raw.get("blades", []), room_pattern=settings.get("room_pattern") or "")
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
    snap = None
    if body.groups or share["percent"]:
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
        if snap:
            if not 0 <= int(share["percent"]) <= 100:
                raise ValueError("pourcentage entre 0 et 100")
            own = farm_targets.cap_from_percent(int(share["percent"]), share["of"], counts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if (body.hosts or body.groups) and not include:
        raise HTTPException(status_code=400, detail="Aucune machine dans la selection")
    if include and not farm_targets.FLUX_HOST_TARGETING_VERIFIED:
        notes.append("Ciblage par nom de machine pas encore valide sur la farm (job test a faire)")
    own = _min_cap(settings["maxactive"], own)
    return service, own, own, notes


def _team_note(settings: dict) -> list[str]:
    note = farm_limits.team_warning(settings["tractor_project"], farm_limits.fetch_shares(settings["engine"]))
    return [note] if note else []


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
    if not simulate and user in tractor_bridge.ANONYMOUS_USERS:
        # Actions are allowed on a job only to the FLUX user written in it: an anonymous job would be everyone's.
        raise HTTPException(status_code=400, detail="Connecte-toi a FLUX (utilisateur) avant de lancer un rendu sur la farm")
    do_freeze = settings["freeze_by_default"] if body.freeze is None else body.freeze
    renderer = body.renderer or settings["renderer"]
    if not renderer:
        raise HTTPException(status_code=400, detail="Choisir un moteur de rendu (karma ou renderman) : "
                                                    "aucun par defaut dans les reglages ni l'environnement du studio")
    freeze_when = body.freeze_when or settings["freeze_when"]
    if freeze_when not in team_settings.FREEZE_WHEN:
        raise HTTPException(status_code=400, detail=f"freeze_when inconnu : {freeze_when}")
    # Scheduled job: freeze on the blade when it starts (latest LAST then), not now. Immediate: same thing, freeze now.
    at_start = do_freeze and bool(body.start_at) and freeze_when == "start"

    if not body.usd_path and not (body.seq and body.shot):
        raise HTTPException(status_code=400, detail="Choisir un shot ou un USD publie")
    rng = None
    if body.usd_path:
        # A published USD, or a stage written by the Houdini HDA (with its shot).
        usd = Path(body.usd_path)
        if not usd.is_file():
            raise HTTPException(status_code=404, detail=f"USD introuvable : {usd}")
        frozen = freeze.freeze_usd(usd, freeze=do_freeze and not at_start)
        name, folder, rng = usd.stem.replace("_LAST", ""), usd.parent, _usd_range(usd)
    if body.seq and body.shot:
        seq, shot = body.seq.upper(), body.shot.upper()
        if not body.usd_path:
            try:
                if at_start:
                    frozen = freeze.live_shot(root, seq, shot, user=user)
                else:
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

    # Published shot: its render layer's settings (ADR 0060). A stage from the HDA keeps Houdini's.
    render_settings = ""
    if not body.usd_path:
        from features.usd_assembler.shot_render import stage_settings

        render_settings = stage_settings(Path(frozen["usd"]), renderer)
    priority = settings["priority"] if body.priority is None else body.priority
    if not isinstance(priority, int) or not 1 <= priority <= 10000:
        raise HTTPException(status_code=400, detail="Priorite entre 1 et 10000")
    if body.denoise and renderer != "renderman":
        raise HTTPException(status_code=400, detail="Denoise apres rendu : RenderMan seulement (Karma : denoiser dans ses reglages)")
    try:
        if body.denoise:
            team_settings.require_denoise(settings)
        if at_start:
            team_settings.require_houdini(settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    service, maxactive, own_cap, notes = _targeting(body, settings, renderer, user)
    if body.denoise and render_settings:
        # ADR 0060: the generated render layer has the beauty only, not RenderMan's denoise AOVs.
        notes.append("Denoise : le stage publie n'a que la beaute (pas les AOV de denoise RenderMan), "
                     "le denoise risque d'echouer. Lancer depuis Houdini (Entree LOP) avec les AOV de denoise.")
    out_dir = freeze.reserve_render_dir(folder)
    render_usd = _farm(frozen["usd"], "Le USD", simulate)
    freeze_at_start = {}
    if at_start:
        # The blade writes <name>_frozen.usda in _job, the chunks render it.
        script = freeze.copy_freeze_script(out_dir / "_job")
        freeze_at_start = {
            "freeze_source": render_usd,
            "freeze_script": _farm(script, "Le script de gel", simulate),
            "freeze_python": settings["blade_tractor_python"],
            "freeze_houdini": settings["houdini_path"],
        }
        render_usd = _farm(out_dir / "_job" / f"{name}_frozen.usda", "Le dossier de rendu", simulate)
    spec = job_builder.RenderJobSpec(
        title=f"{body.project} {name} {out_dir.name}",
        project=settings["tractor_project"],
        user=user,
        usd_path=render_usd,
        render_settings=render_settings,
        **freeze_at_start,
        denoise=body.denoise,
        denoise_exe=settings["denoise_path"],
        denoise_tag=settings["denoise_tag"],
        forbid_drive_letters=settings["forbid_drive_letters"],
        denoise_crossframe=settings["denoise_crossframe"] if body.denoise_crossframe is None else body.denoise_crossframe,
        output_pattern=_farm(out_dir / f"{name}.$F4.exr", "Le dossier de rendu", simulate),
        frame_start=start,
        frame_end=end,
        renderer=renderer,
        chunk_size=body.chunk_size or settings["chunk_size"],
        priority=priority,
        maxactive=maxactive,
        service=service,
        envkeys=settings["envkeys"],
        husk=settings["husk_path"],
        max_task_minutes=settings["max_task_minutes"],
        retry_exit_codes=settings["retry_exit_codes"],
        start_after=body.start_at or "",
        metadata={"flux_project": body.project, "entity": name, "user": user, "cap": str(own_cap),
                  "output": _farm(out_dir, "Le dossier de rendu", simulate), "frozen": "start" if at_start else ("1" if frozen["frozen"] else "0")},
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
    return {**result, "title": spec.title, "output": str(out_dir), "usd": spec.usd_path if at_start else frozen["usd"],
            "frozen": frozen["frozen"] or at_start, "freeze_when": "start" if at_start else "submit",
            "frames": [start, end], "start_at": spec.start_after,
            "denoise": str(out_dir / job_builder.DENOISE_DIR) if spec.denoise else None,
            "service": service, "maxactive": maxactive, "warnings": frozen["warnings"] + notes + _team_note(settings),
            "priority": priority, "priority_warning": team_settings.priority_warning({**settings, "priority": priority})}


_SUBMIT_LOCK = threading.Lock()
_SUBMIT_WINDOW_S = 600
_SUBMIT_MAX = 10  # per backend and per 10 minutes: never flood the engine (2026-10-23)
_submits: list[float] = []


def _guarded_submit(body, user: str, run=None) -> dict:
    """One submit at a time per backend, and a rate cap (a double click or a loop never floods the farm).
    run: the submit to guard (render by default, or the denoise of a rendered sequence)."""
    if not _SUBMIT_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Un lancement est deja en cours, attendre la fin")
    try:
        now = time.time()
        _submits[:] = [t for t in _submits if now - t < _SUBMIT_WINDOW_S]
        if len(_submits) >= _SUBMIT_MAX:
            raise HTTPException(status_code=429, detail=(
                f"Trop de lancements ({_SUBMIT_MAX} en {_SUBMIT_WINDOW_S // 60} min) : attendre un peu"))
        result = (run or _submit)(body, user)
        if not result.get("dry_run"):
            _submits.append(now)
        return result
    finally:
        _SUBMIT_LOCK.release()


@router.post("/submit")
async def submit(body: SubmitBody):
    # Freezing writes a stage version and audits USD dependencies: off the event loop.
    return await asyncio.to_thread(_guarded_submit, body, _user())


# ── denoise of an already rendered sequence (2026-10-23) ─────────────────

class DenoiseBody(BaseModel):
    project: str
    path: str                            # one frame, a pattern (####, $F4) or the folder of the sequence
    frame_start: Optional[int] = None    # None = first frame found
    frame_end: Optional[int] = None
    crossframe: Optional[bool] = None    # None = team default
    priority: Optional[int] = None
    chunk_size: Optional[int] = None


def _denoise_sequence(body: DenoiseBody, user: str) -> dict:
    from features.render import image_sequence

    _ensure_project(body.project)
    settings = team_settings.effective_settings(body.project)
    simulate = settings["dry_run"] is True
    if not simulate and user in tractor_bridge.ANONYMOUS_USERS:
        raise HTTPException(status_code=400, detail="Connecte-toi a FLUX (utilisateur) avant de lancer un denoise sur la farm")
    try:
        team_settings.require_denoise(settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        seq = image_sequence.find(body.path)
    except image_sequence.SequenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    start = seq["first"] if body.frame_start is None else body.frame_start
    end = seq["last"] if body.frame_end is None else body.frame_end
    if start > end or start < seq["first"] or end > seq["last"]:
        raise HTTPException(status_code=400, detail=f"Plage {start}-{end} hors de la sequence ({seq['first']}-{seq['last']})")
    holes = [f for f in seq["missing"] if start <= f <= end]
    if holes:
        shown = ", ".join(str(f) for f in holes[:10]) + (" ..." if len(holes) > 10 else "")
        raise HTTPException(status_code=400, detail=f"Images manquantes dans la sequence : {shown}")
    priority = settings["priority"] if body.priority is None else body.priority
    if not isinstance(priority, int) or not 1 <= priority <= 10000:
        raise HTTPException(status_code=400, detail="Priorite entre 1 et 10000")
    folder = seq["folder"]
    try:
        service = farm_targets.service_expression(settings["service_renderman"], [], settings["exclude_hosts"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    out = folder / job_builder.DENOISE_DIR
    stem = seq["pattern"].split("$F")[0].rstrip("._") or folder.name
    spec = job_builder.RenderJobSpec(
        title=f"{body.project} denoise {stem} {folder.name}",
        project=settings["tractor_project"],
        user=user,
        usd_path="",
        output_pattern=_farm(folder, "La sequence", simulate) + "/" + seq["pattern"],
        frame_start=start,
        frame_end=end,
        renderer="renderman",
        chunk_size=body.chunk_size or settings["chunk_size"],
        priority=priority,
        service=service,
        envkeys=settings["envkeys"],
        denoise_only=True,
        denoise_exe=settings["denoise_path"],
        denoise_tag=settings["denoise_tag"],
        forbid_drive_letters=settings["forbid_drive_letters"],
        denoise_crossframe=settings["denoise_crossframe"] if body.crossframe is None else body.crossframe,
        metadata={"flux_project": body.project, "entity": stem, "user": user, "kind": "denoise",
                  "output": _farm(out, "Le dossier denoised", simulate)},
    )
    try:
        result = tractor_bridge.spool(spec, settings, user, out / "_job")
    except job_builder.JobValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)
    if result.get("jid") is not None:
        _running[int(result["jid"])] = {"project": body.project, "title": spec.title,
                                        "output": str(out), "user": user, "seen": time.time()}
    log.info("Denoise %s %s -> %s", "simulated" if result["dry_run"] else "spooled", spec.title, result.get("jid"))
    return {**result, "title": spec.title, "output": str(out), "frames": [start, end], "count": end - start + 1,
            "pattern": seq["pattern"], "warnings": _team_note(settings),
            "priority_warning": team_settings.priority_warning({**settings, "priority": priority})}


@router.post("/denoise")
async def denoise(body: DenoiseBody):
    return await asyncio.to_thread(_guarded_submit, body, _user(), _denoise_sequence)


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
    _record_exit_codes(project, settings, user, out.get("jobs", []))
    return out


_CODES_EVERY_S = 60.0
_codes_at: dict[str, float] = {}


def _record_exit_codes(project: str, settings: dict, user: str, jobs: list[dict], force: bool = False) -> None:
    """Keep the exit codes of the team's failed FLUX renders (one engine read per minute at most, never fails)."""
    if not force and time.time() - _codes_at.get(project, 0.0) < _CODES_EVERY_S:
        return
    try:
        todo = exit_codes.jobs_to_check(project, jobs, settings["tractor_project"])
        if not todo:
            return
        _codes_at[project] = time.time()
        found = tractor_bridge.exit_codes(settings, user, [j["jid"] for j in todo])
        exit_codes.record(project, todo, found)
    except Exception as exc:  # noqa: BLE001 - a side record never fails the poll
        log.warning("Render exit codes not recorded: %s", exc)


def _exit_codes(project: str, user: str) -> dict:
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    warning = None
    try:
        listing = tractor_bridge.jobs(settings, user, days=90, project=settings["tractor_project"])
        _record_exit_codes(project, settings, user, listing.get("jobs", []), force=True)
    except tractor_bridge.BridgeError as exc:
        warning = f"Farm indisponible ({exc}) : codes deja enregistres seulement"
    return {"codes": exit_codes.suggestions(project, settings["retry_exit_codes"]), "warning": warning}


@router.get("/exit_codes")
async def get_exit_codes(project: str):
    return await asyncio.to_thread(_exit_codes, project, _user())


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


# No FLUX team cap any more (2026-10-23): the school's Shares (engine limits.config) share the farm,
# FLUX never rewrites a job's maxactive. render.json may still hold "team_cap": read, never applied.

def _farm_state(project: str, user: str) -> dict:
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    try:
        out = dict(_farm_snapshot(settings, user))
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


def _tractor_projects(project: str, user: str) -> dict:
    """Tractor projects (teams) seen on the engine in the last 90 days, most used first, to pre-fill the setting."""
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    try:
        listing = tractor_bridge.jobs(settings, user, days=90)
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)
    seen: dict[str, int] = {}
    for j in listing.get("jobs", []):
        for p in j.get("projects") or []:
            if isinstance(p, str) and p.strip():
                seen[p] = seen.get(p, 0) + 1
    names = sorted(seen, key=lambda p: (-seen[p], p))
    return {"projects": [{"name": p, "jobs": seen[p]} for p in names], "current": settings["tractor_project"]}


@router.get("/tractor_projects")
async def tractor_projects(project: str):
    return await asyncio.to_thread(_tractor_projects, project, _user())


def _action(project: str, jid: int, action: str, user: str) -> dict:
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    try:
        return tractor_bridge.job_action(action, settings, user, jid)
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)


class PriorityBody(BaseModel):
    priority: int


def _set_priority(project: str, jid: int, value: int, user: str) -> dict:
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    try:
        out = tractor_bridge.set_priority(settings, user, jid, value)
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)
    return {**out, "priority_warning": team_settings.priority_warning({**settings, "priority": value})}


# Declared before /jobs/{jid}/{action}: FastAPI matches routes in order.
@router.post("/jobs/{jid}/priority")
async def job_priority(jid: int, project: str, body: PriorityBody):
    return await asyncio.to_thread(_set_priority, project, jid, body.priority, _user())


@router.post("/jobs/{jid}/{action}")
async def job_action(jid: int, action: str, project: str):
    if action not in tractor_bridge.JOB_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Action inconnue : {action}")
    return await asyncio.to_thread(_action, project, jid, action, _user())


def _trace(project: str, jid: int, user: str) -> dict:
    _ensure_project(project)
    settings = team_settings.effective_settings(project)
    try:
        return tractor_bridge.trace(settings, user, jid)
    except tractor_bridge.BridgeError as exc:
        raise _bridge_error(exc)


@router.get("/jobs/{jid}/trace")
async def job_trace(jid: int, project: str):
    return await asyncio.to_thread(_trace, project, jid, _user())


# ── studio environment: the link in CONFIG/studio.json and the file it points to (ADR 0063) ──
# Role lead or supervisor ("project_settings") to change anything. Reading is open to the project.

class StudioEnvBody(BaseModel):
    name: Optional[str] = None
    farm: Optional[dict] = None


class StudioEnvLink(BaseModel):
    link: str = ""
    create: bool = False  # create the file (empty environment) when the link points to nothing yet


def _studio_env_state() -> dict:
    from core import studio_config

    link = studio_config.read_studio()["environment"]
    path = studio_config.environment_path()
    env = studio_env.read_environment(path) if path else studio_env.read_environment(None)
    try:
        exists = bool(path and path.is_file())
    except OSError:
        exists = False
    return {"link": link, "path": str(path) if path else "", "exists": exists, "name": env["name"],
            "values": env["farm"], "defaults": studio_env.FARM_DEFAULTS}


@router.get("/studio-env")
def get_studio_env(project: str):
    _ensure_project(project)
    return _studio_env_state()


@router.put("/studio-env")
def put_studio_env(project: str, body: StudioEnvBody):
    _ensure_project(project)
    _require(project, "project_settings")
    patch = {k: v for k, v in (("name", body.name), ("farm", body.farm)) if v is not None}
    try:
        studio_env.write_environment(patch)
    except studio_env.StudioEnvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log.warning("Studio environment changed by %s (%s)", _user(), project)
    _snapshot.clear()
    return _studio_env_state()


@router.put("/studio-env/link")
def put_studio_env_link(project: str, body: StudioEnvLink):
    from core import studio_config
    from core.json_manager import write_json

    _ensure_project(project)
    _require(project, "project_settings")
    try:
        target = studio_config.resolve_link(body.link)
        if target is not None and not target.is_file():
            if not body.create:
                raise HTTPException(status_code=400, detail=f"Fichier d'environnement introuvable : {target}")
            if not write_json(target, studio_env.DEFAULTS):
                raise HTTPException(status_code=400, detail=f"Creation impossible : {target}")
        studio_config.write_studio({"environment": body.link})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=f"Dossier FLUX_ROOT non configure : {exc}")
    log.warning("Studio environment link changed by %s (%s)", _user(), project)
    _snapshot.clear()
    return _studio_env_state()
