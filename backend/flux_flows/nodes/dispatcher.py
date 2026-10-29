# dispatcher.py — the Dispatcher family (ADR 0067): send work to the dispatcher of the pipe,
# never to a named farm manager. The backend (local, tractor) comes from CONFIG/dispatcher.json
# overridden by the project; the core is features/dispatcher (api.py).
#
# Submit, Cancel and RenderShot act on the world: simulated in a dry run (job_id "dry:<n>",
# nothing sent). Status and Wait read: on a "dry:" id they answer "simulated".
# Inside a ForEach in mode dispatch, Submit adds its tasks to the job of the loop instead of
# sending one (the engine sends it at ForEachEnd, ctx.dispatch_batch()).

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

DRY_PREFIX = "dry:"
_EXEC = port("exec", "exec", required=True)
_EXITS = [port("then", "exec"), port("on_error", "exec")]
_JOB_IN = port("job_id", "str", "Le job a suivre (sortie job_id de Submit ou RenderShot)",
               "The job to follow (job_id output of Submit or RenderShot)", "local:1a2b3c4d5e", required=True)
_STATE = port("state", "str", "waiting, active, done, error, cancelled, ou simulated (essai a blanc, Tractor en "
              "simulation)", "waiting, active, done, error, cancelled, or simulated (dry run, Tractor simulation)",
              "done")


def _ctx_project(ctx):
    c = ctx.context or {}
    path = c.get("project_path")
    return str(c.get("project") or ""), (Path(path) if path else None), str(c.get("user") or "")


def _error(exc: Exception) -> NodeError:
    return NodeError(str(exc), code="E_DISPATCH")


# -- Submit --------------------------------------------------------------------------

def _tasks(inputs, params) -> List[Any]:
    """dispatcher tasks from the `tasks` list, else one task from program + args."""
    from features.dispatcher import api

    program = str(params.get("program") or inputs.get("program") or "").strip()
    raw = inputs.get("tasks")
    if raw is None:
        raw = params.get("tasks")
    out = []
    if raw:
        if not isinstance(raw, (list, tuple)):
            raise NodeError("tasks : liste attendue (une entree par tache)", code="E_PARAM_INVALID")
        for i, item in enumerate(raw):
            if isinstance(item, dict):
                prog = str(item.get("program") or program)
                args = item.get("args") or []
                title, cwd = item.get("title") or f"tache {i + 1}", item.get("cwd") or ""
            else:
                prog, args = program, item if isinstance(item, (list, tuple)) else [item]
                title, cwd = f"tache {i + 1}", ""
            if not prog:
                raise NodeError(f"tache {i + 1} : pas de programme (reglage program ou cle program)",
                                code="E_PARAM_INVALID")
            out.append(api.task(title, prog, list(args), cwd))
        return out
    if not program:
        raise NodeError("Submit attend `program` (un programme declare dans la config du dispatcher) ou `tasks`",
                        code="E_PARAM_INVALID")
    args = inputs.get("args")
    if args is None:
        args = params.get("args") or []
    if not isinstance(args, (list, tuple)):
        args = [args]
    return [api.task(str(inputs.get("title") or params.get("title") or "tache 1"), program, list(args))]


def _job(ctx, inputs, params, tasks):
    from features.dispatcher.jobs import DispatchJob

    project, _path, user = _ctx_project(ctx)
    title = str(inputs.get("title") or params.get("title") or ctx.flow or "job").strip()
    priority = params.get("priority")
    return DispatchJob(title=title, user=user, project=project, tasks=tasks,
                       priority=int(priority) if priority not in (None, "") else 100,
                       start_after=str(params.get("start_after") or ""),
                       metadata={"flow": str(ctx.flow or ""), "run": str(ctx.run_id or "")})


