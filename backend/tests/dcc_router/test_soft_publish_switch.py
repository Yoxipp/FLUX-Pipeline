# P8 step 6 (2026-10-29, ADR 0070): POST /dcc/<soft>/publish of Nuke, Painter, Designer, Mari,
# Marvelous and ZBrush publish by the flow publish_<soft> when the project is in publish v2,
# with the v1 response shape; a run that fails before its core falls back to v1 with a
# warning, a refusal is a 409, a failure after the core a 503 and never a second publish.
# One class per soft on a shared base; runner and v1 function mocked.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows.publish_runner import Outcome


class _SoftSwitch:
    """Shared checks; a subclass sets the route, the soft, the body, the v1 function and results."""

    route = ""
    soft = ""
    body: dict = {}
    v1_target = ""            # dotted path of the v1 function the route imports
    v1_result: dict = {}
    flow_outputs: dict = {}   # outputs of a run that published
    flow_values: dict = {}    # values the route must hand to the flow
    v2_result: dict = {}      # the response the route must build from flow_outputs

    def setUp(self) -> None:
        from routers import dcc as dcc_router

        self.tmp = Path(tempfile.mkdtemp(prefix=f"flux_{self.soft}_switch_"))
        (self.tmp / "PROJ").mkdir()
        app = FastAPI()
        app.include_router(dcc_router.router, prefix="/dcc")
        self.client = TestClient(app)
        self.run_publish = mock.AsyncMock()
        self.v1 = mock.Mock(return_value=dict(self.v1_result))
        self._p = [mock.patch("core.paths.get_project_path", side_effect=lambda name: self.tmp / name),
                   mock.patch("flux_flows.publish_runner.run_publish", new=self.run_publish),
                   mock.patch(self.v1_target, new=self.v1)]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _post(self, v2: bool):
        with mock.patch("flux_flows.switch.flows_publish_enabled", return_value=v2) as switch:
            r = self.client.post(self.route, json=self.body)
        switch.assert_called_once_with("PROJ", self.soft)
        return r

    def test_v1_project_keeps_the_current_path(self) -> None:
        r = self._post(False)
        self.assertEqual((r.status_code, r.json()), (200, self.v1_result))
        self.run_publish.assert_not_called()

    def test_v2_gives_the_v1_shape(self) -> None:
        self.run_publish.return_value = Outcome("ok", dict(self.flow_outputs))
        r = self._post(True)
        self.assertEqual((r.status_code, r.json()), (200, self.v2_result), r.text)
        self.v1.assert_not_called()
        args, kwargs = self.run_publish.call_args
        self.assertEqual((args, kwargs["project"], kwargs["user"]), ((self.soft,), "PROJ", "ADAM"))
        self.assertEqual(kwargs["values"], self.flow_values)

    def test_v2_warnings_are_given(self) -> None:
        self.run_publish.return_value = Outcome("ok", {**self.flow_outputs, "warnings": ["map vide"]})
        self.assertEqual(self._post(True).json()["warnings"], ["map vide"])

    def test_failure_before_the_core_falls_back_to_v1(self) -> None:
        self.run_publish.return_value = Outcome("fallback", message="aucune instance ouverte")
        r = self._post(True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.v1.call_count, 1)
        warnings = ["publie par l'ancien chemin : aucune instance ouverte", *(self.v1_result.get("warnings") or [])]
        self.assertEqual(r.json(), {**self.v1_result, "warnings": warnings})

    def test_refusal_is_a_409_and_never_v1(self) -> None:
        self.run_publish.return_value = Outcome("refused", message="Pas de publish le vendredi")
        r = self._post(True)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Pas de publish le vendredi"))
        self.v1.assert_not_called()

    def test_failure_after_the_core_never_publishes_twice(self) -> None:
        self.run_publish.return_value = Outcome("error", message="pub : publish echoue")
        r = self._post(True)
        self.assertEqual(r.status_code, 503)
        self.assertIn("pub : publish echoue", r.json()["detail"])
        self.v1.assert_not_called()


