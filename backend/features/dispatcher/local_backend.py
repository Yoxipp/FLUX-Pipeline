# local_backend.py — dispatcher backend "local": the tasks run on this workstation (ADR 0067).
#
# One worker thread per job; at most config.local.max_parallel tasks run at once on the
# whole backend (one shared semaphore). Each task = one subprocess (argument list, never a
# shell). The jobs live in the memory of the FLUX backend: lost when it restarts.
# Cancel: no new task starts, the running ones are terminated.

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from features.dispatcher.jobs import DispatchError, DispatchJob, counts

NAME = "local"
LOG_TAIL = 4000                     # characters of output kept per task

_LOCK = threading.RLock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_SLOTS: Dict[str, Any] = {"n": 0, "sem": None}


def _semaphore(n: int) -> threading.Semaphore:
    with _LOCK:
        if _SLOTS["sem"] is None or _SLOTS["n"] != n:
            _SLOTS["n"], _SLOTS["sem"] = n, threading.BoundedSemaphore(n)
        return _SLOTS["sem"]


def _executable(exe: str) -> str:
    found = exe if Path(exe).is_file() else shutil.which(exe)
    if not found:
        raise DispatchError(f"`{exe}` introuvable sur ce poste : mets son chemin complet dans `programs` de "
                            "CONFIG/dispatcher.json")
    return found


def _start_time(start_after: str) -> Optional[float]:
    if not start_after:
        return None
    try:
        return datetime.strptime(start_after[:16], "%Y-%m-%dT%H:%M").timestamp()
    except ValueError:
        raise DispatchError(f"date de lancement invalide : `{start_after}` (attendu AAAA-MM-JJTHH:MM)") from None


def farm_path(path: Any) -> str:
    return str(path)


def submit(job: DispatchJob, argvs: List[List[str]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Start *job*; *argvs* = one resolved argument list per task (program first)."""
    argvs = [[_executable(a[0]), *a[1:]] for a in argvs]
    at = _start_time(job.start_after)
    raw = uuid.uuid4().hex[:10]
    record = {"id": raw, "title": job.title, "user": job.user, "project": job.project, "state": "waiting",
              "cancel": threading.Event(), "procs": {},
              "tasks": [{"title": t.title, "argv": argv, "cwd": t.cwd, "state": "waiting", "returncode": None,
                         "log": ""} for t, argv in zip(job.tasks, argvs)]}
    with _LOCK:
        _JOBS[raw] = record
    sem = _semaphore(int(cfg.get("local", {}).get("max_parallel", 2)))
    threading.Thread(target=_work, args=(record, sem, at), name=f"dispatch-{raw}", daemon=True).start()
    return {"job_id": f"{NAME}:{raw}", "dry_run": False, "tasks": len(argvs)}


def _run_task(record: Dict[str, Any], index: int) -> None:
    task = record["tasks"][index]
    task["state"] = "active"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(task["argv"], cwd=task["cwd"] or None, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace", creationflags=flags)
    except OSError as exc:
        task.update(state="error", log=f"lancement impossible : {exc}")
        return
    record["procs"][index] = proc
    out, _ = proc.communicate()
    record["procs"].pop(index, None)
    task["log"] = (out or "")[-LOG_TAIL:]
    task["returncode"] = proc.returncode
    if record["cancel"].is_set():
        task["state"] = "cancelled"
    else:
        task["state"] = "done" if proc.returncode == 0 else "error"


def _work(record: Dict[str, Any], sem: threading.Semaphore, at: Optional[float]) -> None:
    cancel: threading.Event = record["cancel"]
    if at is not None:
        while not cancel.is_set() and time.time() < at:
            cancel.wait(min(30.0, max(0.1, at - time.time())))
    threads = []
    for index in range(len(record["tasks"])):
        sem.acquire()
        if cancel.is_set():
            sem.release()
            break
        record["state"] = "active"

        def run(i=index):
            try:
                _run_task(record, i)
            finally:
                sem.release()

        th = threading.Thread(target=run, daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    for task in record["tasks"]:
        if task["state"] == "waiting":
            task["state"] = "cancelled"
    states = {t["state"] for t in record["tasks"]}
    record["state"] = ("cancelled" if cancel.is_set() else "error" if "error" in states else "done")


def _record(raw: str) -> Dict[str, Any]:
    with _LOCK:
        record = _JOBS.get(raw)
    if record is None:
        raise DispatchError(f"Job local `{raw}` inconnu : les jobs locaux sont perdus au redemarrage de FLUX")
    return record


def status(raw: str) -> Dict[str, Any]:
    record = _record(raw)
    tasks = [{k: t[k] for k in ("title", "state", "returncode", "log")} for t in record["tasks"]]
    return {"job_id": f"{NAME}:{raw}", "state": record["state"], "tasks": tasks, **counts(tasks)}


def cancel(raw: str) -> Dict[str, Any]:
    record = _record(raw)
    record["cancel"].set()
    for proc in list(record["procs"].values()):
        try:
            proc.terminate()
        except OSError:
            pass
    return {"job_id": f"{NAME}:{raw}", "cancelled": True}


def reset() -> None:
    """Tests: forget every job."""
    with _LOCK:
        _JOBS.clear()
