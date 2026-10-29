# P6a (2026-10-23): mayPublish / houPublish call the Publisher's runner functions in a
# worker thread (asyncio.run inside), the shipped publish_maya / publish_houdini flows
# hand the result out by FlowOutput, a Houdini session on another instance is refused,
# the dry run computes the destination without writing. publish_core is not touched.

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from flux_flows import locations, store
from flux_flows.bridges import primitives
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._fake_bridges import FakeCommandPort, FakeHttp
from tests.test_flux_flows._fake_dcc import FakeCmds, FakeHou, install_fake_maya, maya_command_port_handler, restore_modules

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


def _shipped(name: str):
    return store.read_flow({"shipped": locations.shipped_dir()}, "shipped", name)["flow"]


class PublishBlackBox(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_pub_bb_"))
        self.project = self.tmp / "PROJ"
        (self.project / "publish").mkdir(parents=True)
        self._p = [mock.patch("core.paths.get_project_path", side_effect=lambda name: self.tmp / name)]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, flow, values, mode="real"):
        from flux_flows import engine
        import asyncio

        async def scenario():
            mgr = engine.manager()
            run = engine.Run(flow, scope="shipped", project="PROJ", user="ADAM", mode=mode, values=values)
            rec = await mgr.submit(run)
            rec = await mgr.wait(rec["run_id"])
            return rec, run._outputs

        return asyncio.run(scenario())

    def test_publish_maya_flow_calls_the_runner_in_a_thread(self) -> None:
        last = self.project / "publish" / "CHAR_MODEL_chair_null_LAST.ma"
        (self.project / "publish" / "CHAR_MODEL_chair_null_v003.ma").write_text("x")
        last.write_text("x")
        seen = {}

        def runner(**kwargs):
            seen.update(kwargs, thread=threading.current_thread().name)
            return last

        cmds = FakeCmds()
        saved = install_fake_maya(cmds)
        try:
            with FakeCommandPort(maya_command_port_handler) as srv, \
                    mock.patch.object(primitives, "scan_ports", return_value=[{"port": srv.port, "pid": 1}]), \
                    mock.patch("core.dcc_instances.resolve_port", return_value=srv.port), \
                    mock.patch("flux_actions.runner.run_maya_publish_action", side_effect=runner):
                rec, outputs = self._run(_shipped("publish_maya"),
                                         {"name": "CHAR_MODEL_chair_null", "format": ".ma", "description": "retopo"})
        finally:
            restore_modules(saved)
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertTrue(seen["thread"].startswith("flux-flows"), seen["thread"])
        self.assertEqual((seen["base_name"], seen["extension"], seen["port"], seen["description"], seen["user"]),
                         ("CHAR_MODEL_chair_null", ".ma", srv.port, "retopo", "ADAM"))
        self.assertEqual(outputs, {"path": str(last), "version": 3, "files": [str(last)], "warnings": []})

    def test_houdini_session_on_another_instance_is_refused(self) -> None:
        hou = FakeHou()
        with FakeHttp(hou.run) as srv, \
                mock.patch.object(primitives, "scan_ports", return_value=[{"port": srv.port, "pid": 1}]), \
                mock.patch("core.dcc_instances.check_active", return_value=srv.port), \
                mock.patch("flux_actions.runner.run_houdini_publish_action") as runner:
            with mock.patch("core.dcc_instances.resolve_port", side_effect=[srv.port, srv.port + 1]):
                rec, _ = self._run(_shipped("publish_houdini"), {"name": "cache", "node": "/out/cache",
                                                                 "format": ".abc"})
            runner.assert_not_called()
            self.assertIn("publie dans le Houdini choisi", rec["nodes"]["pub"]["error"])
            runner.return_value = {"ok": True, "path": str(self.project / "publish" / "FX_cache_LAST.abc"),
                                   "version": 7}
            with mock.patch("core.dcc_instances.resolve_port", return_value=srv.port):
                rec, outputs = self._run(_shipped("publish_houdini"), {"name": "cache", "node": "/out/cache",
                                                                       "format": "abc", "sequence": False})
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        kwargs = runner.call_args.kwargs
        self.assertEqual((kwargs["base_name"], kwargs["extension"], kwargs["rop_node_path"]), ("cache", ".abc", "/out/cache"))
        self.assertEqual(outputs["version"], 7)
        self.assertEqual(outputs["rop_node"], "/out/cache")   # P8: the route hands it to the Publisher

    def test_dry_run_computes_the_destination_and_writes_nothing(self) -> None:
        hou = FakeHou()
        (self.project / "publish" / "FX_SIM_smoke_null_v001.abc").write_text("x")
        with FakeHttp(hou.run) as srv, \
                mock.patch.object(primitives, "scan_ports", return_value=[{"port": srv.port, "pid": 1}]), \
                mock.patch("core.dcc_instances.resolve_port", return_value=srv.port), \
                mock.patch("features.publisher.publish_core.resolve_publish_path",
                           return_value=self.project / "publish"), \
                mock.patch("flux_actions.runner.run_houdini_publish_action") as runner:
            rec, outputs = self._run(_shipped("publish_houdini"), {"name": "FX_SIM_smoke_null", "format": ".abc"},
                                     mode="dry")
        runner.assert_not_called()
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        line = [r for r in rec["report"] if r.get("kind") == "publish"][0]
        self.assertIn("publierait FX_SIM_smoke_null v002", line["text_fr"])
        self.assertTrue(line["path"].endswith("FX_SIM_smoke_null_v002.abc"))


if __name__ == "__main__":
    unittest.main()