class NukePublishSwitch(_SoftSwitch, unittest.TestCase):
    route, soft = "/dcc/nuke/publish", "nuke"
    v1_target = "dcc.nuke.nuke_publish.publish_from_nuke"
    body = {"project_name": "PROJ", "filename": "SEQ010_SH010_COMP_main", "extension": ".exr",
            "export_options": {"compression": "zip"}, "is_sequence": True, "frame_range": [1001, 1050],
            "node_name": "Merge1", "colorspace": None, "description": None, "user": "ADAM"}
    v1_result = {"ok": True, "path": "D:/p/SEQ010_SH010_COMP_main_v004.####.exr", "version": 4,
                 "version_str": "v004", "is_sequence": True}
    flow_outputs = {"path": "D:/p/SEQ010_SH010_COMP_main_v004.####.exr", "version": 4,
                    "files": ["D:/p/SEQ010_SH010_COMP_main_v004.####.exr"], "warnings": []}
    flow_values = {"name": "SEQ010_SH010_COMP_main", "node": "Merge1", "format": ".exr",
                   "options": {"compression": "zip"}, "sequence": True, "frame_range": "1001 1050",
                   "colorspace": "", "description": ""}
    v2_result = v1_result


_TOKENS = {"project_name": "PROJ", "class_token": "PROP", "task_token": "TEXTURE", "name_token": "chair",
           "instance": "null", "description": "d", "user": "ADAM"}
_MAPS = ["D:/p/PROP_TEXTURE_chair_null_BaseColor_v002.png", "D:/p/PROP_TEXTURE_chair_null_Roughness_v002.png"]


class PainterPublishSwitch(_SoftSwitch, unittest.TestCase):
    route, soft = "/dcc/substance/publish", "painter"
    v1_target = "dcc.substance_painter.substance_export.publish_painter"
    body = {**_TOKENS, "file_format": "png", "bit_depth": "16", "conform_tx": True, "texture_sets": ["chair"],
            "maps": ["BaseColor"], "map_params": {"BaseColor": {"bit_depth": "8"}}}
    v1_result = {"ok": True, "published": _MAPS, "tx": [_MAPS[0][:-4] + ".tx"], "warnings": ["Height vide"]}
    flow_outputs = {"path": _MAPS[0], "version": 2, "files": _MAPS, "warnings": ["Height vide"],
                    "tx": [_MAPS[0][:-4] + ".tx"]}
    flow_values = {"class": "PROP", "task": "TEXTURE", "name": "chair", "instance": "null",
                   "preset": "PBR Metallic Roughness", "format": "png", "bit_depth": "16", "maps": ["BaseColor"],
                   "conform_tx": True, "description": "d",
                   "options": {"texture_sets": ["chair"], "padding": "infinite", "dilation": 16,
                               "map_params": {"BaseColor": {"bit_depth": "8"}}, "channels": None, "tx_only": False}}
    v2_result = v1_result


class DesignerPublishSwitch(_SoftSwitch, unittest.TestCase):
    route, soft = "/dcc/designer/bridge/publish", "designer"
    v1_target = "dcc.substance_designer.designer_export.publish_designer"
    body = {**_TOKENS, "graphs": [{"package": "D:/w/chair.sbs", "graph": "chair", "outputs": None}],
            "file_format": "png", "size": 2048, "bit_depth": None, "sbsar": True, "tx_only": True,
            "conform_tx": True}
    v1_result = {"ok": True, "published": _MAPS, "tx": None, "warnings": []}
    flow_outputs = {"path": _MAPS[0], "version": 2, "files": _MAPS, "warnings": [], "tx": []}
    flow_values = {"class": "PROP", "task": "TEXTURE", "name": "chair", "instance": "null", "format": "png",
                   "size": 2048, "maps": True, "sbsar": True, "sbs": False, "conform_tx": True, "description": "d",
                   "options": {"graphs": [{"package": "D:/w/chair.sbs", "graph": "chair", "outputs": None}],
                               "tx_only": True}}
    v2_result = v1_result


