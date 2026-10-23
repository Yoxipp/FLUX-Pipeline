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
import os
import re
import subprocess
import sys

try:
    basestring_ = basestring  # noqa: F821 (Python 2.7)
except NameError:
    basestring_ = str

# ── TRACTOR (only place that touches the Tractor API) ────────────────────────

JOB_COLUMNS = ["jid", "title", "owner", "projects", "priority", "maxactive", "numtasks",
               "numdone", "numerror", "numactive", "numblocked", "numready",
               "spooltime", "stoptime", "pausetime", "deletetime", "comment", "metadata"]
# progress: 0-100 of an active task, from the ALF_PROGRESS lines its command prints (husk -Va1).
TASK_COLUMNS = ["jid", "tid", "title", "state", "service", "progress"]
BLADE_COLUMNS = ["bladeid", "name", "profile", "status", "nimby", "heartbeattime", "numslots"]
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
    if not req.get("review") and not req.get("spool_cmd"):
        return _spool_api(req)
    # Review (parse only, nothing sent): tractor-spool.bat only runs "rmanpy -m tractor.apps.spooler",
    # so call it with this same Python (a .bat cannot be started without a shell).
    cmd = [req["spool_cmd"]] if req.get("spool_cmd") else [sys.executable, "-m", "tractor.apps.spooler"]
    if req.get("engine"):
        cmd.append("--engine=" + req["engine"])
    cmd.append("--no-spool" if req.get("review") else "--status-json")
    cmd.append(req["alf_path"])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate()[0].decode("utf-8", "replace")
    if proc.returncode != 0:
        raise RuntimeError("tractor-spool a echoue : " + out.strip()[-300:])
    jid = None
    for line in out.splitlines():
        try:
            status = json.loads(line)
        except ValueError:
            continue
        if isinstance(status, dict) and status.get("jid"):
            jid = int(status["jid"])
    if jid is None:
        match = _JID.search(out)
        jid = int(match.group(1)) if match else None
    return {"jid": jid, "output": out.strip()[-2000:]}


def _spool_api(req):
    # Same path as the school's Nuke submitter (EngineClient.spool). tractor-spool cannot be used:
    # it writes the owner unquoted in its JSON and the school login "3d1" starts with a digit
    # ("Invalid JSON generated from job script parse", 2026-10-23). Owner = the Windows login,
    # like every other job; the FLUX user is in the job metadata.
    import getpass
    import socket
    import tractor.api.author.base as author  # noqa: Tractor's Python only

    client = author.ModuleEngineClient
    engine = req.get("engine") or ""
    if engine:
        host, _, port = engine.partition(":")
        client.conn = None  # new connection to this engine (see author.base Job.spool)
        client.setParam(hostname=host)
        if port:
            client.setParam(port=int(port))
    with open(req["alf_path"]) as handle:
        script = handle.read()
    result = client.spool(script, skipLogin=True, block=True, owner=getpass.getuser(),
                          filename=req["alf_path"], hostname=socket.gethostname())
    status = json.loads(result) if isinstance(result, basestring_) else (result or {})
    jid = status.get("jid") if isinstance(status, dict) else None
    if not jid:
        raise RuntimeError("spool refuse par le moteur : %s" % _str(result)[-300:])
    return {"jid": int(jid), "output": _str(result)[-2000:]}


def _str(value):
    return "" if value is None else str(value)


def _running(tq):
    """Commands running now (one per busy slot). "current" = the LATEST invocation of each command,
    finished ones included (school 2026-10-23): only those without a stop time are running."""
    rows = tq.invocations("current", columns=["bladeid", "jid", "stoptime"])
    return [r for r in rows if not r.get("stoptime")]


