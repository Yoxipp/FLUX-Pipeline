# test_validate.py — the validation engine (01_ARCHITECTURE §8, P4): one test per
# code (fr / en messages, fix), and no false positive on the shipped flows.

from __future__ import annotations

import unittest
from pathlib import Path

from flux_flows.model import load_flow_text, parse_flow
from flux_flows.nodes.registry import flow_node, port
from flux_flows.validate import Env, errors, unconfirmed_destructive, validate, validate_document
from tests.test_flux_flows import _flow_helpers as helpers
from tests.test_flux_flows._flow_helpers import flow

SHIPPED = Path(__file__).resolve().parents[2] / "flux_flows" / "shipped"


def _sim(ctx, inputs, params):
    return {"lines": [], "outputs": {}}


def setUpModule() -> None:  # noqa: N802 (unittest API)
    helpers.setUpModule()
    # Test nodes for the DCC flags (the real session / dcc nodes come in P6).
    @flow_node("session.tst_instance", "TstInstance", inputs=[port("exec", "exec", required=True)],
               outputs=[port("then", "exec"), port("session", "session[houdini]")],
               params=[port("mode", "str", default="live_connect_or_open")],
               licence={"param": "mode", "equals": "headless"})
    async def _instance(ctx, inputs, params):
        return {}

    @flow_node("dcc.tst_cook", "tstCook", inputs=[port("exec", "exec", required=True),
                                                 port("session", "session[houdini]", required=True)],
               outputs=[port("then", "exec")], session="houdini", live_only=True)
    async def _cook(ctx, inputs, params):
        return {}

    @flow_node("action.tst_erase", "TstErase", inputs=[port("exec", "exec", required=True)],
               outputs=[port("then", "exec")], params=[port("mode", "str", default="archive")],
               destructive={"param": "mode", "equals": "erase"}, simulate=_sim)
    async def _erase(ctx, inputs, params):
        return {}


def tearDownModule() -> None:  # noqa: N802 (unittest API)
    helpers.tearDownModule()


def _codes(issues, code=None):
    found = [i for i in issues if code is None or i.code == code]
    return found


START = {"ev": "event.manual"}


class ShippedFlowsTests(unittest.TestCase):
    def test_no_error_on_any_shipped_flow(self) -> None:
        for path in sorted(SHIPPED.glob("*.flow.yml")):
            issues = validate(load_flow_text(path.read_text(encoding="utf-8")))
            self.assertEqual([i.to_dict() for i in errors(issues)], [], path.name)

    def test_issue_shape(self) -> None:
        issue = validate(flow({}, []))[0]
        self.assertEqual(set(issue.to_dict()), {"level", "code", "node", "port", "message_fr", "message_en",
                                                 "why_fr", "why_en", "fix", "link"})


