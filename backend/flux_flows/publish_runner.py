# publish_runner.py - a POST /dcc/<soft>/publish route publishing through its flow (P8, ADR 0070).
#
# When the project is in v2 (switch.flows_publish_enabled), the route calls run_publish():
# it runs the shipped (or team / project / perso) flow publish_<soft> with the form values,
# waits for the end and hands back an Outcome. The route keeps the exact v1 response shape
# (n°7): it reads path, version, files, warnings of the outcome and builds the rest.
#
# Verdicts (ADR 0070):
#   ok        the core published; outputs = the FlowOutput values of the run.
#   refused   flux.refuse_publish stopped the run before the core: message shown as is,
#             never a fallback.
#   fallback  the run failed BEFORE the core started (flow missing or invalid, Instance not
#             found, port refused...): the route publishes by v1, with warning() in its
#             response and a log line here.
#   error     the run failed AFTER the core started (or was cancelled): never a fallback,
#             a second publish could write a second vNNN. The route raises the error.
# "Before / after the core" = the probe dict of the run context (dcc_publish.PROBE_KEY),
# set by core_starting() right before the Publisher function. Bridges are untouched: the
# cores call the same functions as v1.

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from flux_flows import engine, locations, runs, store
from flux_flows.model import Flow
from flux_flows.nodes.dcc_publish import PROBE_KEY

log = logging.getLogger("flux.flows.publish")

EVENT = "publish_request"


def flow_name(soft: str) -> str:
    return f"publish_{soft.strip().lower()}"


@dataclass
class Outcome:
    status: str                                  # ok | refused | fallback | error
    outputs: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    run_id: Optional[str] = None
    flow: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def warning(self) -> str:
        """The line a route adds to its response when it published by v1 instead."""
        return f"publie par l'ancien chemin : {self.message}"


def _load(soft: str, user: Optional[str], project: Optional[str]) -> tuple:
    """(scope, flow, version) of publish_<soft>: the active version of a copy, else its
    working file; the shipped file otherwise. Raises on a missing or unreadable flow."""
    name = flow_name(soft)
    roots = locations.roots_for(user=user, project=project)
    scope = store.resolve(roots, name)
    if scope is None:
        raise LookupError(f"flow {name} introuvable")
    version = None
    if scope != "shipped":
        state = store.read_state(roots[scope], name)
        if state.get("active") and state.get("active_version"):
            version = int(state["active_version"])
    flow: Flow = store.read_flow(roots, scope, name, version)["flow"]
    return scope, flow, version


async def run_publish(soft: str, *, project: str, values: Dict[str, Any], user: Optional[str] = None) -> Outcome:
    """Run publish_<soft> with *values* (the flow interface) and wait for its verdict."""
    name = flow_name(soft)
    try:
        scope, flow, version = await asyncio.to_thread(_load, soft, user, project)
    except Exception as exc:  # noqa: BLE001 - any load failure is before the core
        return _fallback(name, None, f"{name} illisible ou absent ({exc})")
    probe: Dict[str, Any] = {"core_started": False, "refused": None}
    folder = runs.runs_dir(scope, project=project, user=user)
    run = engine.Run(flow, scope=scope, project=project, user=user, version=version, event=EVENT,
                     values=values, folder=folder, context={PROBE_KEY: probe},
                     payload={"soft": soft})
    record = await engine.manager().submit(run)
    if record["status"] in ("refused", "skipped"):
        issues = record.get("issues") or []
        why = (issues[0].get("message_fr") if issues else None) or record.get("error") or record["status"]
        return _fallback(name, record["run_id"], f"{name} non lance : {why}")
    if run.task is not None:
        await asyncio.shield(run.task)
    final = engine.manager().get(run.run_id) or run.record
    status, error = final.get("status"), str(final.get("error") or "")
    if status == "ok":
        return Outcome("ok", dict(run._outputs), run_id=run.run_id, flow=name)
    if probe.get("refused") and not probe.get("core_started"):
        return Outcome("refused", message=str(probe["refused"]), run_id=run.run_id, flow=name)
    if not probe.get("core_started") and status == "error":
        return _fallback(name, run.run_id, error or "echec avant le publish")
    # After the core started, or a cancelled / interrupted run: the run's error, never v1.
    return Outcome("error", message=error or str(status), run_id=run.run_id, flow=name)


def _fallback(name: str, run_id: Optional[str], reason: str) -> Outcome:
    log.warning("publish par flow %s : repli sur v1 (%s)%s", name, reason, f" run {run_id}" if run_id else "")
    return Outcome("fallback", message=reason, run_id=run_id, flow=name)
