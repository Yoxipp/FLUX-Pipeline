# P8 step 1 (2026-10-29, PUBLISH_PARITE §4 n°15): the arguments each shipped publish subflow
# hands to the Publisher function it wraps (Nuke, Painter, Designer, Mari, ZBrush, Marvelous),
# pinned on the code BEFORE the switch. Fake bridges only, the publish functions are mocked.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flux_flows.bridges import primitives, softs
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows._fake_bridges import FakeTcpJson
from tests.test_flux_flows.test_nodes_softs import run_node

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


class PublishCoreArguments(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.srv = FakeTcpJson(lambda req: {"status": "ok"}).start()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_pub_args_"))
        (self.tmp / "PROJ").mkdir()
        self.published = str(self.tmp / "x_v007.png")
        self._p = [mock.patch("core.paths.get_project_path", side_effect=lambda name: self.tmp / name),
                   mock.patch.object(primitives, "ping", side_effect=lambda soft, port=None: {"ok": True, "version": "t",
                                                                                              "port": port})]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        self.srv.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _call(self, soft: str, node: str, target: str, inputs: dict, port=None, result=None):
        seen = {}

        def fake(*args, **kwargs):
            seen.update(args=args, kwargs=kwargs)
            return result if result is not None else {"ok": True, "published": [self.published], "version": 7}

        h.reset()
        with mock.patch(target, side_effect=fake), mock.patch("dcc.zbrush.client.zbrush_client.release"):
            rec, value = run_node(soft, node, softs.port_range(soft).start if port is None else port,
                                  inputs=inputs, out="version", project="PROJ")
        self.assertEqual(rec["status"], "ok", rec.get("error") or rec["nodes"].get("n", {}).get("error"))
        return seen, value

    def test_nuke(self) -> None:
        seen, value = self._call("nuke", "dcc.nk_publish", "dcc.nuke.nuke_publish.publish_from_nuke",
                                 {"name": "SEQ010_SH010_COMP_main", "node": "Write1", "format": "exr",
                                  "frame_range": "1001-1010", "sequence": True, "description": "d",
                                  "options": {"compression": "zip"}, "colorspace": "ACEScg"})
        self.assertEqual(seen["args"], ("PROJ", "SEQ010_SH010_COMP_main", ".exr"))
        # Gap n°4: nk_publish.flow.yml has no `options` input, the Write knobs are dropped (P8 step 3).
        self.assertEqual(seen["kwargs"], {"options": None, "is_sequence": True,
                                          "frame_range": (1001, 1010), "node_name": "Write1", "description": "d",
                                          "user": "ADAM", "colorspace": "ACEScg"})
        self.assertEqual(value, 7)

    def test_nuke_defaults(self) -> None:
        seen, _ = self._call("nuke", "dcc.nk_publish", "dcc.nuke.nuke_publish.publish_from_nuke",
                             {"name": "SEQ010_SH010_COMP_main"})
        self.assertEqual(seen["args"][2], ".exr")
        self.assertEqual(seen["kwargs"], {"options": None, "is_sequence": False, "frame_range": None,
                                          "node_name": None, "description": "", "user": "ADAM", "colorspace": None})

    def test_painter(self) -> None:
        seen, _ = self._call("painter", "dcc.sp_publish", "dcc.substance_painter.substance_export.publish_painter",
                             {"class": "PROP", "task": "TEXTURE", "name": "chair", "instance": "A",
                              "preset": "Arnold", "format": "exr", "bit_depth": "16", "size": 4096,
                              "maps": ["BaseColor"], "conform_tx": True, "description": "d"})
        self.assertEqual(seen["args"], ("PROJ",))
        self.assertEqual(seen["kwargs"], {"class_tok": "PROP", "task_tok": "TEXTURE", "name_tok": "chair",
                                          "instance": "A", "preset": "Arnold", "file_format": "exr",
                                          "bit_depth": "16", "conform_tx": True, "description": "d", "user": "ADAM",
                                          "size": 4096, "maps": ["BaseColor"]})

    def test_painter_defaults(self) -> None:
        seen, _ = self._call("painter", "dcc.sp_publish", "dcc.substance_painter.substance_export.publish_painter",
                             {"class": "PROP", "task": "TEXTURE", "name": "chair"})
        self.assertEqual(seen["kwargs"], {"class_tok": "PROP", "task_tok": "TEXTURE", "name_tok": "chair",
                                          "instance": "null", "preset": "PBR Metallic Roughness", "file_format": "png",
                                          "bit_depth": "8", "conform_tx": False, "description": "", "user": "ADAM",
                                          "size": None, "maps": None})

    def test_designer(self) -> None:
        seen, _ = self._call("designer", "dcc.sd_publish", "dcc.substance_designer.designer_export.publish_designer",
                             {"class": "PROP", "task": "TEXTURE", "name": "rock", "format": "exr", "size": 1024,
                              "bit_depth": "32", "maps": False, "sbsar": True, "sbs": True, "conform_tx": True,
                              "description": "d"})
        self.assertEqual(seen["args"], ("PROJ",))
        self.assertEqual(seen["kwargs"], {"class_tok": "PROP", "task_tok": "TEXTURE", "name_tok": "rock",
                                          "instance": "null", "file_format": "exr", "size": 1024, "bit_depth": "32",
                                          "maps": False, "sbsar": True, "sbs": True, "conform_tx": True,
                                          "description": "d", "user": "ADAM"})

    def test_mari(self) -> None:
        seen, _ = self._call("mari", "dcc.mari_publish", "dcc.mari.mari_export.publish_mari",
                             {"class": "PROP", "task": "TEXTURE", "name": "chair", "format": "exr",
                              "channels": ["diffuse"], "conform_tx": True, "description": "d"})
        self.assertEqual(seen["args"], ("PROJ",))
        self.assertEqual(seen["kwargs"], {"class_tok": "PROP", "task_tok": "TEXTURE", "name_tok": "chair",
                                          "instance": "null", "file_format": "exr", "conform_tx": True,
                                          "description": "d", "user": "ADAM", "channels": ["diffuse"]})

    def test_zbrush(self) -> None:
        seen, _ = self._call("zbrush", "dcc.zb_publish", "dcc.zbrush.zbrush_export.publish_zbrush",
                             {"name": "CHAR_SCULPT_head_null", "format": "obj", "options": {"subdiv": 2},
                              "description": "d"})
        # Gap n°4: zb_publish.flow.yml has no `options` input, they are dropped (P8 step 3).
        self.assertEqual(seen["args"], (self.tmp / "PROJ", "CHAR_SCULPT_head_null", ".obj", {}, "d", "ADAM"))
        self.assertEqual(seen["kwargs"], {"project_name": "PROJ"})

    def test_marvelous(self) -> None:
        seen, value = self._call("marvelous", "dcc.mvd_publish", "dcc.marvelous.marvelous_export.publish_marvelous",
                                 {"name": "CHAR_CLOTH_dress_null", "format": "usd", "options": {"thickness": True},
                                  "with_zprj": True, "description": "d"})
        self.assertEqual(seen["args"], ("PROJ", "CHAR_CLOTH_dress_null"))
        # Gap n°4: mvd_publish.flow.yml has no `options` input, they are dropped (P8 step 3).
        self.assertEqual(seen["kwargs"], {"file_format": "usd", "options": None, "with_zprj": True,
                                          "description": "d", "user": "ADAM"})
        self.assertEqual(value, 7)

    def test_marvelous_accepts_any_instance(self) -> None:
        # Marvelous has no base-port rule (_base_port_only): another instance still publishes.
        seen, _ = self._call("marvelous", "dcc.mvd_publish", "dcc.marvelous.marvelous_export.publish_marvelous",
                             {"name": "CHAR_CLOTH_dress_null"}, port=softs.port_range("marvelous").start + 1)
        self.assertEqual(seen["kwargs"]["file_format"], "abc")

    def test_marvelous_error_is_the_run_error(self) -> None:
        h.reset()
        with mock.patch("dcc.marvelous.marvelous_export.publish_marvelous",
                        return_value={"ok": False, "error": "pas de garment"}):
            rec, _ = run_node("marvelous", "dcc.mvd_publish", softs.port_range("marvelous").start,
                              inputs={"name": "CHAR_CLOTH_dress_null"}, project="PROJ")
        self.assertEqual(rec["status"], "error")
        self.assertIn("pas de garment", str(rec.get("error")) + str(rec["nodes"]["n"].get("error")))

    def test_version_zero_when_the_function_gives_none(self) -> None:
        # Current gap (PUBLISH_PARITE n°6): no version from publish_* and none in the record -> 0.
        _seen, value = self._call("mari", "dcc.mari_publish", "dcc.mari.mari_export.publish_mari",
                                  {"class": "PROP", "task": "TEXTURE", "name": "chair"},
                                  result={"ok": True, "published": [str(self.tmp / "nothing.tif")]})
        self.assertEqual(value, 0)


if __name__ == "__main__":
    unittest.main()
