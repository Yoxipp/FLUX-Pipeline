# _sched_helpers.py — a scheduler on temporary folders for the P5 tests.
#
# Flows are saved in a temporary team folder, frozen v1 and marked active in state.json;
# run records go to a temporary runs folder. The test node action.t_record of
# _flow_helpers records what ran (h.CALLS).

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

from flux_flows import engine, runs, scheduler, store
from flux_flows.scheduler import ActiveFlow, Scheduler

from tests.test_flux_flows import _flow_helpers as h


class Env:
    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_sched_"))
        self.team = self.tmp / "ext" / "flows"
        self.team.mkdir(parents=True)
        self._patches = [mock.patch.object(runs, "runs_dir", side_effect=lambda scope, **_: self.tmp / scope / "runs")]
        for p in self._patches:
            p.start()

    def close(self) -> None:
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def active(self, flow, *, scope: str = "team", project: Optional[str] = None) -> ActiveFlow:
        """Save *flow* as frozen v1, active, in the team folder."""
        roots = {scope: self.team}
        store.save_flow(roots, scope, flow, user="ADAM")
        store.increment_flow(roots, scope, flow.name, user="ADAM")
        state = store.read_state(self.team, flow.name)
        state.update(active=True, active_version=1)
        (self.team / flow.name / "state.json").write_text(json.dumps(state), encoding="utf-8")
        return ActiveFlow(scope, project, flow.name, 1, flow, self.team)

    def state(self, name: str) -> Dict[str, Any]:
        return store.read_state(self.team, name)


def make(env: Env, flows: List[ActiveFlow], *, now: datetime = datetime(2026, 10, 23, 9, 0), holder: bool = True,
         **kwargs: Any) -> Scheduler:
    sched = Scheduler(user_fn=lambda: "ADAM", scan_fn=lambda _user: list(flows), now_fn=lambda: now, **kwargs)
    sched.user = "ADAM"
    sched.flows = list(flows)
    sched.lock = mock.Mock(holder=holder)
    return sched


def record_flow(name: str, event_type: str, params: Dict[str, Any], *, extra_nodes=None, links=None):
    """event -> action.t_record(value = <first data output of the event>)."""
    nodes = {"ev": (event_type, params), "rec": "action.t_record", **(extra_nodes or {})}
    return h.flow(nodes, ["ev.then->rec.exec", *(links or [])], name=name)


async def settle(*records: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Wait for the runs of *records* to end."""
    mgr = engine.manager()
    return [await mgr.wait(r["run_id"]) for r in records if r]


def run(coro):
    return asyncio.run(coro)