def _check_programs(ctx, tasks) -> str:
    """The backend name; every program must be declared (dry run checks it too)."""
    from features.dispatcher import api
    from features.dispatcher import config as dconfig
    from features.dispatcher.jobs import DispatchError

    _project, path, _user = _ctx_project(ctx)
    try:
        cfg = api.effective_config(path)
        for t in tasks:
            dconfig.program(cfg, t.program, cfg["backend"])
    except (DispatchError, dconfig.ConfigError) as exc:
        raise _error(exc) from None
    return cfg["backend"]


def _simulate_submit(ctx, inputs, params):
    tasks = _tasks(inputs, params)
    backend = _check_programs(ctx, tasks)
    batch = ctx.dispatch_batch()
    where = "ajouterait au job de la boucle" if batch is not None else f"enverrait au dispatcher ({backend})"
    if batch is not None:
        batch["tasks"].extend(tasks)
        batch.setdefault("title", str(inputs.get("title") or params.get("title") or ctx.flow or "job"))
    lines = [{"kind": "dispatch", "text_fr": f"{where} : {len(tasks)} tache(s), {', '.join(sorted({t.program for t in tasks}))}"}]
    return {"lines": lines, "outputs": {"job_id": "" if batch is not None else f"{DRY_PREFIX}{ctx.node_id}",
                                        "backend": backend, "tasks": len(tasks)}}


@flow_node("dispatcher.submit", "Submit", icon="Rocket",
           inputs=[_EXEC,
                   port("tasks", "list[any]", "Une entree par tache : une liste d'arguments, ou {program, args, title}",
                        "One entry per task: a list of arguments, or {program, args, title}",
                        [["--frame", "1"], ["--frame", "2"]]),
                   port("args", "list[str]", "Arguments de la tache unique (sans tasks)",
                        "Arguments of the single task (without tasks)", ["-c", "print('ok')"]),
                   port("title", "str", "Titre du job (vide : nom du flow)", "Job title (empty: flow name)",
                        "cache sim SH010")],
           outputs=[*_EXITS,
                    port("job_id", "str", "Le job envoye, a relier a JobStatus, WaitJob ou CancelJob (vide dans une "
                         "boucle dispatch : le job part a ForEachEnd)", "The job sent, link it to JobStatus, WaitJob or "
                         "CancelJob (empty in a dispatch loop: the job leaves at ForEachEnd)", "local:1a2b3c4d5e"),
                    port("backend", "str", "Backend choisi par la config du dispatcher (local, tractor)",
                         "Backend chosen by the dispatcher config (local, tractor)", "local"),
                    port("tasks", "int", "Nombre de taches envoyees", "Number of tasks sent", 2)],
           params=[port("program", "str", "Programme lance par chaque tache : un des programmes declares dans la "
                        "config du dispatcher (husk, hython, mayapy...)", "Program each task starts: one of the "
                        "programs declared in the dispatcher config (husk, hython, mayapy...)", "hython"),
                   port("priority", "int", "Priorite du job (100 par defaut ; au-dessus passe avant les autres "
                        "equipes sur la farm)", "Job priority (100 by default; above goes before the other teams on "
                        "the farm)", 100, default=100),
                   port("start_after", "str", "Depart differe AAAA-MM-JJTHH:MM, vide = tout de suite",
                        "Delayed start YYYY-MM-DDTHH:MM, empty = now", "2026-10-24T20:00")],
           effect=True, simulate=_simulate_submit, shelf=95,
           aliases=["farm", "dispatcher", "envoyer", "job", "tractor", "deadline", "queue", "soumettre"],
           doc_fr="Envoie un job au dispatcher du pipe : une tache par entree de tasks, chacune lance un programme "
                  "declare (jamais de commande libre). Le backend (local, Tractor...) vient de la config du "
                  "dispatcher, pas du flow.",
           doc_en="Sends a job to the dispatcher of the pipe: one task per entry of tasks, each starts a declared "
                  "program (never a free command). The backend (local, Tractor...) comes from the dispatcher config, "
                  "not from the flow.")