class ErrorCodeTests(unittest.TestCase):
    def test_schema(self) -> None:
        got, issues = validate_document({"flux_flow": 2, "name": "x_flow", "nodez": {}})
        self.assertIsNone(got)
        self.assertEqual([i.code for i in issues], ["E_SCHEMA"])
        self.assertIn("nodez", issues[0].message_fr)

    def test_unknown_node(self) -> None:
        issues = _codes(validate(flow({**START, "n1": "team.nope"}, ["ev.then->n1.exec"])), "E_UNKNOWN_NODE")
        self.assertEqual((issues[0].node, issues[0].fix), ("n1", None))
        self.assertIn("team.nope", issues[0].message_en)

    def test_param_invalid(self) -> None:
        f = flow({**START, "n1": ("operator.for_begin", {"start": 1, "end": 3, "step": 0}),
                  "n2": ("operator.for_end", {"begin": "n1"}),
                  "n3": ("event.manual", {"every_s": 2})},
                 ["ev.then->n1.exec", "n1.loop->n2.exec"])
        issues = _codes(validate(f), "E_PARAM_INVALID")
        self.assertEqual(sorted((i.node, i.port) for i in issues), [("n1", "step"), ("n3", "every_s")])
        self.assertIn("5 secondes", [i for i in issues if i.node == "n3"][0].message_fr)

    def test_param_invalid_type_and_pattern(self) -> None:
        f = flow({**START, "n1": ("flux.find_publishes", {"name": "[abc"}),
                  "n2": ("operator.for_begin", {"start": "deux", "end": 3})}, [])
        ports = sorted((i.node, i.port) for i in _codes(validate(f), "E_PARAM_INVALID"))
        self.assertEqual(ports, [("n1", "name"), ("n2", "start")])

    def test_farm_mode(self) -> None:
        f = flow({**START, "n1": ("session.tst_instance", {"mode": "farm"})}, ["ev.then->n1.exec"])
        self.assertEqual(_codes(validate(f), "E_PARAM_INVALID")[0].node, "n1")

    def test_link_invalid(self) -> None:
        f = flow({**START, "n1": "action.t_record", "n2": "action.t_record", "v": ("data.value", {"value": 1})},
                 ["ev.then->n1.exec", "ev.then->n2.exec", "n1.nope->n2.value", "v.value->ev.exec",
                  "v.value->n1.value", "n2.out->n1.value"])
        issues = _codes(validate(f), "E_LINK_INVALID")
        messages = " | ".join(i.message_fr for i in issues)
        self.assertIn("Sequence", messages)            # 2nd link on an exec output
        self.assertIn("pas de sortie `nope`", messages)
        self.assertIn("evenement", messages)           # exec into an event
        self.assertIn("qu'un lien", messages)          # 2nd link on a data input
        self.assertTrue(all(i.fix["kind"] == "remove_link" and i.link for i in issues))

    def test_type_mismatch_and_foreach_fix(self) -> None:
        f = flow({**START, "n1": ("action.list_files", {"folder": "x"}), "n2": "action.make_dir"},
                 ["ev.then->n2.exec", "n1.files->n2.path"])
        issue = _codes(validate(f), "E_TYPE_MISMATCH")[0]
        self.assertIn("ForEach", issue.message_fr)
        self.assertEqual(issue.fix, {"kind": "insert_foreach", "args": {"from": "n1.files", "to": "n2.path"}})
        self.assertEqual(issue.link, {"from": "n1.files", "to": "n2.path"})

    def test_type_mismatch_does_not_block_a_dry_run(self) -> None:
        f = flow({**START, "v": ("data.value", {"type": "int", "value": 3}), "n2": "action.make_dir"},
                 ["ev.then->n2.exec", "v.value->n2.path"])
        issues = validate(f)
        self.assertTrue(errors(issues))
        self.assertFalse([i for i in errors(issues, dry_run=True) if i.code == "E_TYPE_MISMATCH"])

    def test_exec_into_data_is_a_type_mismatch(self) -> None:
        f = flow({**START, "n1": "action.t_record"}, ["ev.then->n1.value"])
        self.assertEqual(_codes(validate(f), "E_TYPE_MISMATCH")[0].port, "value")

    def test_required_empty(self) -> None:
        issues = _codes(validate(flow({**START, "n1": "action.copy"}, ["ev.then->n1.exec"])), "E_REQUIRED_EMPTY")
        self.assertEqual(sorted(i.port for i in issues), ["dest", "source"])
        self.assertIn("relie un lien", issues[0].message_fr)

    def test_no_event(self) -> None:
        issue = _codes(validate(flow({"n1": "action.t_record"}, [])), "E_NO_EVENT")[0]
        self.assertEqual(issue.fix, {"kind": "add_node", "args": {"type": "event.button"}})
        self.assertEqual(issue.message_en, "This flow has no start node")

    def test_exec_cycle(self) -> None:
        f = flow({**START, "n1": "action.t_record", "n2": "action.t_record"},
                 ["ev.then->n1.exec", "n1.then->n2.exec", "n2.then->n1.exec"])
        issue = _codes(validate(f), "E_EXEC_CYCLE")[0]
        self.assertIn("revient en arriere", issue.message_fr)
        self.assertEqual(issue.fix["kind"], "remove_link")

    def test_data_cycle(self) -> None:
        f = flow({**START, "a": "data.t_counter", "b": "data.t_counter", "n1": "action.t_record"},
                 ["ev.then->n1.exec", "a.value->b.x", "b.value->a.x", "a.value->n1.value"])
        self.assertTrue(_codes(validate(f), "E_EXEC_CYCLE"))

    def test_block_unbalanced(self) -> None:
        f = flow({**START, "b": ("operator.foreach_begin", {}), "v": ("data.value", {"type": "list", "value": [1]})},
                 ["ev.then->b.exec", "v.value->b.list"])
        issue = _codes(validate(f), "E_BLOCK_UNBALANCED")[0]
        self.assertEqual(issue.fix, {"kind": "add_block_end", "args": {"begin": "b", "type": "operator.foreach_end"}})

    def test_block_chain_leaves_the_block(self) -> None:
        f = flow({**START, "b": ("operator.for_begin", {"start": 1, "end": 2}), "e": ("operator.for_end", {"begin": "b"}),
                  "n1": "action.t_record", "n2": "operator.sequence", "after": "action.t_record"},
                 ["ev.then->b.exec", "b.loop->n2.exec", "n2.then_0->e.exec", "n2.then_1->after.exec",
                  "e.done->after.exec"])
        self.assertIn("sort du bloc", _codes(validate(f), "E_BLOCK_UNBALANCED")[0].message_fr)

    def test_no_session_and_live_only(self) -> None:
        f = flow({**START, "c": "dcc.tst_cook"}, ["ev.then->c.exec"])
        issue = _codes(validate(f), "E_NO_SESSION")[0]
        self.assertEqual(issue.fix, {"kind": "add_instance", "args": {"soft": "houdini", "node": "c"}})
        f = flow({**START, "i": ("session.tst_instance", {"mode": "headless"}), "c": "dcc.tst_cook"},
                 ["ev.then->i.exec", "i.then->c.exec", "i.session->c.session"])
        issues = validate(f)
        live = _codes(issues, "E_LIVE_ONLY")[0]
        self.assertEqual(live.fix, {"kind": "set_instance_mode", "args": {"node": "i", "mode": "live_connect_or_open"}})
        self.assertEqual(_codes(issues, "W_LICENCE")[0].node, "i")
        f = flow({**START, "i": "session.tst_instance", "c": "dcc.tst_cook"},
                 ["ev.then->i.exec", "i.then->c.exec", "i.session->c.session"])
        self.assertFalse(_codes(validate(f), "E_LIVE_ONLY") + _codes(validate(f), "W_LICENCE"))

    def test_var_never_set(self) -> None:
        f = flow({**START, "g": ("data.get_variable", {"name": "count"}), "n1": "action.t_record"},
                 ["ev.then->n1.exec", "g.value->n1.value"], variables=[{"name": "count", "type": "int"}])
        issue = _codes(validate(f), "E_VAR_NEVER_SET")[0]
        self.assertEqual(issue.fix["args"]["name"], "count")
        f = flow({**START, "g": ("data.get_variable", {"name": "count"}), "n1": "action.t_record"},
                 ["ev.then->n1.exec", "g.value->n1.value"], variables=[{"name": "count", "type": "int", "default": 0}])
        self.assertFalse(_codes(validate(f), "E_VAR_NEVER_SET"))

    def test_data_before_produced(self) -> None:
        f = flow({**START, "n1": "action.t_record", "n2": "action.t_record"},
                 ["ev.then->n1.exec", "n1.then->n2.exec", "n2.out->n1.value"])
        issue = _codes(validate(f), "E_DATA_BEFORE_PRODUCED")[0]
        self.assertEqual((issue.node, issue.port), ("n1", "value"))

    def test_body_value_read_after_the_end(self) -> None:
        f = flow({**START, "v": ("data.value", {"type": "list", "value": [1, 2]}),
                  "b": "operator.foreach_begin", "n1": "action.t_record", "e": ("operator.foreach_end", {"begin": "b"}),
                  "after": "action.t_record"},
                 ["ev.then->b.exec", "v.value->b.list", "b.loop->n1.exec", "n1.then->e.exec",
                  "b.item->e.collect", "e.done->after.exec", "n1.out->after.value"])
        issues = validate(f)
        self.assertEqual(_codes(issues, "E_DATA_BEFORE_PRODUCED")[0].node, "after")

    def test_unknown_token(self) -> None:
        f = flow({**START, "n1": ("action.make_dir", {"path": "$FLUX/{shto}/${dest}"})}, ["ev.then->n1.exec"],
                 interface=[{"id": "dest", "type": "dir"}])
        issue = _codes(validate(f), "E_UNKNOWN_TOKEN")[0]
        self.assertIn("{shot}", issue.message_fr)
        self.assertEqual(issue.fix["kind"], "replace_token")
        self.assertEqual(issue.fix["args"]["suggestion"], "{shot}")
        self.assertEqual(len(_codes(validate(f), "E_UNKNOWN_TOKEN")), 1)

    def test_subflow_cycle(self) -> None:
        called = {"other_flow": flow({**START, "c": ("subflow.flow_call", {"flow": "test_flow"})},
                                     ["ev.then->c.exec"], name="other_flow")}
        f = flow({**START, "c": ("subflow.flow_call", {"flow": "other_flow"})}, ["ev.then->c.exec"])
        issue = _codes(validate(f, Env(flow_loader=called.get)), "E_SUBFLOW_CYCLE")[0]
        self.assertIn("test_flow appelle other_flow appelle test_flow", issue.message_fr)

    def test_destructive_unconfirmed(self) -> None:
        old = flow({**START, "d": "action.tst_erase"}, ["ev.then->d.exec"])
        new = flow({**START, "d": ("action.tst_erase", {"mode": "erase"})}, ["ev.then->d.exec"])
        issue = unconfirmed_destructive(new, old, [])[0]
        self.assertEqual((issue.code, issue.node), ("E_DESTRUCTIVE_UNCONFIRMED", "d"))
        self.assertFalse(unconfirmed_destructive(new, old, ["d"]))
        self.assertFalse(unconfirmed_destructive(new, new, []))
        self.assertTrue(unconfirmed_destructive(new, None, []))


