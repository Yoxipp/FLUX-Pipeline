# _flow_helpers.py — test nodes and flow builders shared by the engine tests (P2).
#
# Test node types are registered once per test module (setUpModule) and removed
# after it (tearDownModule) so the real catalog stays untouched for later suites
# of tests/run_tests.py, like _registry_guard does for the v1 registry.

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from flux_flows.model import parse_flow
from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

CALLS: List[tuple] = []
COUNTS: Dict[str, int] = {}
_saved: dict = {}


def _sim_record(ctx, inputs, params):
    return {"lines": [{"kind": "test", "text_fr": f"enregistrerait {inputs.get('value')!r}"}],
            "outputs": {"out": inputs.get("value")}}


def _register() -> None:
    @flow_node("action.t_record", "TRecord", inputs=[port("exec", "exec", required=True), port("value", "any")],
               outputs=[port("then", "exec"), port("on_error", "exec"), port("out", "any")],
               effect=True, simulate=_sim_record)
    async def _record(ctx, inputs, params):
        CALLS.append((ctx.node_id, inputs.get("value")))
        return {"out": inputs.get("value")}

    @flow_node("action.t_fail", "TFail", inputs=[port("exec", "exec", required=True)],
               outputs=[port("then", "exec"), port("on_error", "exec"), port("error", "str")])
    async def _fail(ctx, inputs, params):
        raise NodeError("boom")

    @flow_node("action.t_sleep", "TSleep", inputs=[port("exec", "exec", required=True)],
               outputs=[port("then", "exec"), port("on_error", "exec")])
    async def _sleep(ctx, inputs, params):
        await asyncio.sleep(float(params.get("seconds", 1)))
        return {}

    @flow_node("action.t_block", "TBlock", inputs=[port("exec", "exec", required=True)],
               outputs=[port("then", "exec"), port("on_error", "exec")])
    def _block(ctx, inputs, params):
        end = time.monotonic() + float(params.get("seconds", 2))
        while time.monotonic() < end and not ctx.cancelled.is_set():
            time.sleep(0.02)
        return {}

    @flow_node("data.t_counter", "TCounter", inputs=[port("x", "any")], outputs=[port("value", "any")])
    async def _counter(ctx, inputs, params):
        key = params.get("key", ctx.node_id)
        COUNTS[key] = COUNTS.get(key, 0) + 1
        return {"value": (inputs.get("x"), COUNTS[key]) if inputs.get("x") is not None else COUNTS[key]}

    @flow_node("data.t_boom", "TBoom", outputs=[port("value", "any")])
    async def _boom(ctx, inputs, params):
        raise NodeError("pure boom")


def setUpModule() -> None:  # noqa: N802 (unittest API)
    registry.ensure_builtin()
    _saved.clear()
    _saved.update(registry._REGISTRY)
    _register()


def tearDownModule() -> None:  # noqa: N802 (unittest API)
    registry._REGISTRY.clear()
    registry._REGISTRY.update(_saved)


def reset() -> None:
    CALLS.clear()
    COUNTS.clear()


def flow(nodes: Dict[str, Any], links: List[str], **extra: Any):
    """nodes: {id: type or (type, params)}; links: ["n1.then->n2.exec", ...]."""
    doc_nodes = {}
    for nid, spec in nodes.items():
        kind, params = (spec, {}) if isinstance(spec, str) else spec
        doc_nodes[nid] = {"type": kind, "params": params}
    doc_links = [{"from": l.split("->")[0], "to": l.split("->")[1]} for l in links]
    return parse_flow({"flux_flow": 2, "name": extra.pop("name", "test_flow"), "nodes": doc_nodes,
                       "links": doc_links, **extra})


def run_flow(flow_obj, *, mode: str = "real", folder=None, values: Optional[dict] = None,
             event: Optional[str] = None) -> Dict[str, Any]:
    from flux_flows import engine

    async def scenario():
        mgr = engine.manager()
        run = engine.Run(flow_obj, scope="team", project=None, user="ADAM", mode=mode, folder=folder,
                         values=values, event=event)
        rec = await mgr.submit(run)
        return await mgr.wait(rec["run_id"])

    return asyncio.run(scenario())