def submit(ctx, inputs, params):
    from features.dispatcher import api
    from features.dispatcher.jobs import DispatchError

    tasks = _tasks(inputs, params)
    batch = ctx.dispatch_batch()
    if batch is not None:
        backend = _check_programs(ctx, tasks)
        batch["tasks"].extend(tasks)
        batch.setdefault("title", str(inputs.get("title") or params.get("title") or ctx.flow or "job"))
        if params.get("priority") not in (None, ""):
            batch.setdefault("priority", int(params["priority"]))
        ctx.log(f"{len(tasks)} tache(s) ajoutee(s) au job de la boucle (envoye a ForEachEnd)")
        return {"job_id": "", "backend": backend, "tasks": len(tasks)}
    _project, path, _user = _ctx_project(ctx)
    try:
        result = api.submit(_job(ctx, inputs, params, tasks), path)
    except DispatchError as exc:
        raise _error(exc) from None
    note = " (simulation : rien n'est parti)" if result.get("dry_run") else ""
    ctx.log(f"job {result['job_id']} envoye ({result['backend']}, {result['tasks']} tache(s)){note}")
    return {"job_id": result["job_id"], "backend": result["backend"], "tasks": result["tasks"]}


# -- Status / Wait / Cancel --------------------------------------------------------------

def _status(ctx, job_id: str) -> Dict[str, Any]:
    from features.dispatcher import api
    from features.dispatcher.jobs import DispatchError

    job_id = str(job_id or "").strip()
    if not job_id:
        raise NodeError("job_id vide : relie la sortie job_id de Submit ou RenderShot", code="E_PARAM_INVALID")
    if ctx.dry or job_id.startswith(DRY_PREFIX):
        return {"job_id": job_id, "state": "simulated", "total": 0, "done": 0, "errors": 0}
    project, _path, user = _ctx_project(ctx)
    try:
        return api.status(job_id, project, user)
    except DispatchError as exc:
        raise _error(exc) from None


_COUNTS = [port("done", "int", "Taches finies", "Tasks done", 3), port("total", "int", "Taches du job", "Tasks of the job", 4),
           port("errors", "int", "Taches en erreur", "Tasks in error", 0)]


@flow_node("dispatcher.status", "JobStatus", icon="Gauge",
           inputs=[_EXEC, _JOB_IN],
           outputs=[*_EXITS, _STATE, *_COUNTS,
                    port("finished", "bool", "Le job est termine (done, error, cancelled ou simulated)",
                         "The job is over (done, error, cancelled or simulated)", False)],
           shelf=96, aliases=["etat job", "job status", "farm", "suivi"],
           doc_fr="Lit l'etat d'un job du dispatcher et ses compteurs, sans attendre.",
           doc_en="Reads the state of a dispatcher job and its counters, without waiting.")
def status(ctx, inputs, params):
    from features.dispatcher.jobs import FINAL_STATES

    st = _status(ctx, inputs.get("job_id"))
    return {"state": st["state"], "done": st.get("done", 0), "total": st.get("total", 0),
            "errors": st.get("errors", 0), "finished": st["state"] in FINAL_STATES}


@flow_node("dispatcher.wait", "WaitJob", icon="Hourglass",
           inputs=[_EXEC, _JOB_IN],
           outputs=[*_EXITS, _STATE, *_COUNTS],
           params=[port("every_s", "float", "Frequence maximale de lecture de l'etat en secondes (min 5 ; les "
                        "premieres lectures sont plus rapprochees : 1, 2, 4 s...)", "Maximum state polling interval in "
                        "seconds (min 5; the first reads come sooner: 1, 2, 4 s...)", 10, default=10),
                   port("timeout_s", "float", "Attente maximale en secondes (le node echoue apres)",
                        "Maximum wait in seconds (the node fails after)", 3600, default=3600)],
           shelf=97, aliases=["attendre job", "wait job", "farm", "fin du job"],
           doc_fr="Attend la fin d'un job du dispatcher. then si tout est fini sans erreur, on_error si une tache "
                  "echoue ou si le job est annule.",
           doc_en="Waits for a dispatcher job to end. then when everything finished without error, on_error when a "
                  "task fails or the job is cancelled.")
