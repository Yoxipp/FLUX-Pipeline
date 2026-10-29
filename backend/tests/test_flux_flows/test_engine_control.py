# P3 (2026-10-23): engine control flow (01 §4, 02_NODES §5 and §10): Sequence order,
# For (end included, step), While (stops on its condition, error at the ceiling,
# one turn in a dry run), BreakLoop to done, FlowCall outputs, depth limit and cycle.

from __future__ import annotations

import asyncio
import json
import unittest

from flux_flows import engine
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._flow_helpers import flow, run_flow, setUpModule, tearDownModule  # noqa: F401


def _records(name="r"):
    return [v for n, v in h.CALLS if n == name]


def _run_with(flow_obj, flows, mode="real"):
    """Run flow_obj; FlowCall loads the called flows from ``flows`` (name -> Flow or factory)."""
    def loader(name, version):
        found = flows.get(name) if isinstance(flows, dict) else flows(name)
        if found is None:
            raise engine.NodeError(f"Flow `{name}` introuvable")
        return found

    async def scenario():
        mgr = engine.manager()
        run = engine.Run(flow_obj, scope="team", project=None, user="ADAM", mode=mode, flow_loader=loader)
        rec = await mgr.submit(run)
        return await mgr.wait(rec["run_id"])

    return asyncio.run(scenario())


class Sequence(unittest.TestCase):
    def setUp(self):
        h.reset()

    def test_outputs_in_order_each_chain_to_its_end(self):
        f = flow({"n1": "event.manual", "s": ("operator.sequence", {"count": 3}),
                  "a": ("action.t_record", {"value": "a"}), "a2": ("action.t_record", {"value": "a2"}),
                  "b": ("action.t_record", {"value": "b"}), "c": ("action.t_record", {"value": "c"})},
                 ["n1.then->s.exec", "s.then_0->a.exec", "a.then->a2.exec", "s.then_1->b.exec", "s.then_2->c.exec"])
        rec = run_flow(f)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual([n for n, _ in h.CALLS], ["a", "a2", "b", "c"])

    def test_count_out_of_range(self):
        f = flow({"n1": "event.manual", "s": ("operator.sequence", {"count": 9})}, ["n1.then->s.exec"])
        self.assertEqual(run_flow(f)["status"], "error")


class ForLoop(unittest.TestCase):
    def setUp(self):
        h.reset()

    def _for(self, **params):
        f = flow({"n1": "event.manual", "b": ("operator.for_begin", params), "r": "action.t_record",
                  "e": ("operator.for_end", {"begin": "b"}), "after": "action.t_record"},
                 ["n1.then->b.exec", "b.loop->r.exec", "b.index->r.value", "r.then->e.exec", "e.done->after.exec"])
        return run_flow(f)

    def test_end_included_and_step(self):
        self.assertEqual(self._for(start=1, end=3)["status"], "ok")
        self.assertEqual(_records(), [1, 2, 3])
        self.assertEqual(h.CALLS[-1][0], "after")
        h.reset()
        self._for(start=1, end=10, step=3)
        self.assertEqual(_records(), [1, 4, 7, 10])
        h.reset()
        self._for(start=10, end=0, step=-5)
        self.assertEqual(_records(), [10, 5, 0])

    def test_empty_range_skips_the_body(self):
        self.assertEqual(self._for(start=5, end=1)["status"], "ok")
        self.assertEqual([n for n, _ in h.CALLS], ["after"])

    def test_step_zero_and_ceiling(self):
        self.assertEqual(h.refused_codes(self._for(start=1, end=3, step=0)), ["E_PARAM_INVALID"])
        rec = self._for(start=1, end=20, max_iterations=5)
        self.assertEqual(rec["status"], "error")
        self.assertIn("max_iterations", rec["nodes"]["b"]["error"])
        self.assertEqual(h.CALLS, [])


class WhileLoop(unittest.TestCase):
    def setUp(self):
        h.reset()

    def _counting(self, limit=1000, mode="real"):
        # while i < 3: i = i + 1; record i
        f = flow({"n1": "event.manual", "w": ("operator.while_begin", {"max_iterations": limit}),
                  "g": ("data.get_variable", {"name": "i"}), "lt": ("logic.compare", {"op": "lt", "b": 3}),
                  "add": ("operator.math", {"op": "add", "b": 1}), "s": ("data.set_variable", {"name": "i"}),
                  "r": "action.t_record", "e": ("operator.while_end", {"begin": "w"}), "after": "action.t_record"},
                 ["n1.then->w.exec", "g.value->lt.a", "lt.result->w.condition", "w.loop->s.exec",
                  "g.value->add.a", "add.as_int->s.value", "s.then->r.exec", "s.value->r.value", "r.then->e.exec",
                  "e.done->after.exec", "g.value->after.value"],
                 variables=[{"name": "i", "type": "int", "default": 0}])
        return run_flow(f, mode=mode)

    def test_stops_when_the_condition_turns_false(self):
        rec = self._counting()
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(_records(), [1, 2, 3])
        self.assertEqual(h.CALLS[-1], ("after", 3))

    def test_error_at_the_ceiling(self):
        rec = self._counting(limit=2)
        self.assertEqual(rec["status"], "error")
        self.assertIn("max_iterations", rec["nodes"]["w"]["error"])
        self.assertEqual(_records(), [1, 2])
        self.assertNotIn("after", [n for n, _ in h.CALLS])

    def test_always_true_hits_the_ceiling(self):
        f = flow({"n1": "event.manual", "w": ("operator.while_begin", {"condition": True, "max_iterations": 4}),
                  "r": "action.t_record", "e": ("operator.while_end", {"begin": "w"})},
                 ["n1.then->w.exec", "w.loop->r.exec", "w.index->r.value", "r.then->e.exec"])
        rec = run_flow(f)
        self.assertEqual(rec["status"], "error")
        self.assertEqual(_records(), [0, 1, 2, 3])

    def test_dry_run_is_one_turn(self):
        rec = self._counting(mode="dry")
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["nodes"]["s"]["count"], 1)
        self.assertIn("un seul tour du While", json.dumps(rec["report"]))
        self.assertEqual(h.CALLS, [])          # t_record is simulated

    def test_not_a_bool(self):
        f = flow({"n1": "event.manual", "w": ("operator.while_begin", {"condition": "yes"}),
                  "e": ("operator.while_end", {"begin": "w"})}, ["n1.then->w.exec"])
        self.assertIn("booleen", run_flow(f)["nodes"]["w"]["error"])