def _jobs(req):
    # Every state (active, error, done, paused), like the Dashboard: only the age bounds the list.
    tq = _tq(req)
    running = {}
    for inv in _running(tq):
        running[inv.get("jid")] = running.get(inv.get("jid"), 0) + 1
    if req.get("jid") is not None:
        clauses = ["jid=%d" % int(req["jid"])]
    else:
        clauses = ["spooltime > -%dd" % int(req.get("days") or 30)]
    if req.get("owner"):
        clauses.append("owner=" + req["owner"])
    if req.get("project"):
        clauses.append("projects like " + req["project"])
    rows = tq.jobs(" and ".join(clauses), columns=JOB_COLUMNS, sortby=["-spooltime"],
                         limit=int(req.get("limit") or 500), archive=bool(req.get("archive")))
    progress = _active_progress(tq, [r.get("jid") for r in rows if running.get(r.get("jid"))])
    jobs = []
    for r in rows:
        projects = r.get("projects") or []
        jobs.append({
            "jid": r.get("jid"), "title": r.get("title"), "user": r.get("owner"),
            "projects": projects if isinstance(projects, list) else [projects],
            "priority": r.get("priority"), "maxactive": r.get("maxactive") or 0,
            "numTasks": r.get("numtasks"), "numDone": r.get("numdone"),
            "numError": r.get("numerror"),
            "numActive": max(int(r.get("numactive") or 0), running.get(r.get("jid"), 0)),
            "numBlocked": r.get("numblocked"), "numReady": r.get("numready"),
            "spooltime": _str(r.get("spooltime")), "stoptime": _str(r.get("stoptime")),
            "pausetime": _str(r.get("pausetime")), "deletetime": _str(r.get("deletetime")),
            "comment": r.get("comment") or "", "metadata": r.get("metadata") or "",
            "activeProgress": progress.get(r.get("jid"), 0),
        })
    return {"jobs": jobs}


def _active_progress(tq, jids):
    """{jid: sum of the % of its active tasks} for running jobs only (one query, none when idle)."""
    jids = sorted(set(int(j) for j in jids if j is not None))
    if not jids:
        return {}
    out = {}
    clause = "jid in [%s] and state=active" % ",".join(str(j) for j in jids)
    for r in tq.tasks(clause, columns=["jid", "progress"]):
        try:
            value = float(r.get("progress") or 0)
        except (TypeError, ValueError):
            continue
        out[r.get("jid")] = out.get(r.get("jid"), 0) + max(0.0, min(100.0, value))
    return out


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
    rows = tq.blades("name like .", columns=BLADE_COLUMNS)
    names = dict((r.get("bladeid"), r.get("name")) for r in rows)
    running = _running(tq)
    jids = sorted(set(inv.get("jid") for inv in running if inv.get("jid") is not None))
    projects_of = {}
    if jids:
        clause = "jid in [%s]" % ",".join(str(int(j)) for j in jids)
        for r in tq.jobs(clause, columns=["jid", "projects"]):
            projects = r.get("projects") or ["(none)"]
            projects_of[r.get("jid")] = projects if isinstance(projects, list) else [projects]
    active = {}
    busy = {}
    for inv in running:
        projects = projects_of.get(inv.get("jid"), ["(none)"])
        for p in projects:
            active[p] = active.get(p, 0) + 1
        name = names.get(inv.get("bladeid"))
        if name:
            busy[name] = {"jid": inv.get("jid"), "project": projects[0]}
    blades = []
    for r in rows:
        blade = dict((k, _str(r.get(k)) if k == "heartbeattime" else r.get(k)) for k in BLADE_COLUMNS if k != "bladeid")
        blade["busy"] = busy.get(r.get("name"))
        blades.append(blade)
    return {"blades": blades, "active_by_project": active}


def _one_job(tq, jid, archive=False):
    """[{"jid": jid}] after checking the job exists. Every write passes this exact list, never a
    search clause: a Tractor operation applies to everything its search matches."""
    jid = int(jid)
    found = [r for r in tq.jobs("jid=%d" % jid, columns=["jid"], limit=2, archive=archive) if r.get("jid") == jid]
    if len(found) != 1:
        raise ValueError("job %d introuvable" % jid)
    return [{"jid": jid}]


def _maxactive(req):
    # Team cap balancing (FLUX jobs of the team only, checked by the backend): change a job's maxactive.
    value = int(req["value"])
    if value < 0:
        raise ValueError("maxactive >= 0")
    tq = _tq(req)
    tq.jattr(_one_job(tq, req["jid"]), key="maxactive", value=value)
    return {"jid": int(req["jid"]), "maxactive": value}


