# P6a (2026-10-23): may* nodes against a fake Maya (the code they send runs on a stand-in
# of `maya.cmds` behind a fake commandPort). Proves the calls, NOT Maya.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_flows.bridges import primitives
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._fake_bridges import FakeCommandPort
from tests.test_flux_flows._fake_dcc import FakeCmds, install_fake_maya, maya_command_port_handler, restore_modules

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


class MayaNodes(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_may_nodes_"))
        self.cmds = FakeCmds()
        self.cmds.nodes = {"|chair_grp": "transform", "|chair_grp|chair_geo": "transform",
                           "|chair_grp|chair_geo|chair_geoShape": "mesh", "|tmp_geo": "transform"}
        self.saved = install_fake_maya(self.cmds)
        self.srv = FakeCommandPort(maya_command_port_handler).start()
        self._p = [mock.patch.object(primitives, "scan_ports", return_value=[{"port": self.srv.port, "pid": 1}]),
                   mock.patch("core.dcc_instances.resolve_port", return_value=self.srv.port)]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        self.srv.close()
        restore_modules(self.saved)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_node(self, node_type: str, params=None, inputs=None, out: str = None, mode: str = "real"):
        nodes = {"ev": "event.manual", "inst": "session.may_instance",
                 "n": (node_type, {**(params or {}), **(inputs or {})}), "rec": "action.t_record"}
        links = ["ev.then->inst.exec", "inst.then->n.exec", "inst.session->n.session", "n.then->rec.exec"]
        if out:
            links.append(f"n.{out}->rec.value")
        rec = h.run_flow(h.flow(nodes, links), mode=mode, checked=False)
        return rec, (h.CALLS[-1][1] if h.CALLS else None)

    def test_open_save_save_as(self) -> None:
        self.cmds.modified = True
        rec, _ = self.run_node("dcc.may_open_scene", inputs={"path": "/p/b.ma"})
        self.assertIn("non enregistree", rec["nodes"]["n"]["error"])
        rec, value = self.run_node("dcc.may_open_scene", {"discard_changes": True}, {"path": "/p/b.ma"}, "scene")
        self.assertEqual(value, "/p/b.ma")
        rec, value = self.run_node("dcc.may_save_scene", out="path")
        self.assertEqual((rec["status"], value), ("ok", "/p/b.ma"))
        target = str(self.tmp / "c.mb").replace("\\", "/")
        rec, value = self.run_node("dcc.may_save_as", {"copy": True}, {"path": target}, "path")
        self.assertEqual((value, self.cmds.scene), (target, "/p/b.ma"))
        export_call = [c for c in self.cmds.calls if c[2].get("exportAll")][0]
        self.assertEqual(export_call[2]["type"], "mayaBinary")
        rec, _ = self.run_node("dcc.may_save_as", inputs={"path": str(self.tmp / "c.obj")})
        self.assertIn("extension de scene", rec["nodes"]["n"]["error"])

    def test_find_set_get(self) -> None:
        rec, value = self.run_node("dcc.may_find_nodes", {"pattern": "*_geo ^tmp*", "type": "transform"}, out="nodes")
        self.assertEqual(value, ["|chair_grp|chair_geo"])
        self.run_node("dcc.may_set_attr", inputs={"node": "|chair_grp", "attr": "translate", "value": [1, 2, 3]})
        rec, value = self.run_node("dcc.may_get_attr", inputs={"node": "|chair_grp", "attr": "translate"}, out="value")
        self.assertEqual(value, [1, 2, 3])
        self.run_node("dcc.may_set_attr", inputs={"node": "|chair_grp", "attr": "notes", "value": "hello"})
        self.assertEqual(self.cmds.attrs["|chair_grp.notes"], "hello")

    def test_run_script(self) -> None:
        rec, value = self.run_node("dcc.may_run_script", inputs={"code": "result = len(cmds.ls()) + args['k']",
                                                                 "args": {"k": 10}}, out="result")
        self.assertEqual(value, 14)

    def test_import_reference_and_tagged_import(self) -> None:
        src = self.tmp / "chair_model_LAST.ma"
        src.write_text("x")
        rec, value = self.run_node("dcc.may_import", {"mode": "reference"}, {"path": str(src)}, "nodes")
        self.assertEqual(value, ["chair_model_LAST:root"])
        with mock.patch("dcc.maya.maya_hub.import_into_maya", return_value={"ok": True, "file": "x.ma"}) as imp:
            rec, value = self.run_node("dcc.may_import", inputs={"path": str(src)}, out="nodes")
        self.assertEqual(value, ["x.ma"])
        self.assertEqual(imp.call_args.kwargs["mode"], "import")

    def test_update_ref_dry_lists_and_real_replaces(self) -> None:
        plan = {"ok": True, "message": "1 mis a jour", "items": [{"node": "|a", "status": "update"}],
                "updated": ["|a"], "skipped": 0}
        with mock.patch("dcc.maya.maya_hub.update_imports", return_value=plan) as upd:
            dry, _ = self.run_node("dcc.may_update_ref", mode="dry")
            self.assertTrue(upd.call_args.kwargs["dry"])
            self.assertTrue(any("remplacerait |a" in r["text_fr"] for r in dry["report"]))
            rec, value = self.run_node("dcc.may_update_ref", out="updated")
        self.assertEqual(value, ["|a"])

    def test_module_call_goes_through_the_session(self) -> None:
        from flux_flows.bridges.session import MayaLiveSession
        from flux_flows.nodes.dcc_maya import maya_module_call

        fake = mock.Mock()
        fake.run.return_value = {"ok": True, "result": True}
        self.assertEqual(maya_module_call(fake, "maya_update", "run_list")["error"], "Maya n'a rien renvoye")
        code = fake.run.call_args.args[0]
        self.assertIn("from dcc.maya import maya_update as _mu", code)
        self.assertIsInstance(MayaLiveSession(1), MayaLiveSession)

    def test_playblast_is_live_only(self) -> None:
        from flux_flows import validate

        flow = h.flow({"ev": "event.manual", "inst": ("session.may_instance", {"mode": "headless"}),
                       "pb": ("dcc.may_playblast", {"path": "/p/a.mov"})},
                      ["ev.then->inst.exec", "inst.then->pb.exec", "inst.session->pb.session"])
        codes = {(i.code, i.node) for i in validate.validate(flow, validate.Env())}
        self.assertIn(("E_LIVE_ONLY", "pb"), codes)
        with mock.patch("flux_flows.nodes.dcc_maya.maya_module_call",
                        return_value={"ok": True, "file": "/p/a.mov"}) as call:
            rec, value = self.run_node("dcc.may_playblast", {"frame_range": "1-10", "size": "640x360"},
                                       {"path": "/p/a.mov"}, "file")
        self.assertEqual(value, "/p/a.mov")
        self.assertEqual(call.call_args.args[1:3], ("maya_playblast", "run_playblast"))
        rec, _ = self.run_node("dcc.may_playblast", {"size": "big"}, {"path": "/p/a.mov"})
        self.assertIn("size invalide", rec["nodes"]["n"]["error"])


if __name__ == "__main__":
    unittest.main()
