# tractor_backend.py — dispatcher backend "tractor" (ADR 0067 over ADR 0015).
#
# A generic Alfred job: one Task / RemoteCmd per dispatcher task, with the guards of
# features/render/job_builder (Tcl-safe words, no drive letter in a real spool). The
# connection settings are those of the project render.json (team_settings): engine,
# bridge, Tractor project, envkeys, dry_run. While dry_run is on (school phase 0 not done),
# submit writes the .alf + .json and spools nothing; the job state is then "simulated".
# Status and cancel go through the existing bridge (cancel = kill, refused on a job this
# FLUX user did not spool, like the Render tab).

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from features.dispatcher.jobs import DispatchError, DispatchJob

NAME = "tractor"
SIMULATED_PREFIX = "sim-"
_STATE_MAP = {"active": "active", "error": "error", "done": "done", "waiting": "waiting", "paused": "waiting",
              "deleted": "cancelled"}


def _settings(project: str) -> Dict[str, Any]:
    if not project:
        raise DispatchError("Backend tractor : un projet est requis (reglages render.json du projet)")
    from features.render import team_settings

    return team_settings.effective_settings(project)


def _simulate(settings: Dict[str, Any]) -> bool:
    return settings.get("dry_run") is True


def farm_path(path: Any, project: str) -> str:
    """The path as the farm sees it (UNC). In simulation a local path is kept as is."""
    from features.render.farm_paths import to_farm_path

    text = str(path)
    found = to_farm_path(text)
    if found:
        return found
    if _simulate(_settings(project)):
        return text.replace("\\", "/")
    raise DispatchError(f"`{text}` n'est pas vu par la farm (disque local) : utilise un chemin du partage")


def _word(text: str, what: str, strict: bool) -> str:
    from features.render import job_builder as jb

    if _UNSAFE.search(text.replace("$F", "")):
        raise DispatchError(f"{what} : caractere non supporte dans `{text}` (accolades, crochets, antislash, $)")
    if strict and jb.is_drive_letter_path(text):
        raise DispatchError(f"{what} : `{text}` (lettre de lecteur) n'est pas vu par le compte de la farm, "
                            "utilise un chemin UNC")
    return text


_UNSAFE = re.compile(r"[{}\[\]$]")


def to_alf(job: DispatchJob, argvs: List[List[str]], settings: Dict[str, Any], strict: bool) -> str:
    """Alfred script: Job attributes as in job_builder.to_alf, one Task per dispatcher task."""
    from features.render import job_builder as jb

    argvs = [[_word(a.replace("\\", "/"), "commande", strict) for a in argv] for argv in argvs]
    title = _word(job.title, "titre", False)
    attrs = [f"-title {jb._tcl(title)}", f"-projects {jb._tcl(_word(settings['tractor_project'], 'projet', False))}",
             f"-priority {int(job.priority)}"]
    if int(settings.get("maxactive") or 0) > 0:
        attrs.append(f"-maxactive {int(settings['maxactive'])}")
    if job.start_after:
        try:
            attrs.append(f"-after {jb._tcl(jb.after_clause(job.start_after))}")
        except jb.JobValidationError as exc:
            raise DispatchError(str(exc)) from None
    if job.service:
        attrs.append(f"-service {jb._tcl(_word(job.service, 'service', False))}")
    envkeys = [_word(k, "envkey", False) for k in settings.get("envkeys") or []]
    if envkeys:
        attrs.append(f"-envkey {jb._tcl(' '.join(envkeys))}")
    meta = {str(k): _word(str(v), "metadata", False) for k, v in job.metadata.items()}
    if meta:
        attrs.append(f"-metadata {jb._tcl(json.dumps(meta, sort_keys=True))}")
    lines = ["##AlfredToDo 3.0", "Job " + " ".join(attrs) + " -subtasks {"]
    for task, argv in zip(job.tasks, argvs):
        service = f" -service {jb._tcl(job.service)}" if job.service else ""
        lines.append(f"    Task -title {jb._tcl(_word(task.title, 'tache', False))} -cmds {{")
        lines.append(f"        RemoteCmd {jb._tcl_cmd(argv)}{service}")
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _record_dir(job: DispatchJob) -> Path:
    if job.record_dir:
        return Path(job.record_dir)
    from core import paths
    from core.project_setup import setup_dir

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return setup_dir(paths.get_project_path(job.project)) / "dispatch" / stamp


def submit(job: DispatchJob, argvs: List[List[str]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    from features.render import tractor_bridge

    settings = _settings(job.project)
    simulate = _simulate(settings)
    job.metadata = {"flux_project": job.project, "user": job.user, **job.metadata}
    alf = to_alf(job, argvs, settings, strict=not simulate)
    folder = _record_dir(job)
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", job.title) or "job"
    alf_path, json_path = folder / f"{stem}.alf", folder / f"{stem}.json"
    alf_path.write_text(alf, encoding="utf-8")
    json_path.write_text(json.dumps({"title": job.title, "user": job.user, "project": job.project,
                                     "tasks": [{"title": t.title, "argv": a} for t, a in zip(job.tasks, argvs)]},
                                    indent=2), encoding="utf-8")
    files = {"alf": str(alf_path), "json": str(json_path)}
    if simulate:
        return {"job_id": f"{NAME}:{SIMULATED_PREFIX}{stem}", "dry_run": True, "tasks": len(argvs), "files": files}
    try:
        result = tractor_bridge.call("spool", settings, job.user, alf_path=str(alf_path))
    except tractor_bridge.BridgeError as exc:
        raise DispatchError(f"Tractor : {exc}") from None
    jid = result.get("jid")
    if jid is None:
        raise DispatchError(f"Tractor n'a pas rendu de numero de job ({result.get('output') or 'sans message'})")
    return {"job_id": f"{NAME}:{int(jid)}", "dry_run": False, "tasks": len(argvs), "files": files}


def status(raw: str, project: str, user: str) -> Dict[str, Any]:
    if raw.startswith(SIMULATED_PREFIX):
        return {"job_id": f"{NAME}:{raw}", "state": "simulated", "total": 0, "done": 0, "errors": 0, "tasks": []}
    from features.render import tractor_bridge

    settings = _settings(project)
    try:
        found = [j for j in tractor_bridge.call("jobs", settings, user, jid=int(raw)).get("jobs") or []
                 if isinstance(j, dict) and j.get("jid") == int(raw)]
    except (tractor_bridge.BridgeError, ValueError) as exc:
        raise DispatchError(f"Tractor : {exc}") from None
    if not found:
        return {"job_id": f"{NAME}:{raw}", "state": "cancelled", "total": 0, "done": 0, "errors": 0, "tasks": []}
    job = found[0]
    state = _STATE_MAP.get(tractor_bridge.job_state(job), "waiting")
    num = tractor_bridge._int
    return {"job_id": f"{NAME}:{raw}", "state": state, "total": num(job.get("numTasks")),
            "done": num(job.get("numDone")), "errors": num(job.get("numError")), "tasks": []}


def cancel(raw: str, project: str, user: str) -> Dict[str, Any]:
    if raw.startswith(SIMULATED_PREFIX):
        return {"job_id": f"{NAME}:{raw}", "cancelled": True, "dry_run": True}
    from features.render import tractor_bridge

    try:
        tractor_bridge.kill(_settings(project), user, int(raw))
    except (tractor_bridge.BridgeError, ValueError) as exc:
        raise DispatchError(f"Tractor : {exc}") from None
    return {"job_id": f"{NAME}:{raw}", "cancelled": True}
