# P2 (2026-10-22): flux.legacy_command runs a v1 command through flux_core's public API
# (02 §7) and the node registry refuses an effect node without simulate (01 §5).

from __future__ import annotations

import threading
import unittest

from flux_core import CommandBase, register
from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeContext, NodeError
from flux_flows.nodes.registry import NodeDefinitionError, flow_node
from tests.test_flux_core._registry_guard import setUpModule, tearDownModule  # noqa: F401


class _Run:
    """Stub of the engine run seen through NodeContext."""

    def __init__(self) -> None:
        self.run_id, self.flow_name, self.mode = "r1", "f", "real"
        self.context = {"project": "PRJ", "project_path": "/p", "user": "ADAM"}
        self.interface: dict = {}
        self.cancelled = threading.Event()
        self.logs: list = []

    def node_log(self, node_id, level, text):
        self.logs.append((level, text))


@register("p2_test_double")
class _Double(CommandBase):
    parameters = {"n": {"type": "int", "value": 1}, "suffix": {"type": "str", "value": "x"}}
    required_metadata = ["project_name"]

    async def run(self, parameters, action_query, logger):
        logger.info("double %s", parameters["n"])
        return {"result": parameters["n"] * 2, "project": action_query.buffer.context["project_name"],
                "suffix": parameters["suffix"]}


class LegacyCommand(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = registry.get_node("flux.legacy_command")
        self.run = _Run()
        self.ctx = NodeContext(self.run, "n2")

    def test_runs_the_v1_command_with_context_and_casts(self) -> None:
        out = self.spec.func(self.ctx, {"n": "21", "inputs": {}}, {"command": "p2_test_double",
                                                                     "params": {"suffix": "y"}})
        self.assertEqual((out["result"], out["project"], out["suffix"]), (42, "PRJ", "y"))
        self.assertEqual(out["outputs"]["result"], 42)
        self.assertIn(("info", "double 21"), self.run.logs)

    def test_linked_dict_and_errors(self) -> None:
        out = self.spec.func(self.ctx, {"inputs": {"n": 2}}, {"command": "p2_test_double"})
        self.assertEqual(out["result"], 4)
        with self.assertRaises(NodeError):
            self.spec.func(self.ctx, {"n": "abc"}, {"command": "p2_test_double"})
        with self.assertRaises(NodeError):
            self.spec.func(self.ctx, {}, {"command": "does_not_exist"})
        self.run.context = {"user": "ADAM"}
        with self.assertRaises(NodeError):
            self.spec.func(self.ctx, {}, {"command": "p2_test_double"})

    def test_simulate_never_runs_it(self) -> None:
        res = self.spec.simulate(self.ctx, {}, {"command": "p2_test_double"})
        self.assertIn("p2_test_double", res["lines"][0]["text_fr"])
        self.assertEqual(self.run.logs, [])


class Registry(unittest.TestCase):
    def test_effect_node_needs_simulate(self) -> None:
        with self.assertRaises(NodeDefinitionError):
            flow_node("action.p2_nosim", "X", effect=True)
        with self.assertRaises(NodeDefinitionError):
            flow_node("action.p2_nosim", "X", destructive=True)

    def test_every_builtin_effect_node_has_simulate(self) -> None:
        nodes = {s.type: s for s in registry.all_nodes()}
        p2 = {"event.button", "event.manual", "data.value", "data.get_variable", "data.set_variable",
              "data.flow_input", "logic.if", "operator.foreach_begin", "operator.foreach_end",
              "flux.notify", "flux.legacy_command"}
        self.assertTrue(p2 <= set(nodes))
        for spec in nodes.values():
            if spec.effect:
                self.assertIsNotNone(spec.simulate, spec.type)
        self.assertTrue(nodes["flux.notify"].effect)
        self.assertFalse(nodes["data.value"].effect)


if __name__ == "__main__":
    unittest.main()
