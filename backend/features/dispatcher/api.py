# api.py — entry points of the dispatcher (ADR 0067), used by the Dispatcher nodes and the
# ForEach dispatch mode of the Flows engine.
#
# submit: the backend comes from the config of the pipe (overridden by the project); every
# task program is resolved through config.programs (white list). status / cancel: the
# backend is the prefix of the job_id ("local:..", "tractor:.."), so a job keeps its backend
# even if the config changes after it was sent.

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from features.dispatcher import config as dconfig
from features.dispatcher import local_backend, tractor_backend
from features.dispatcher.jobs import DispatchError, DispatchJob, DispatchTask, split_id

_BACKENDS = {"local": local_backend, "tractor": tractor_backend}


def effective_config(project_path: Optional[Path]) -> Dict[str, Any]:
    try:
        return dconfig.load(project_path)
    except dconfig.ConfigError as exc:
        raise DispatchError(str(exc)) from None


def backend_name(project_path: Optional[Path]) -> str:
    return effective_config(project_path)["backend"]


def farm_path(path: Any, project_path: Optional[Path], project: str) -> str:
    """*path* as the tasks of the current backend will see it."""
    name = backend_name(project_path)
    return tractor_backend.farm_path(path, project) if name == "tractor" else local_backend.farm_path(path)


def submit(job: DispatchJob, project_path: Optional[Path]) -> Dict[str, Any]:
    if not job.tasks:
        raise DispatchError("Job sans tache : rien a envoyer")
    cfg = effective_config(project_path)
    name = cfg["backend"]
    try:
        argvs: List[List[str]] = [[dconfig.program(cfg, t.program, name), *[str(a) for a in t.args]]
                                  for t in job.tasks]
    except dconfig.ConfigError as exc:
        raise DispatchError(str(exc)) from None
    result = _BACKENDS[name].submit(job, argvs, cfg)
    return {**result, "backend": name}


def _backend(job_id: str):
    name, raw = split_id(job_id)
    if name not in _BACKENDS:
        raise DispatchError(f"Backend `{name}` inconnu pour le job {job_id}")
    return name, raw


def status(job_id: str, project: str = "", user: str = "") -> Dict[str, Any]:
    name, raw = _backend(job_id)
    return local_backend.status(raw) if name == "local" else tractor_backend.status(raw, project, user)


def cancel(job_id: str, project: str = "", user: str = "") -> Dict[str, Any]:
    name, raw = _backend(job_id)
    return local_backend.cancel(raw) if name == "local" else tractor_backend.cancel(raw, project, user)


def task(title: str, program: str, args: List[Any], cwd: str = "") -> DispatchTask:
    return DispatchTask(title=str(title), program=str(program), args=[str(a) for a in args], cwd=str(cwd or ""))