class WarningCodeTests(unittest.TestCase):
    def test_destructive_untested_and_tested(self) -> None:
        f = flow({**START, "d": ("action.tst_erase", {"mode": "erase"})}, ["ev.then->d.exec"])
        self.assertEqual(_codes(validate(f), "W_DESTRUCTIVE_UNTESTED")[0].level, "warning")
        self.assertFalse(_codes(validate(f, Env(tested=["d"])), "W_DESTRUCTIVE_UNTESTED"))

    def test_destructive_in_loop(self) -> None:
        f = flow({**START, "v": ("data.value", {"type": "list", "value": ["a"]}), "b": "operator.foreach_begin",
                  "d": ("action.delete", {}), "e": ("operator.foreach_end", {"begin": "b"})},
                 ["ev.then->b.exec", "v.value->b.list", "b.loop->d.exec", "d.then->e.exec", "b.item->d.path"])
        self.assertEqual(_codes(validate(f), "W_DESTRUCTIVE_IN_LOOP")[0].node, "d")

    def test_absolute_path_and_other_project(self) -> None:
        f = flow({**START, "n1": ("action.make_dir", {"path": "C:/temp/out"}),
                  "n2": ("action.make_dir", {"path": "$FLUX/DOSSIER_PROJETS/OTHER/x"}),
                  "n3": ("action.make_dir", {"path": "$FLUX/DOSSIER_PROJETS/MINE/x"})},
                 ["ev.then->n1.exec", "n1.then->n2.exec", "n2.then->n3.exec"])
        env = Env(project="MINE", flux_root="D:/FLUX", projects_dir="D:/FLUX/DOSSIER_PROJETS")
        issues = validate(f, env)
        self.assertEqual([i.node for i in _codes(issues, "W_ABSOLUTE_PATH")], ["n1"])
        self.assertEqual([i.node for i in _codes(issues, "W_OTHER_PROJECT")], ["n2"])
        self.assertIn("`OTHER`", _codes(issues, "W_OTHER_PROJECT")[0].message_fr)

    def test_scan_too_fast(self) -> None:
        f = flow({"ev": ("event.manual", {"every_s": 6}), "n1": "action.t_record"}, ["ev.then->n1.exec"])
        issue = _codes(validate(f), "W_SCAN_TOO_FAST")[0]
        self.assertEqual(issue.fix, {"kind": "set_param", "args": {"node": "ev", "param": "every_s", "value": 30}})

    def test_while_no_exit(self) -> None:
        f = flow({**START, "w": ("operator.while_begin", {"condition": True}), "n1": "action.t_record",
                  "e": ("operator.while_end", {"begin": "w"})},
                 ["ev.then->w.exec", "w.loop->n1.exec", "n1.then->e.exec"])
        self.assertEqual(_codes(validate(f), "W_WHILE_NO_EXIT")[0].node, "w")
        f = flow({**START, "w": "operator.while_begin", "s": ("data.set_variable", {"name": "go"}),
                  "g": ("data.get_variable", {"name": "go"}), "c": ("data.value", {"type": "bool", "value": False}),
                  "e": ("operator.while_end", {"begin": "w"})},
                 ["ev.then->w.exec", "w.loop->s.exec", "c.value->s.value", "s.then->e.exec", "g.value->w.condition"],
                 variables=[{"name": "go", "type": "bool", "default": True}])
        self.assertFalse(_codes(validate(f), "W_WHILE_NO_EXIT"))

    def test_isolated_node(self) -> None:
        f = flow({**START, "n1": "action.t_record", "n2": "action.t_record", "n3": "action.t_record"},
                 ["ev.then->n1.exec", "n2.then->n3.exec"])
        issues = _codes(validate(f), "W_ISOLATED_NODE")
        self.assertEqual(sorted(i.node for i in issues), ["n2", "n3"])
        self.assertEqual(issues[0].fix["kind"], "remove_node")

    def test_shipped_changed(self) -> None:
        f = flow({**START, "n1": "action.t_record"}, ["ev.then->n1.exec"])
        self.assertEqual(_codes(validate(f, Env(shipped_changed=True)), "W_SHIPPED_CHANGED")[0].level, "warning")


