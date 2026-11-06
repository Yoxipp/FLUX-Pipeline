# jobs.py — a dispatcher job, independent of the farm manager (ADR 0067).
#
# A job is a list of tasks; a task starts one declared program (config.programs) with a
# list of arguments, never through a shell. States are the same for every backend:
# waiting, active, done, error, cancelled, and simulated (a dry run backend: nothing ran).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

STATES = ("waiting", "active", "done", "error", "cancelled", "simulated")
FINAL_STATES = ("done", "error", "cancelled", "simulated")


class DispatchError(RuntimeError):
    """A job cannot be sent, read or cancelled. The message says what to do."""


@dataclass
class DispatchTask:
    title: str
    program: str                   # a key of config.programs
    args: List[str] = field(default_factory=list)
    cwd: str = ""


@dataclass
class DispatchJob:
    title: str
    user: str
    project: str                   # FLUX project name ("" = none)
    tasks: List[DispatchTask] = field(default_factory=list)
    priority: int = 100
    start_after: str = ""          # "YYYY-MM-DDTHH:MM" local time, empty = now
    service: str = ""              # farm blade selection (Tractor service key), empty = any
    metadata: Dict[str, str] = field(default_factory=dict)
    record_dir: str = ""           # where the job files (.alf, .json) are written, empty = backend default


def split_id(job_id: str):
    """("local", "a1b2") from "local:a1b2"; refuses an id without its backend."""
    backend, sep, raw = str(job_id or "").partition(":")
    if not sep or not raw:
        raise DispatchError(f"job_id `{job_id}` invalide : attendu <backend>:<id> (sortie job_id de Submit)")
    return backend, raw


def counts(tasks: List[dict]) -> Dict[str, int]:
    total = len(tasks)
    return {"total": total, "done": sum(1 for t in tasks if t.get("state") == "done"),
            "errors": sum(1 for t in tasks if t.get("state") == "error")}
