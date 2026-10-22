# -*- coding: utf-8 -*-
"""FLUX to Tractor bridge (ADR 0015). Runs with Tractor's own Python 2.7.

The FLUX backend never imports the Tractor API: it starts this script as a
subprocess, writes one JSON request on stdin and reads one JSON answer on
stdout:  {"ok": true, "result": {...}}  or  {"ok": false, "error": "..."}.

Must stay valid Python 2.7 AND 3 (no f-strings, no annotations).

TO VERIFY AT SCHOOL (phase 0, TOM_RETAKES/ECOLE_ENV.md): every Tractor call
is in the TRACTOR section below (query API names, job columns, tractor-spool
output). Nothing here was run against a real engine yet.
"""
from __future__ import print_function

import json
import re
import subprocess
import sys

try:
    basestring_ = basestring  # noqa: F821 (Python 2.7)
except NameError:
    basestring_ = str

# ── TRACTOR (only place that touches the Tractor API) ────────────────────────

JOB_COLUMNS = ["jid", "title", "owner", "projects", "priority", "numtasks",
               "numdone", "numerror", "numactive", "numblocked", "numready",
               "spooltime", "stoptime", "pausetime", "deletetime", "comment", "metadata"]
TASK_COLUMNS = ["jid", "tid", "title", "state", "service"]
BLADE_COLUMNS = ["name", "profile", "status", "nimby"]
LOG_TAIL = 20000
_JID = re.compile(r"jid[:= ]+(\d+)", re.IGNORECASE)


def _tq(req):
    import tractor.api.query as tq  # noqa: Tractor's Python only

    engine = req.get("engine") or ""
    # Login account (school 2026-10-22: only "root" logs in, as tq does), not the job owner.
    params = {"user": req.get("login") or req.get("user") or ""}
    if engine:
        host, _, port = engine.partition(":")
        params["hostname"] = host
        if port:
            params["port"] = int(port)
    tq.setEngineClientParam(**params)
    return tq


def _spool(req):
    cmd = [req.get("spool_cmd") or "tractor-spool"]
    if req.get("engine"):
        cmd.append("--engine=" + req["engine"])
    if req.get("user"):
        cmd.append("--user=" + req["user"])
    cmd.append(req["alf_path"])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate()[0].decode("utf-8", "replace")
    if proc.returncode != 0:
        raise RuntimeError("tractor-spool a echoue : " + out.strip()[-300:])
    match = _JID.search(out)
    return {"jid": int(match.group(1)) if match else None, "output": out.strip()}


def _str(value):
    return "" if value is None else str(value)


def _jobs(req):
    # Every state (active, error, done, paused), like the Dashboard: only the age bounds the list.
    if req.get("jid") is not None:
        clauses = ["jid=%d" % int(req["jid"])]
    else:
        clauses = ["spooltime > -%dd" % int(req.get("days") or 30)]
    if req.get("owner"):
        clauses.append("owner=" + req["owner"])
    if req.get("project"):
        clauses.append("projects like " + req["project"])
    rows = _tq(req).jobs(" and ".join(clauses), columns=JOB_COLUMNS, sortby=["-spooltime"],
                         limit=int(req.get("limit") or 500), archive=bool(req.get("archive")))
    jobs = []
    for r in rows:
        projects = r.get("projects") or []
        jobs.append({
            "jid": r.get("jid"), "title": r.get("title"), "user": r.get("owner"),
            "projects": projects if isinstance(projects, list) else [projects],
            "priority": r.get("priority"),
            "numTasks": r.get("numtasks"), "numDone": r.get("numdone"),
            "numError": r.get("numerror"), "numActive": r.get("numactive"),
            "numBlocked": r.get("numblocked"), "numReady": r.get("numready"),
            "spooltime": _str(r.get("spooltime")), "stoptime": _str(r.get("stoptime")),
            "pausetime": _str(r.get("pausetime")), "deletetime": _str(r.get("deletetime")),
            "comment": r.get("comment") or "", "metadata": r.get("metadata") or "",
        })
    return {"jobs": jobs}


def _tasks(req):
    rows = _tq(req).tasks("jid=%d" % int(req["jid"]), columns=TASK_COLUMNS)
    return {"tasks": [dict((k, r.get(k)) for k in TASK_COLUMNS) for r in rows]}


def _log(req):
    logs = _tq(req).log("jid=%d and tid=%d" % (int(req["jid"]), int(req["tid"])))
    text = ""
    for value in logs.values():
        text = value if isinstance(value, basestring_) else _str(value)
    return {"log": text[-LOG_TAIL:]}


def _blades(req):
    tq = _tq(req)
    blades = [dict((k, r.get(k)) for k in BLADE_COLUMNS) for r in tq.blades("name like .", columns=BLADE_COLUMNS)]
    active = {}
    for r in tq.jobs("numactive > 0", columns=["projects", "numactive"]):
        projects = r.get("projects") or ["(none)"]
        if not isinstance(projects, list):
            projects = [projects]
        for p in projects:
            active[p] = active.get(p, 0) + int(r.get("numactive") or 0)
    return {"blades": blades, "active_by_project": active}


def _job_op(name):
    def run(req):
        clause = "jid=" + str(int(req["jid"]))
        tq = _tq(req)
        if name == "kill":
            tq.interrupt(clause)  # stop running tasks
            tq.pause(clause)      # and keep the job from restarting
        elif name == "retry":
            tq.retry(clause + " and error")
        elif name == "pause":
            tq.pause(clause)
        elif name == "resume":
            tq.unpause(clause)
        return {"jid": int(req["jid"])}
    return run


def _ping(req):
    return {"version": sys.version.split()[0]}


# ── protocol ─────────────────────────────────────────────────────────────────

VERBS = {
    "spool": _spool, "jobs": _jobs, "tasks": _tasks, "log": _log, "blades": _blades, "ping": _ping,
    "kill": _job_op("kill"), "retry": _job_op("retry"),
    "pause": _job_op("pause"), "resume": _job_op("resume"),
}


def handle(req):
    verb = req.get("verb")
    if verb not in VERBS:
        return {"ok": False, "error": "verbe inconnu : %s" % verb}
    try:
        return {"ok": True, "result": VERBS[verb](req)}
    except Exception as exc:  # the backend only needs a readable message
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


def main():
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        req, answer = None, {"ok": False, "error": "requete illisible : %s" % exc}
    if req is not None:
        answer = handle(req)
    sys.stdout.write(json.dumps(answer))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
