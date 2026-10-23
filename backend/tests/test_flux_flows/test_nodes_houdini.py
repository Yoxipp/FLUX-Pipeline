# P6a (2026-10-23): hou* nodes against a fake Houdini (the code they send runs on a
# stand-in of `hou` behind a fake HTTP bridge). Proves the calls, NOT Houdini.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_flows.bridges import primitives
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._fake_bridges import FakeHttp
from tests.test_flux_flows._fake_dcc import FakeHou

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


class HoudiniNodes(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_hou_nodes_"))
        self.hou = FakeHou()
        self.hou.add("/obj/geo1", "geo", "Object")
        self.hou.add("/obj/geo1/OUT", "null", tx=0.0)
        self.hou.add("/out/karma1", "karma", "Driver", picture="/r/beauty.$F4.exr", f1=1, f2=3, f3=1)
        self.srv = FakeHttp(self.hou.run).start()
        self._p = [mock.patch.object(primitives, "scan_ports", return_value=[{"port": self.srv.port, "pid": 1}]),
                   mock.patch("core.dcc_instances.resolve_port", return_value=self.srv.port)]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        self.srv.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_node(self, node_type: str, params=None, inputs=None, out: str = None, mode: str = "real"):
        """ev -> HoudiniInstance -> node (-> t_record of output *out*). inputs: literal values."""
        nodes = {"ev": "event.manual", "inst": "session.hou_instance",
                 "n": (node_type, {**(params or {}), **(inputs or {})}), "rec": "action.t_record"}
        links = ["ev.then->inst.exec", "inst.then->n.exec", "inst.session->n.session", "n.then->rec.exec"]
        if out:
            links.append(f"n.{out}->rec.value")
        rec = h.run_flow(h.flow(nodes, links), mode=mode, checked=False)
        value = h.CALLS[-1][1] if h.CALLS else None
        return rec, value

    def test_open_scene_refuses_unsaved_changes(self) -> None:
        self.hou.unsaved = True
        rec, _ = self.run_node("dcc.hou_open_scene", inputs={"path": "/p/b.hip"})
        self.assertIn("non enregistree", rec["nodes"]["n"]["error"])
        rec, value = self.run_node("dcc.hou_open_scene", {"discard_changes": True}, {"path": "/p/b.hip"}, "scene")
        self.assertEqual((rec["status"], value, self.hou.file), ("ok", "/p/b.hip", "/p/b.hip"))
        rec, value = self.run_node("dcc.hou_open_scene", {"new": True}, out="scene")
        self.assertEqual(value, "untitled.hip")

    def test_save_scene_in_place_and_under_a_name(self) -> None:
        self.hou.file = "/p/a.hip"
        rec, value = self.run_node("dcc.hou_save_scene", out="path")
        self.assertEqual((value, self.hou.saved), ("/p/a.hip", ["/p/a.hip"]))
        target = self.tmp / "b.hip"
        rec, value = self.run_node("dcc.hou_save_scene", inputs={"path": str(target)}, out="path")
        self.assertEqual((rec["status"], self.hou.file), ("ok", str(target).replace("\\", "/")))
        target.write_text("x")
        rec, _ = self.run_node("dcc.hou_save_scene", inputs={"path": str(target)})
        self.assertIn("existe deja", rec["nodes"]["n"]["error"])
        rec, _ = self.run_node("dcc.hou_save_scene", {"overwrite": True}, {"path": str(target)})
        self.assertEqual(rec["status"], "ok")

    def test_save_as_copy_and_increment(self) -> None:
        self.hou.file = "/p/a.hip"
        (self.tmp / "shot_v001.hip").write_text("x")
        rec, value = self.run_node("dcc.hou_save_as", {"copy": True, "increment": True},
                                   {"path": str(self.tmp / "shot.hip")}, "path")
        self.assertTrue(value.endswith("shot_v002.hip"), value)
        self.assertEqual(self.hou.file, "/p/a.hip")              # copy: the open scene keeps its name

    def test_run_script_with_args(self) -> None:
        rec, value = self.run_node("dcc.hou_run_script",
                                   inputs={"code": "result = args['n'] * 2 + hou.frame()", "args": {"n": 4}},
                                   out="result")
        self.assertEqual((rec["status"], value), ("ok", 1009))
        rec, _ = self.run_node("dcc.hou_run_script")
        self.assertIn("attend `code`", rec["nodes"]["n"]["error"])

    def test_find_get_set_selected(self) -> None:
        rec, value = self.run_node("dcc.hou_find_node", {"pattern": "OUT", "root": "/obj"}, out="node")
        self.assertEqual(value, "/obj/geo1/OUT")
        rec, value = self.run_node("dcc.hou_find_nodes", {"pattern": "*", "type": "karma"}, out="count")
        self.assertEqual(value, 1)
        self.run_node("dcc.hou_set_parm", inputs={"node": "/obj/geo1/OUT", "parm": "tx", "value": 2.5})
        rec, value = self.run_node("dcc.hou_get_parm", inputs={"node": "/obj/geo1/OUT", "parm": "tx"}, out="value")
        self.assertEqual(value, 2.5)
        rec, _ = self.run_node("dcc.hou_get_parm", inputs={"node": "/obj/geo1/OUT", "parm": "nope"})
        self.assertIn("parm introuvable", rec["nodes"]["n"]["error"])
        self.hou.selected = ["/out/karma1"]
        rec, value = self.run_node("dcc.hou_selected", out="nodes")
        self.assertEqual(value, ["/out/karma1"])

    def test_cook_rop_and_node(self) -> None:
        rec, _ = self.run_node("dcc.hou_cook_node", {"frame_range": "1-3"}, {"node": "/out/karma1"})
        self.assertEqual((rec["status"], self.hou.nodes["/out/karma1"].renders), ("ok", [(1, 3, 1)]))
        self.run_node("dcc.hou_cook_node", {"force": True}, {"node": "/obj/geo1/OUT"})
        self.assertEqual(self.hou.nodes["/obj/geo1/OUT"].cooks, 1)

    def test_render_lists_frames_and_dry_run_cooks_nothing(self) -> None:
        rec, value = self.run_node("dcc.hou_render", {"frame_range": "1-2"}, {"node": "/out/karma1"}, "files")
        self.assertEqual(value, ["/r/beauty.0001.exr", "/r/beauty.0002.exr"])
        renders = list(self.hou.nodes["/out/karma1"].renders)
        dry, _ = self.run_node("dcc.hou_render", {"frame_range": "1-2"}, {"node": "/out/karma1"}, mode="dry")
        self.assertEqual(self.hou.nodes["/out/karma1"].renders, renders)
        self.assertTrue(any("rendrait /out/karma1" in r["text_fr"] for r in dry["report"]))

    def test_export_and_import_reuse_the_hub_code_with_the_session(self) -> None:
        with mock.patch("dcc.houdini.houdini_export.export_via_node", return_value={"ok": True}) as export:
            rec, value = self.run_node("dcc.hou_export", {"frame_range": "1001-1010"},
                                       {"path": str(self.tmp / "rock.bgeo.sc"), "node": "/obj/geo1/OUT"}, "files")
        args, kwargs = export.call_args
        self.assertEqual((args[0], args[1], args[3]), ("/obj/geo1/OUT", ".bgeo.sc", (1001, 1010, 1)))
        self.assertEqual(kwargs["client"].port, self.srv.port)
        with mock.patch("dcc.houdini.houdini_import.import_into_lop",
                        return_value={"ok": True, "result": {"node_path": "/stage/ref1"}}) as imp:
            rec, value = self.run_node("dcc.hou_import", {"mode": "reference"}, {"path": "/p/a.usd"}, "nodes")
        self.assertEqual(value, ["/stage/ref1"])
        self.assertEqual(imp.call_args.args[1], "reference")


if __name__ == "__main__":
    unittest.main()
