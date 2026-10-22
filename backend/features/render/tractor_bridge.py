"""Client of the external Tractor bridge (ADR 0015).

The FLUX backend never imports the Tractor API (Python 2.7, proprietary). It runs
the bridge script with Tractor's own Python as a subprocess: one JSON object on
stdin, one JSON object on stdout.

  request : {"verb": str, "engine": "host:port", "user": str, ...verb args}
  response: {"ok": true, "result": {...}} or {"ok": false, "error": "message"}
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

from features.render import job_builder

VERBS = ("spool", "jobs", "tasks", "log", "blades", "kill", "retry", "pause", "resume", "ping")
_JID_VERBS = ("tasks", "log", "kill", "retry", "pause", "resume")
DEFAULT_LOGIN = "root"  # school engine 2026-10-22: only "root" logs in (as tq does), read only for FLUX
_DROPPED_ENV = ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE")
_STDERR_TAIL = 300
_SIMULATION_MSG = "Mode simulation : aucune action sur la farm"


class BridgeError(RuntimeError):
    """Raised when the Tractor bridge cannot answer (readable French message)."""


def _clean_env() -> Dict[str, str]:
    # Tractor's Python 2.7 must not see the backend's Python 3.
    env = dict(os.environ)
    for key in _DROPPED_ENV:
        env.pop(key, None)
    return env


def _check_configured(settings: dict) -> tuple:
    python = str(settings.get("bridge_python") or "").strip()
    script = str(settings.get("bridge_script") or "").strip()
    if not python or not script or not Path(python).is_file() or not Path(script).is_file():
        raise BridgeError("Pont Tractor non configure (reglages avances : python et script du pont)")
    return python, script


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def call(verb: str, settings: dict, user: str, timeout: int = 30, **args) -> dict:
    """Run one bridge verb and return its result dict. Raises BridgeError."""
    return _run(verb, settings, user, timeout, args)


def _run(verb: str, settings: dict, user: str, timeout: int, args: dict) -> dict:
    if verb not in VERBS:
        raise BridgeError(f"Verbe Tractor inconnu : {verb}")
    if verb in _JID_VERBS and not _is_int(args.get("jid")):
        raise BridgeError(f"Tractor : {verb} demande un numero de job (jid entier)")
    if verb == "spool" and not args.get("alf_path"):
        raise BridgeError("Tractor : spool demande un fichier .alf")
    python, script = _check_configured(settings)

    request = {"verb": verb, "engine": settings.get("engine") or "", "user": user or "",
               "login": settings.get("engine_user") or DEFAULT_LOGIN}
    request.update(args)
    kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}
    try:
        proc = subprocess.run(
            [python, script],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_clean_env(),
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        raise BridgeError(f"Pont Tractor : delai depasse ({timeout} s)") from None
    except OSError as exc:
        raise BridgeError(f"Pont Tractor : lancement impossible ({exc})") from exc

    try:
        response = json.loads(proc.stdout)
    except (ValueError, TypeError):
        response = None
    if not isinstance(response, dict) or "ok" not in response:
        tail = (proc.stderr or "").strip()[-_STDERR_TAIL:]
        msg = "Pont Tractor : reponse illisible"
        raise BridgeError(f"{msg} ({tail})" if tail else msg)
    if not response["ok"]:
        raise BridgeError("Tractor : " + str(response.get("error") or "erreur inconnue"))
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def spool(spec: job_builder.RenderJobSpec, settings: dict, user: str, out_dir: Path) -> dict:
    """Write the .alf + .json record, then spool it (unless dry_run)."""
    simulate = settings.get("dry_run") is True
    # A simulation may run on a local disk (home tests); a real spool needs UNC paths.
    files = job_builder.dry_run(spec, out_dir, strict=not simulate)
    if simulate:
        return {"dry_run": True, "jid": None, "files": files}
    result = call("spool", settings, user, alf_path=files["alf"])
    return {"dry_run": False, "jid": result.get("jid"), "files": files, "output": result.get("output", "")}


def is_configured(settings: dict) -> bool:
    try:
        _check_configured(settings)
    except BridgeError:
        return False
    return True


def _reads_off(settings: dict) -> bool:
    # Reads are harmless: they hit the real engine even in simulation, as soon as
    # the bridge is configured. Only spool and actions obey dry_run.
    return settings.get("dry_run") is True and not is_configured(settings)


def _metadata(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def job_state(job: dict) -> str:
    """One readable state per job, from Tractor's counters and timestamps."""
    if job.get("deletetime"):
        return "deleted"
    if job.get("pausetime"):
        return "paused"
    if _int(job.get("numActive")) > 0:
        return "active"
    if _int(job.get("numError")) > 0:
        return "error"
    total = _int(job.get("numTasks"))
    if total and _int(job.get("numDone")) >= total:
        return "done"
    return "waiting"


def _normalize(job: dict) -> dict:
    meta = _metadata(job.get("metadata"))
    out = dict(job)
    out["metadata"] = meta
    # Every school job is owned by the shared Windows login: the FLUX user lives in the metadata.
    out["flux_user"] = str(meta.get("user") or "")
    out["state"] = job_state(job)
    return out


def jobs(settings: dict, user: str, *, mine: bool = False, project: Optional[str] = None,
         days: int = 30, archive: bool = False) -> dict:
    """Every Tractor job of the last `days` days, any state (what the Dashboard shows)."""
    if _reads_off(settings):
        return {"jobs": [], "dry_run": True}
    result = call("jobs", settings, user, project=project, days=days, archive=archive)
    found = [_normalize(j) for j in result.get("jobs", []) if isinstance(j, dict)]
    if mine:
        found = [j for j in found if j["flux_user"] == user]
    return {"jobs": found, "dry_run": settings.get("dry_run") is True}


def tasks(settings: dict, user: str, jid: int) -> dict:
    if _reads_off(settings):
        return {"tasks": [], "dry_run": True}
    return call("tasks", settings, user, jid=jid)


def task_log(settings: dict, user: str, jid: int, tid: int) -> dict:
    if not _is_int(tid):
        raise BridgeError("Tractor : log demande un numero de tache (tid entier)")
    if _reads_off(settings):
        return {"log": "", "dry_run": True}
    return call("log", settings, user, jid=jid, tid=tid)


def blades(settings: dict, user: str) -> dict:
    if _reads_off(settings):
        return {"blades": [], "active_by_project": {}, "dry_run": True}
    return call("blades", settings, user)


def _action(verb: str, settings: dict, user: str, jid: int) -> dict:
    if settings.get("dry_run") is True:
        raise BridgeError(_SIMULATION_MSG)
    # FLUX logs in as an engine admin: only act on jobs this FLUX user spooled (2026-10-22).
    found = [j for j in call("jobs", settings, user, jid=jid).get("jobs") or []
             if isinstance(j, dict) and j.get("jid") == jid]
    if not found or not user or _normalize(found[0])["flux_user"] != user:
        raise BridgeError("Action refusee : ce job n'a pas ete lance par vous depuis FLUX")
    return call(verb, settings, user, jid=jid)


def kill(settings: dict, user: str, jid: int) -> dict:
    return _action("kill", settings, user, jid)


def retry(settings: dict, user: str, jid: int) -> dict:
    return _action("retry", settings, user, jid)


def pause(settings: dict, user: str, jid: int) -> dict:
    return _action("pause", settings, user, jid)


def resume(settings: dict, user: str, jid: int) -> dict:
    return _action("resume", settings, user, jid)