class BreakLoop(unittest.TestCase):
    def setUp(self):
        h.reset()

    def test_break_jumps_to_done(self):
        # for i in 1..5: if i >= 3: break; record i
        f = flow({"n1": "event.manual", "b": ("operator.for_begin", {"start": 1, "end": 5}),
                  "ge": ("logic.compare", {"op": "ge", "b": 3}), "if": "logic.if", "brk": "operator.break_loop",
                  "r": "action.t_record", "e": ("operator.for_end", {"begin": "b"}),
                  "after": ("action.t_record", {"value": "done"})},
                 ["n1.then->b.exec", "b.loop->if.exec", "b.index->ge.a", "ge.result->if.condition",
                  "if.then->brk.exec", "if.else->r.exec", "b.index->r.value", "r.then->e.exec",
                  "e.done->after.exec"])
        rec = run_flow(f)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(h.CALLS, [("r", 1), ("r", 2), ("after", "done")])
        self.assertEqual(rec["nodes"]["e"]["state"], "ok")

    def test_break_outside_a_loop(self):
        f = flow({"n1": "event.manual", "brk": "operator.break_loop"}, ["n1.then->brk.exec"])
        rec = run_flow(f)
        self.assertEqual(rec["status"], "error")
        self.assertIn("hors d'une boucle", rec["nodes"]["brk"]["error"])


class FlowCall(unittest.TestCase):
    def setUp(self):
        h.reset()

    @staticmethod
    def _child():
        # y = x + 10, recorded inside the child too
        return flow({"m": "event.manual", "fi": ("data.flow_input", {"id": "x"}),
                     "add": ("operator.math", {"op": "add", "b": 10}), "cr": "action.t_record",
                     "out": ("subflow.flow_output", {"id": "y"})},
                    ["m.then->cr.exec", "fi.value->cr.value", "cr.then->out.exec", "fi.value->add.a",
                     "add.as_int->out.value"],
                    name="child", interface={"inputs": [{"id": "x", "type": "int", "default": 0}],
                                             "outputs": [{"id": "y", "type": "int"}]})

    def _parent(self, **params):
        return flow({"n1": "event.manual", "c": ("subflow.flow_call", {"flow": "child", **params}),
                     "r": "action.t_record"},
                    ["n1.then->c.exec", "c.then->r.exec", "c.y->r.value"], name="parent")

    def test_inputs_and_outputs(self):
        rec = _run_with(self._parent(x=5), {"child": self._child()})
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(h.CALLS, [("cr", 5), ("r", 15)])

    def test_outputs_are_kept_in_the_record(self):
        # P7: a page widget fed by {flow, output} reads them from the last run.
        rec = _run_with(self._child(), {})
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(rec["outputs"], {"y": 10})

    def test_linked_input_wins_over_the_default(self):
        f = flow({"n1": "event.manual", "v": ("data.value", {"type": "int", "value": 7}),
                  "c": ("subflow.flow_call", {"flow": "child"}), "r": "action.t_record"},
                 ["n1.then->c.exec", "v.value->c.x", "c.then->r.exec", "c.y->r.value"], name="parent")
        rec = _run_with(f, {"child": self._child()})
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(h.CALLS[-1], ("r", 17))

    def test_unknown_flow(self):
        rec = _run_with(self._parent(), {})
        self.assertEqual(rec["status"], "error")
        self.assertIn("introuvable", rec["nodes"]["c"]["error"])

    @staticmethod
    def _caller(name, callee):
        return flow({"m": "event.manual", "c": ("subflow.flow_call", {"flow": callee})}, ["m.then->c.exec"],
                    name=name)

    def test_cycle(self):
        flows = {"fb": self._caller("fb", "fa")}
        rec = _run_with(self._caller("fa", "fb"), flows)
        self.assertEqual(rec["status"], "error")
        self.assertIn("fa > fb > fa", rec["nodes"]["c"]["error"])

    def test_depth_limit(self):
        # f0 calls f1 calls f2 ... : the 9th nested call is refused
        loaded = []

        def factory(name):
            loaded.append(name)
            return self._caller(name, f"f{int(name[1:]) + 1}")

        rec = _run_with(self._caller("f0", "f1"), factory)
        self.assertEqual(rec["status"], "error")
        self.assertIn(f"Plus de {engine.MAX_SUBFLOW_DEPTH} sous-flows", rec["nodes"]["c"]["error"])
        self.assertEqual(loaded, [f"f{i}" for i in range(1, engine.MAX_SUBFLOW_DEPTH + 1)])


if __name__ == "__main__":
    unittest.main()