class MariPublishSwitch(_SoftSwitch, unittest.TestCase):
    route, soft = "/dcc/mari/publish", "mari"
    v1_target = "dcc.mari.mari_export.publish_mari"
    body = {**_TOKENS, "file_format": "exr", "conform_tx": True, "channels": ["diffuse"],
            "channel_params": {"diffuse": {"bit_depth": "16"}}}
    v1_result = {"ok": True, "published": _MAPS, "tx": [_MAPS[0][:-4] + ".tx"], "warnings": []}
    flow_outputs = {"path": _MAPS[0], "version": 2, "files": _MAPS, "warnings": [], "tx": [_MAPS[0][:-4] + ".tx"]}
    flow_values = {"class": "PROP", "task": "TEXTURE", "name": "chair", "instance": "null", "format": "exr",
                   "channels": ["diffuse"], "conform_tx": True, "description": "d",
                   "options": {"channel_params": {"diffuse": {"bit_depth": "16"}}, "tx_only": False}}
    v2_result = v1_result


class MarvelousPublishSwitch(_SoftSwitch, unittest.TestCase):
    route, soft = "/dcc/marvelous/bridge/publish", "marvelous"
    v1_target = "dcc.marvelous.marvelous_export.publish_marvelous"
    body = {"project_name": "PROJ", "target_name": "CHAR_CLOTH_dress_null", "file_format": "abc",
            "options": {"garment": True, "scale": 1}, "with_zprj": True, "description": None, "user": "ADAM"}
    v1_result = {"ok": True, "published": ["D:/p/CHAR_CLOTH_dress_null_v003.abc", "D:/p/CHAR_CLOTH_dress_null_v003.zprj"],
                 "warnings": []}
    flow_outputs = {"path": "D:/p/CHAR_CLOTH_dress_null_v003.abc", "version": 3,
                    "files": ["D:/p/CHAR_CLOTH_dress_null_v003.abc", "D:/p/CHAR_CLOTH_dress_null_v003.zprj"],
                    "warnings": []}
    flow_values = {"name": "CHAR_CLOTH_dress_null", "format": "abc", "options": {"garment": True, "scale": 1},
                   "with_zprj": True, "description": ""}
    v2_result = v1_result


class ZBrushPublishSwitch(_SoftSwitch, unittest.TestCase):
    route, soft = "/dcc/zbrush/publish", "zbrush"
    v1_target = "dcc.zbrush.zbrush_export.publish_zbrush"
    body = {"project_name": "PROJ", "filename": "CHAR_SCULPT_head_null", "extension": ".ztl",
            "export_options": {"subdiv": 2}, "description": "d", "user": "ADAM"}
    v1_result = {"ok": True, "path": "D:/p/CHAR_SCULPT_head_null_LAST.ztl", "version": 5, "version_str": "v005"}
    flow_outputs = {"path": "D:/p/CHAR_SCULPT_head_null_LAST.ztl", "version": 5,
                    "files": ["D:/p/CHAR_SCULPT_head_null_LAST.ztl"], "warnings": []}
    flow_values = {"name": "CHAR_SCULPT_head_null", "format": ".ztl", "options": {"subdiv": 2}, "description": "d"}
    v2_result = v1_result

    def test_v2_keep_local_copies_the_publish(self) -> None:
        src = self.tmp / "PROJ" / "CHAR_SCULPT_head_null_LAST.ztl"
        src.write_bytes(b"ztl")
        local = self.tmp / "local"
        local.mkdir()
        self.run_publish.return_value = Outcome("ok", {"path": str(src), "version": 5})
        with mock.patch("flux_flows.switch.flows_publish_enabled", return_value=True):
            r = self.client.post(self.route, json={**self.body, "keep_local": True, "local_dir": str(local)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((local / src.name).read_bytes(), b"ztl")


if __name__ == "__main__":
    unittest.main()