def wait(ctx, inputs, params):
    import time

    every = max(5.0, float(params.get("every_s") or 10))
    limit = float(params.get("timeout_s") or 3600)
    t0 = time.monotonic()
    delay = 1.0                   # 1, 2, 4... up to every_s: a short job is seen at once
    while True:
        st = _status(ctx, inputs.get("job_id"))
        state = st["state"]
        if state in ("done", "simulated"):
            return {"state": state, "done": st.get("done", 0), "total": st.get("total", 0), "errors": st.get("errors", 0)}
        if state in ("error", "cancelled"):
            raise NodeError(f"Job {st['job_id']} : {state} ({st.get('errors', 0)} tache(s) en erreur)",
                            code="E_DISPATCH")
        if time.monotonic() - t0 >= limit:
            raise NodeError(f"Job {st['job_id']} toujours {state} apres {limit:g} s (timeout_s)", code="E_DISPATCH")
        if ctx.cancelled.wait(delay):
            raise NodeError("Run annule pendant l'attente du job", code="E_DISPATCH")
        delay = min(every, delay * 2)


def _simulate_cancel(ctx, inputs, params):
    return {"lines": [{"kind": "dispatch", "text_fr": f"annulerait le job {inputs.get('job_id') or '?'}"}],
            "outputs": {"cancelled": True}}


@flow_node("dispatcher.cancel", "CancelJob", icon="Ban",
           inputs=[_EXEC, _JOB_IN],
           outputs=[*_EXITS, port("cancelled", "bool", "Le job est annule", "The job is cancelled", True)],
           effect=True, simulate=_simulate_cancel, shelf=98, aliases=["annuler job", "kill", "farm", "stop"],
           doc_fr="Annule un job du dispatcher (les taches en cours sont arretees). Sur la farm, seulement un job que "
                  "tu as envoye depuis FLUX.",
           doc_en="Cancels a dispatcher job (running tasks are stopped). On the farm, only a job you sent from FLUX.")
def cancel(ctx, inputs, params):
    from features.dispatcher import api
    from features.dispatcher.jobs import DispatchError

    job_id = str(inputs.get("job_id") or "").strip()
    if job_id.startswith(DRY_PREFIX):
        return {"cancelled": True}
    project, _path, user = _ctx_project(ctx)
    try:
        api.cancel(job_id, project, user)
    except DispatchError as exc:
        raise _error(exc) from None
    ctx.log(f"job {job_id} annule")
    return {"cancelled": True}


# -- RenderShot ------------------------------------------------------------------------------

RENDERERS = ("karma", "renderman")


def _render_plan(ctx, inputs, params, dry: bool):
    from features.dispatcher import render_shot
    from features.dispatcher.jobs import DispatchError

    project, path, user = _ctx_project(ctx)
    if path is None:
        raise NodeError("RenderShot : pas de projet, lance le flow dans un projet")
    values = {**params, **{k: v for k, v in inputs.items() if v is not None}}
    try:
        return render_shot.plan(project=project, project_path=path, user=user, seq=str(values.get("seq") or ""),
                                shot=str(values.get("shot") or ""), usd=str(values.get("usd") or ""),
                                renderer=str(values.get("renderer") or "karma"), frame_start=values.get("frame_start"),
                                frame_end=values.get("frame_end"), chunk_size=values.get("chunk_size"),
                                priority=values.get("priority"), freeze=values.get("freeze", True) is not False,
                                dry=dry)
    except DispatchError as exc:
        raise _error(exc) from None


def _render_outputs(info, job_id):
    return {"job_id": job_id, "output": info["output"], "usd": info["usd"], "frames": info["frames"],
            "backend": info["backend"]}