def _engine_client():
    import tractor.api.query.base as qbase  # noqa: Tractor's Python only
    return qbase.ModuleEngineClient


def _job_op(name):
    # Same calls as the Dashboard job menu (Tractor 2.4 EngineClient / Dashboard ALL.js, read 2026-10-23).
    def run(req):
        jid = int(req["jid"])
        tq = _tq(req)
        job = _one_job(tq, jid, archive=(name == "restore"))
        if name == "kill":
            tq.interrupt(job)  # stop running tasks
            tq.pause(job)      # and keep the job from restarting
        elif name == "retry":
            tq.retryerrors(job)        # "Retry All Error Tasks"
        elif name == "skip_errors":
            tq.skiperrors(job)         # "Skip All Error Tasks"
        elif name == "restart":
            tq.restart(job)            # "Restart Job": every task again
        elif name == "archive":
            tq.delete(job)             # "Archive Job" (jretire), undone by restore
        elif name == "restore":
            tq.undelete(job)           # "Restore Job" (jrestore)
        elif name == "lock":
            tq.lock(job, note="FLUX %s" % (req.get("user") or ""))
        elif name == "unlock":
            tq.unlock(job)
        elif name == "shuffle_top":
            # "Shuffle Job To Top": Dashboard queue request jshuffle, not exposed by the query API.
            client = _engine_client()
            client._transaction(client.QUEUE, {"q": "jshuffle", "jid": str(jid)})
        elif name == "pause":
            tq.pause(job)
        elif name == "resume":
            tq.unpause(job)
        return {"jid": int(req["jid"])}
    return run


def _trace(req):
    """Read only: why the engine does or does not dispatch this job ("Trace Job" of the Dashboard)."""
    jid = int(req["jid"])
    _one_job(_tq(req), jid)
    client = _engine_client()
    text = client._transaction(client.CONTROL, {"q": "tracer", "t": "J%d" % jid, "fmt": "plain"}, translation=None)
    return {"trace": _str(text)[-LOG_TAIL:]}


def _exit_codes(req):
    """Read only: non-zero exit codes of these jobs' executions (retries included), with the program run."""
    jids = sorted(set(int(j) for j in (req.get("jids") or [])))[:50]
    if not jids:
        return {"invocations": []}
    tq = _tq(req)
    clause = "jid in [%s]" % ",".join(str(j) for j in jids)
    program = {}
    for c in tq.commands(clause, columns=["jid", "cid", "argv"]):
        argv = c.get("argv") or []
        program[(c.get("jid"), c.get("cid"))] = os.path.basename(_str(argv[0]).replace("\\", "/")) if argv else ""
    out = []
    for r in tq.invocations(clause + " and rcode != 0", columns=["jid", "tid", "cid", "rcode", "stoptime"]):
        if r.get("rcode") is None:
            continue
        out.append({"jid": r.get("jid"), "tid": r.get("tid"), "cid": r.get("cid"), "rcode": int(r.get("rcode")),
                    "stoptime": _str(r.get("stoptime")), "program": program.get((r.get("jid"), r.get("cid")), "")})
    return {"invocations": out}


def _ping(req):
    return {"version": sys.version.split()[0]}


# ── protocol ─────────────────────────────────────────────────────────────────

VERBS = {
    "spool": _spool, "jobs": _jobs, "tasks": _tasks, "log": _log, "blades": _blades, "ping": _ping,
    "kill": _job_op("kill"), "retry": _job_op("retry"),
    "pause": _job_op("pause"), "resume": _job_op("resume"), "maxactive": _maxactive,
    "exit_codes": _exit_codes, "trace": _trace,
    "skip_errors": _job_op("skip_errors"), "restart": _job_op("restart"), "archive": _job_op("archive"),
    "restore": _job_op("restore"), "lock": _job_op("lock"), "unlock": _job_op("unlock"),
    "shuffle_top": _job_op("shuffle_top"),
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