class NoFalsePositiveTests(unittest.TestCase):
    def test_clean_loop_flow(self) -> None:
        f = flow({**START, "v": ("data.value", {"type": "list", "value": ["a", "b"]}), "b": "operator.foreach_begin",
                  "n1": "action.t_record", "e": ("operator.foreach_end", {"begin": "b"}), "after": "action.t_record"},
                 ["ev.then->b.exec", "v.value->b.list", "b.loop->n1.exec", "b.item->n1.value", "n1.then->e.exec",
                  "n1.out->e.collect", "e.done->after.exec", "e.results->after.value"])
        self.assertEqual([i.to_dict() for i in validate(f)], [])

    def test_if_branches_rejoin(self) -> None:
        f = flow({**START, "c": ("data.value", {"type": "bool", "value": True}), "i": "logic.if",
                  "a": "action.t_record", "b": "action.t_record", "j": "action.t_record"},
                 ["ev.then->i.exec", "c.value->i.condition", "i.then->a.exec", "i.else->b.exec",
                  "a.then->j.exec", "b.then->j.exec"])
        self.assertEqual(errors(validate(f)), [])

    def test_schema_valid_document(self) -> None:
        doc = {"flux_flow": 2, "name": "doc_flow", "nodes": {"ev": {"type": "event.manual"}}, "links": []}
        got, issues = validate_document(doc)
        self.assertIsNotNone(got)
        self.assertEqual([i.code for i in issues], ["W_ISOLATED_NODE"])


if __name__ == "__main__":
    unittest.main()