def _simulate_render(ctx, inputs, params):
    job, info = _render_plan(ctx, inputs, params, dry=True)
    lines = [{"kind": "dispatch", "text_fr": f"rendrait {info['usd']} frames {info['frames'][0]}-{info['frames'][1]} "
                                             f"({len(job.tasks)} tache(s), {info['backend']}) dans {info['output']}",
              "path": info["output"]}]
    lines += [{"kind": "warn", "text_fr": w} for w in info["warnings"]]
    return {"lines": lines, "outputs": _render_outputs(info, f"{DRY_PREFIX}{ctx.node_id}")}


@flow_node("dispatcher.render_shot", "RenderShot", icon="Clapperboard",
           inputs=[_EXEC,
                   port("seq", "str", "Sequence du plan a rendre (ou usd)", "Sequence of the shot to render (or usd)",
                        "SEQ010", tokens="SEQ"),
                   port("shot", "str", "Plan a rendre (SHOT010)", "Shot to render (SHOT010)", "SHOT010", tokens="SHOT"),
                   port("usd", "path", "Ou un USD publie a rendre (a la place du plan)",
                        "Or a published USD to render (instead of the shot)", "$FLUX/PROJ/shot/SEQ010/SHOT010/light.usd"),
                   port("frame_start", "int", "Premiere frame (vide : celle du plan ou du USD)",
                        "First frame (empty: the shot's or the USD's)", 1001),
                   port("frame_end", "int", "Derniere frame (vide : celle du plan ou du USD)",
                        "Last frame (empty: the shot's or the USD's)", 1100)],
           outputs=[*_EXITS,
                    port("job_id", "str", "Le job envoye (a relier a WaitJob)", "The job sent (link it to WaitJob)",
                         "tractor:1234"),
                    port("output", "dir", "Dossier des images (render/vNNN)", "Images folder (render/vNNN)",
                         "$FLUX/PROJ/shot/SEQ010/SHOT010/render/v003"),
                    port("usd", "path", "USD rendu (version gelee)", "Rendered USD (frozen version)"),
                    port("frames", "list[int]", "Plage rendue [debut, fin]", "Rendered range [start, end]", [1001, 1100]),
                    port("backend", "str", "Backend du dispatcher (local, tractor)", "Dispatcher backend", "tractor")],
           params=[port("renderer", "str", "Moteur de rendu husk", "husk renderer", "karma", default="karma",
                        choices=RENDERERS, labels={"karma": ("Karma", "Karma"), "renderman": ("RenderMan", "RenderMan")}),
                   port("chunk_size", "int", "Frames par tache (vide : config du dispatcher)",
                        "Frames per task (empty: dispatcher config)", 5),
                   port("freeze", "bool", "Geler LAST -> vNNN avant le rendu (recommande)",
                        "Freeze LAST -> vNNN before rendering (recommended)", True, default=True),
                   port("priority", "int", "Priorite du job (vide : config du dispatcher)",
                        "Job priority (empty: dispatcher config)", 100)],
           effect=True, simulate=_simulate_render, shelf=99,
           aliases=["render", "rendu", "husk", "karma", "renderman", "farm", "tractor"],
           doc_fr="Rend un plan (ou un USD publie) avec husk, Karma ou RenderMan : gele LAST -> vNNN, une tache par "
                  "paquet de frames, images dans render/vNNN. Envoye au dispatcher du pipe (local ou farm).",
           doc_en="Renders a shot (or a published USD) with husk, Karma or RenderMan: freezes LAST -> vNNN, one task "
                  "per chunk of frames, images in render/vNNN. Sent to the dispatcher of the pipe (local or farm).")
def render_shot(ctx, inputs, params):
    from features.dispatcher import api
    from features.dispatcher.jobs import DispatchError

    job, info = _render_plan(ctx, inputs, params, dry=False)
    for w in info["warnings"]:
        ctx.log(w, "warn")
    _project, path, _user = _ctx_project(ctx)
    try:
        result = api.submit(job, path)
    except DispatchError as exc:
        raise _error(exc) from None
    ctx.log(f"rendu {job.title} : job {result['job_id']} ({result['backend']}, {len(job.tasks)} tache(s))")
    return _render_outputs(info, result["job_id"])
