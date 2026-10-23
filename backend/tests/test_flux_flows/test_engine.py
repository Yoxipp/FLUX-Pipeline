# P2 (2026-10-22): Flows engine (01 §4): exec order, memo, data not produced, If,
# ForEach (empty list too), on_error, timeout, cancel, run_policy, admission.

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_flows import engine
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._flow_helpers import flow, run_flow, setUpModule, tearDownModule  # noqa: F401


def _value(v, kind="int"):
    return ("data.value", {"type": kind, "value": v})


class Exec(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()

    def test_exec_order_and_states(self) -> None:
        f = flow({"n1": "event.manual", "a": "action.t_record", "b": "action.t_record", "v": _value(1)},
                 ["n1.then->a.exec", "a.then->b.exec", "v.value->a.value", "a.out->b.value"])
        rec = run_flow(f)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(h.CALLS, [("a", 1), ("b", 1)])
        self.assertEqual({n: e["state"] for n, e in rec["nodes"].items()},
                         {"n1": "ok", "a": "ok", "b": "ok", "v": "ok"})
        self.assertEqual(rec["links"]["a.out->b.value"]["value"], "1")
        self.assertIsNotNone(rec["duration_ms"])

    def test_pure_node_is_memoised(self) -> None:
        f = flow({"n1": "event.manual", "a": "action.t_record", "b": "action.t_record", "c": "data.t_counter"},
                 ["n1.then->a.exec", "a.then->b.exec", "c.value->a.value", "c.value->b.value"])
        run_flow(f)
        self.assertEqual(h.CALLS, [("a", 1), ("b", 1)])
        self.assertEqual(h.COUNTS["c"], 1)

    def test_data_read_before_produced(self) -> None:
        f = flow({"n1": "event.manual", "a": "action.t_record", "b": "action.t_record"},
                 ["n1.then->a.exec", "a.then->b.exec", "b.out->a.value"])
        self.assertEqual(h.refused_codes(run_flow(f)), ["E_DATA_BEFORE_PRODUCED"])
        rec = run_flow(f, checked=False)
        self.assertEqual(rec["status"], "error")
        self.assertIn("avant d'etre produite", rec["nodes"]["a"]["error"])
        self.assertEqual(h.CALLS, [])

    def test_pure_error_fails_the_reader(self) -> None:
        f = flow({"n1": "event.manual", "a": "action.t_record", "p": "data.t_boom"},
                 ["n1.then->a.exec", "p.value->a.value"])
        rec = run_flow(f)
        self.assertEqual((rec["status"], rec["nodes"]["p"]["state"]), ("error", "error"))
        self.assertIn("p a echoue : pure boom", rec["nodes"]["a"]["error"])

    def test_exec_cycle_stops(self) -> None:
        f = flow({"n1": "event.manual", "a": "action.t_record", "b": "action.t_record"},
                 ["n1.then->a.exec", "a.then->b.exec", "b.then->a.exec"])
        self.assertIn("E_EXEC_CYCLE", h.refused_codes(run_flow(f)))
        rec = run_flow(f, checked=False)
        self.assertEqual(rec["status"], "error")
        self.assertIn("boucle", rec["error"])


class Blocks(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()

    def _if(self, cond: bool):
        f = flow({"n1": "event.manual", "i": "logic.if", "c": _value(cond, "bool"),
                  "t": "action.t_record", "e": "action.t_record", "j": "action.t_record"},
                 ["n1.then->i.exec", "c.value->i.condition", "i.then->t.exec", "i.else->e.exec",
                  "t.then->j.exec", "e.then->j.exec"])
        return run_flow(f)

    def test_if_takes_one_branch_then_joins(self) -> None:
        self._if(True)
        self.assertEqual([c[0] for c in h.CALLS], ["t", "j"])
        h.reset()
        rec = self._if(False)
        self.assertEqual([c[0] for c in h.CALLS], ["e", "j"])
        self.assertEqual(rec["nodes"]["t"]["state"], "idle")

    def test_if_needs_a_bool(self) -> None:
        f = flow({"n1": "event.manual", "i": "logic.if", "c": _value(1)},
                 ["n1.then->i.exec", "c.value->i.condition"])
        self.assertEqual(h.refused_codes(run_flow(f)), ["E_TYPE_MISMATCH"])
        self.assertEqual(run_flow(f, checked=False)["status"], "error")

    def _foreach(self, items):
        f = flow({"n1": "event.manual", "l": ("data.value", {"type": "list", "value": items}),
                  "b": "operator.foreach_begin", "r": "action.t_record",
                  "e": ("operator.foreach_end", {"begin": "b"}), "after": "action.t_record",
                  "per": "data.t_counter", "once": ("data.t_counter", {"key": "once"}),
                  "r2": "action.t_record"},
                 ["n1.then->b.exec", "l.value->b.list", "b.loop->r.exec", "b.item->per.x", "per.value->r.value",
                  "r.then->r2.exec", "once.value->r2.value", "r2.then->e.exec", "r.out->e.collect",
                  "e.done->after.exec", "e.results->after.value"])
        return run_flow(f)

    def test_foreach_body_per_item_and_results(self) -> None:
        rec = self._foreach(["a", "b", "c"])
        self.assertEqual(rec["status"], "ok")
        self.assertEqual([c for c in h.CALLS if c[0] == "r"], [("r", ("a", 1)), ("r", ("b", 2)), ("r", ("c", 3))])
        self.assertEqual(h.CALLS[-1], ("after", [("a", 1), ("b", 2), ("c", 3)]))
        self.assertEqual(h.COUNTS, {"per": 3, "once": 1})   # loop dependent vs not
        self.assertEqual(rec["nodes"]["r"]["count"], 3)

    def test_foreach_empty_list_skips_the_body(self) -> None:
        rec = self._foreach([])
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(h.CALLS, [("after", [])])

    def test_foreach_without_end(self) -> None:
        f = flow({"n1": "event.manual", "l": ("data.value", {"type": "list", "value": [1]}),
                  "b": "operator.foreach_begin"}, ["n1.then->b.exec", "l.value->b.list"])
        self.assertEqual(h.refused_codes(run_flow(f)), ["E_BLOCK_UNBALANCED"])
        rec = run_flow(f, checked=False)
        self.assertIn("n'a pas de End", rec["error"])

    def test_body_node_read_after_end_is_refused(self) -> None:
        f = flow({"n1": "event.manual", "l": ("data.value", {"type": "list", "value": [1, 2]}),
                  "b": "operator.foreach_begin", "r": "action.t_record",
                  "e": ("operator.foreach_end", {"begin": "b"}), "after": "action.t_record"},
                 ["n1.then->b.exec", "l.value->b.list", "b.loop->r.exec", "b.item->r.value", "r.then->e.exec",
                  "e.done->after.exec", "r.out->after.value"])
        self.assertEqual(h.refused_codes(run_flow(f)), ["E_DATA_BEFORE_PRODUCED"])
        rec = run_flow(f, checked=False)
        self.assertEqual(rec["status"], "error")
        self.assertIn("results de End", rec["nodes"]["after"]["error"])

    def test_variables_and_memo_invalidation(self) -> None:
        f = flow({"n1": "event.manual", "g": ("data.get_variable", {"name": "copied"}),
                  "a": "action.t_record", "s": ("data.set_variable", {"name": "copied"}),
                  "v": _value("5", "str"), "b": "action.t_record"},
                 ["n1.then->a.exec", "g.value->a.value", "a.then->s.exec", "v.value->s.value",
                  "s.then->b.exec", "g.value->b.value"],
                 variables=[{"name": "copied", "type": "int", "default": 0}])
        rec = run_flow(f)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(h.CALLS, [("a", 0), ("b", 5)])

    def test_variable_without_default_never_written(self) -> None:
        f = flow({"n1": "event.manual", "g": ("data.get_variable", {"name": "x"}), "a": "action.t_record"},
                 ["n1.then->a.exec", "g.value->a.value"], variables=[{"name": "x", "type": "int"}])
        self.assertEqual(h.refused_codes(run_flow(f)), ["E_VAR_NEVER_SET"])
        self.assertIn("jamais ecrite", run_flow(f, checked=False)["nodes"]["a"]["error"])


class Errors(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()

    def test_on_error_is_handled(self) -> None:
        f = flow({"n1": "event.manual", "x": "action.t_fail", "r": "action.t_record"},
                 ["n1.then->x.exec", "x.on_error->r.exec", "x.error->r.value"])
        rec = run_flow(f)
        self.assertEqual((rec["status"], rec["nodes"]["x"]["state"]), ("ok", "error_handled"))
        self.assertEqual(h.CALLS, [("r", "boom")])

    def test_error_without_handler_stops(self) -> None:
        f = flow({"n1": "event.manual", "x": "action.t_fail", "r": "action.t_record"},
                 ["n1.then->x.exec", "x.then->r.exec"])
        rec = run_flow(f)
        self.assertEqual((rec["status"], rec["error"]), ("error", "x : boom"))
        self.assertEqual(h.CALLS, [])

    def test_required_input_empty(self) -> None:
        f = flow({"n1": "event.manual", "s": ("data.set_variable", {"name": "x"})}, ["n1.then->s.exec"],
                 variables=[{"name": "x", "type": "int"}])
        self.assertEqual(h.refused_codes(run_flow(f)), ["E_REQUIRED_EMPTY"])
        self.assertIn("attend `value`", run_flow(f, checked=False)["nodes"]["s"]["error"])

    def test_timeout(self) -> None:
        f = flow({"n1": "event.manual", "s": ("action.t_sleep", {"seconds": 5, "timeout_s": 0.1})},
                 ["n1.then->s.exec"])
        rec = run_flow(f)
        self.assertEqual(rec["status"], "error")
        self.assertIn("timeout", rec["nodes"]["s"]["error"])

    def test_cancel(self) -> None:
        f = flow({"n1": "event.manual", "s": ("action.t_block", {"seconds": 5}), "r": "action.t_record"},
                 ["n1.then->s.exec", "s.then->r.exec"])

        async def scenario():
            mgr = engine.manager()
            run = engine.Run(f, scope="team", project=None, user="ADAM")
            rec = await mgr.submit(run)
            await asyncio.sleep(0.2)
            self.assertEqual(mgr.cancel(rec["run_id"]), "cancelling")
            return await mgr.wait(rec["run_id"])

        rec = asyncio.run(scenario())
        self.assertEqual(rec["status"], "cancelled")
        self.assertEqual(rec["nodes"]["s"]["state"], "cancelled")
        self.assertEqual(h.CALLS, [])


class Admission(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()

    def _two(self, policy: str):
        f = flow({"n1": "event.manual", "s": ("action.t_sleep", {"seconds": 0.2}), "r": "action.t_record"},
                 ["n1.then->s.exec", "s.then->r.exec"], run_policy=policy)

        async def scenario():
            mgr = engine.manager()
            first = await mgr.submit(engine.Run(f, scope="team", project=None, user="ADAM"))
            second = await mgr.submit(engine.Run(f, scope="team", project=None, user="ADAM"))
            a = await mgr.wait(first["run_id"])
            b = await mgr.wait(second["run_id"])
            return a, b

        return asyncio.run(scenario())

    def test_skip_if_running(self) -> None:
        a, b = self._two("skip_if_running")
        self.assertEqual((a["status"], b["status"]), ("ok", "skipped"))
        self.assertEqual(len(h.CALLS), 1)

    def test_queue_runs_one_after_the_other(self) -> None:
        a, b = self._two("queue")
        self.assertEqual((a["status"], b["status"]), ("ok", "ok"))
        self.assertLessEqual(a["ended"], b["started"])

    def test_refused_without_event_or_with_unknown_node(self) -> None:
        rec = run_flow(flow({"a": "action.t_record"}, []))
        self.assertEqual((rec["status"], rec["issues"][0]["code"]), ("refused", "E_NO_EVENT"))
        rec = run_flow(flow({"n1": "event.manual", "z": "action.nope"}, ["n1.then->z.exec"]))
        self.assertEqual((rec["status"], rec["issues"][0]["code"]), ("refused", "E_UNKNOWN_NODE"))

    def test_interface_values_reach_the_event_and_flow_input(self) -> None:
        f = flow({"n1": "event.button", "i": ("data.flow_input", {"id": "dest"}), "a": "action.t_record",
                  "b": "action.t_record"},
                 ["n1.then->a.exec", "i.value->a.value", "a.then->b.exec", "n1.values->b.value"],
                 interface=[{"id": "dest", "type": "dir", "default": "$FLUX/DAILY"}])
        from core.paths import from_flux_token  # P3: a dir default is resolved by FlowInput
        with mock.patch("core.paths.get_flux_root", return_value=Path(tempfile.gettempdir())):
            run_flow(f)
            self.assertEqual(h.CALLS[0], ("a", str(from_flux_token("$FLUX/DAILY"))))
        h.reset()
        run_flow(f, values={"dest": "D:/X", "ignored": 1})
        self.assertEqual(h.CALLS, [("a", "D:/X"), ("b", {"dest": "D:/X"})])

    def test_four_runs_at_once_at_most(self) -> None:
        flows = [flow({"n1": "event.manual", "s": ("action.t_sleep", {"seconds": 0.2})}, ["n1.then->s.exec"],
                      name=f"f{i}") for i in range(6)]

        async def scenario():
            mgr = engine.manager()
            recs = [await mgr.submit(engine.Run(f, scope="team", project=None, user="ADAM")) for f in flows]
            await asyncio.sleep(0.1)
            running = sum(1 for r in mgr.running() if r["status"] == "running")
            for r in recs:
                await mgr.wait(r["run_id"])
            return running

        self.assertEqual(asyncio.run(scenario()), engine.MAX_RUNNING)


class Examples(unittest.TestCase):
    """The shipped example flows (P2 step 7): one runs to the end, one fails."""

    def _load(self, name: str):
        from flux_flows import locations
        from flux_flows.model import load_flow_text

        return load_flow_text((locations.shipped_dir() / f"{name}.flow.yml").read_text(encoding="utf-8"))

    def test_example_foreach_runs_and_dry_runs(self) -> None:
        rec = run_flow(self._load("example_foreach"))
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["nodes"]["n5"]["count"], 3)
        self.assertEqual(rec["links"]["n10.value->n9.text"]["value"], "shot_030")
        dry = run_flow(self._load("example_foreach"), mode="dry")
        self.assertEqual((dry["status"], dry["nodes_simulated"]), ("ok", ["n9"]))

    def test_example_error_fails_with_the_values_received(self) -> None:
        rec = run_flow(self._load("example_error"))
        self.assertEqual(rec["status"], "error")
        self.assertIn("douze", rec["nodes"]["n3"]["error"])
        self.assertEqual(rec["nodes"]["n3"]["values"], {"value": "douze"})
        self.assertEqual(rec["nodes"]["n4"]["state"], "idle")


if __name__ == "__main__":
    unittest.main()
