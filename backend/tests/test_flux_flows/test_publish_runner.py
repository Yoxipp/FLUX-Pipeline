# P8 step 3 (2026-10-29, ADR 0070): publish_runner runs publish_<soft> for a route and gives
# its verdict: ok, refused (flux.refuse_publish, never a fallback), fallback (the run failed
# BEFORE the core: v1 publishes) or error (AFTER the core: never v1, no double publish).
# Maya through a fake commandPort; the v1 runner function is mocked, nothing is published.

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from flux_flows import engine, locations, publish_runner, store
from flux_flows.bridges import primitives
from flux_flows.nodes import registry
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._fake_bridges import FakeCommandPort
from tests.test_flux_flows._fake_dcc import FakeCmds, install_fake_maya, maya_command_port_handler, restore_modules

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816

VALUES = {"name": "CHAR_MODEL_chair_null", "format": ".ma", "scope": "scene", "description": "retopo {v} $x"}
REFUSE = "Le nom doit finir par _null"
FAILED = object()   # the v1 runner gives None (publish failed after the core started)


class PublishRunner(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_pub_runner_"))
        self.project = self.tmp / "PROJ"
        (self.project / "publish").mkdir(parents=True)
        self.team = self.tmp / "team"
        self.team.mkdir()
        self.shipped = locations.shipped_dir()
        self.last = self.project / "publish" / "CHAR_MODEL_chair_null_LAST.ma"
        (self.project / "publish" / "CHAR_MODEL_chair_null_v003.ma").write_text("x")
        self.last.write_text("x")
        roots = lambda user=None, project=None: {"shipped": self.shipped, "team": self.team, "project": None,  # noqa: E731
                                                 "perso": None}
        self._p = [mock.patch("core.paths.get_project_path", side_effect=lambda name: self.tmp / name),
                   mock.patch.object(locations, "roots_for", side_effect=roots),
                   mock.patch("flux_flows.runs.runs_dir", return_value=None)]
        for p in self._p:
            p.start()
        self.seen: dict = {}

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _team_copy(self, edit) -> None:
        text = store.shipped_file(self.shipped, "publish_maya").read_text(encoding="utf-8")
        path = store.working_file(self.team, "publish_maya")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(edit(text), encoding="utf-8")

    def _publish(self, result=None, instances=True, values=None):
        def runner(**kwargs):
            self.seen.update(kwargs)
            return None if result is FAILED else self.last

        cmds = FakeCmds()
        saved = install_fake_maya(cmds)
        try:
            with FakeCommandPort(maya_command_port_handler) as srv, \
                    mock.patch.object(primitives, "scan_ports",
                                      return_value=[{"port": srv.port, "pid": 1}] if instances else []), \
                    mock.patch("core.dcc_instances.resolve_port", return_value=srv.port), \
                    mock.patch("flux_actions.runner.run_maya_publish_action", side_effect=runner) as mocked:
                self.port = srv.port
                out = asyncio.run(publish_runner.run_publish("maya", project="PROJ", values=values or VALUES,
                                                             user="ADAM"))
                self.calls = mocked.call_count
        finally:
            restore_modules(saved)
        return out

    def test_ok_gives_the_flow_outputs(self) -> None:
        out = self._publish(values={**VALUES, "options": {"uv": True}, "frame_range": "1001-1010-0.5"})
        self.assertEqual(out.status, "ok", out.message)
        self.assertEqual(out.outputs, {"path": str(self.last), "version": 3, "files": [str(self.last)],
                                       "warnings": []})
        self.assertEqual(self.calls, 1)
        # The form reaches the v1 runner untouched: no resolver on the description (links), options,
        # full frame range with a float step (n°12), logger of the run (n°3), user (n°5).
        self.assertEqual(self.seen["description"], "retopo {v} $x")
        self.assertEqual(self.seen["options"], {"uv": True})
        self.assertEqual(self.seen["frame_range"], [1001, 1010, 0.5])
        self.assertEqual((self.seen["user"], self.seen["port"]), ("ADAM", self.port))
        self.assertIsNotNone(self.seen["logger"])

    def test_port_of_the_route_wins(self) -> None:
        out = self._publish(values={**VALUES, "port": 7099})
        self.assertEqual(out.status, "ok", out.message)
        self.assertEqual(self.seen["port"], 7099)

    def test_no_instance_falls_back_before_the_core(self) -> None:
        out = self._publish(instances=False)
        self.assertEqual(out.status, "fallback")
        self.assertEqual(self.calls, 0)
        self.assertIn("aucune instance", out.message)
        self.assertTrue(out.warning().startswith("publie par l'ancien chemin : "))

    def test_failure_after_the_core_never_falls_back(self) -> None:
        out = self._publish(result=FAILED)
        self.assertEqual(self.calls, 1)
        self.assertEqual(out.status, "error")
        self.assertIn("publish Maya echoue", out.message)

    def test_missing_flow_falls_back(self) -> None:
        empty = self.tmp / "no_shipped"
        empty.mkdir()
        self.shipped = empty
        out = self._publish()
        self.assertEqual(out.status, "fallback")
        self.assertIn("publish_maya", out.message)
        self.assertEqual(self.calls, 0)

    def test_invalid_team_copy_falls_back(self) -> None:
        self._team_copy(lambda t: t.replace("type: dcc.may_publish,", "type: dcc.may_publish_typo,"))
        out = self._publish()
        self.assertEqual(out.status, "fallback")
        self.assertIn("non lance", out.message)
        self.assertEqual(self.calls, 0)

    def test_refuse_publish_stops_before_the_core(self) -> None:
        def edit(text: str) -> str:
            # Team check: If (a failing check) -> else -> RefusePublish ; then -> mayPublish.
            text = text.replace("  - {from: inst.then, to: pub.exec}\n",
                                "  - {from: inst.then, to: chk.exec}\n  - {from: ok.value, to: chk.condition}\n"
                                "  - {from: chk.then, to: pub.exec}\n  - {from: chk.else, to: refuse.exec}\n")
            return text.replace("  pub: {type: dcc.may_publish,",
                                "  ok: {type: data.value, pos: [480, 0], params: {type: bool, value: false}}\n"
                                "  chk: {type: logic.if, pos: [480, 160]}\n"
                                f'  refuse: {{type: flux.refuse_publish, pos: [480, 320], params: {{message: "{REFUSE}"}}}}\n'
                                "  pub: {type: dcc.may_publish,")
        self._team_copy(edit)
        out = self._publish()
        self.assertEqual(out.status, "refused", out.message)
        self.assertEqual(out.message, REFUSE)
        self.assertEqual(self.calls, 0)

    def test_refused_probe_blocks_a_core_reached_anyway(self) -> None:
        # A RefusePublish whose error is handled (on_error) cannot let the publish through.
        from flux_flows.nodes import dcc_publish
        from flux_flows.nodes.contract import NodeError

        ctx = SimpleNamespace(context={dcc_publish.PROBE_KEY: {"core_started": False, "refused": REFUSE}})
        with self.assertRaises(NodeError) as caught:
            dcc_publish.core_starting(ctx)
        self.assertEqual(caught.exception.message, REFUSE)
        ctx = SimpleNamespace(context={dcc_publish.PROBE_KEY: {"core_started": False, "refused": None}})
        dcc_publish.core_starting(ctx)
        self.assertTrue(ctx.context[dcc_publish.PROBE_KEY]["core_started"])


class RefusePublishNode(unittest.TestCase):
    def test_dry_run_and_empty_message(self) -> None:
        from flux_flows.nodes.contract import NodeError

        registry.ensure_builtin()
        spec = registry.get_node("flux.refuse_publish")
        got = spec.simulate(SimpleNamespace(context={}), {"message": REFUSE}, {})
        self.assertEqual(got["lines"][0]["text_fr"], f"refuserait le publish : {REFUSE}")
        with self.assertRaises(NodeError):
            spec.func(SimpleNamespace(context={}), {"message": "  "}, {})
        with self.assertRaises(NodeError) as caught:   # outside a publish run: stops the run, no probe
            spec.func(SimpleNamespace(context={}), {"message": REFUSE}, {})
        self.assertEqual(caught.exception.message, REFUSE)


class PublishCoreTimeout(unittest.TestCase):
    def test_no_engine_timeout_for_publish_cores(self) -> None:
        registry.ensure_builtin()
        run = SimpleNamespace()
        node = SimpleNamespace(params={})
        for t in ("dcc.may_publish_core", "dcc.hou_publish_core", "dcc.nk_publish_core", "dcc.zb_publish_core"):
            self.assertIsNone(engine.Run._timeout(run, node, registry.get_node(t)), t)
        other = next(s for s in registry.all_nodes() if s.family == "dcc" and not s.subflow
                     and not s.type.endswith("_publish_core"))
        self.assertEqual(engine.Run._timeout(run, node, other), engine.DCC_TIMEOUT_S)
        self.assertEqual(engine.Run._timeout(run, SimpleNamespace(params={"timeout_s": 30}),
                                             registry.get_node("dcc.may_publish_core")), 30.0)


if __name__ == "__main__":
    unittest.main()
