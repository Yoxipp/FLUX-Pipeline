# P8 step 7 (2026-10-29, ADR 0070): parity of a publish by v1 and by the flows, through the real
# route, the real publish_runner and the real shipped flows publish_<soft> (Nuke, Painter, Designer,
# Mari, Marvelous, ZBrush). The Instance finds a fake live instance on the base port, and the
# Publisher function each path ends in (publish_from_nuke, publish_painter...) is mocked: both
# paths must call it ONCE with the same arguments and give the same response. Destination,
# version and LAST are computed inside that function, so same arguments = same files; a test
# never validates a DCC (skill dcc-testing, live check by the maintainer).
# Also: switch values read from project.json, refusal (team copy), fallback before the core,
# no fallback after it. Maya / Houdini: test_publish_runner.py and tests/dcc_router.

from __future__ import annotations

import importlib
import inspect
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import locations, store
from flux_flows.bridges import primitives, softs
from tests.test_flux_flows import _flow_helpers as h

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816

_TOKENS = {"project_name": "PROJ", "class_token": "PROP", "task_token": "TEXTURE", "name_token": "chair",
           "instance": "null", "description": "retopo $x {v}", "user": "ADAM"}
_MAPS = ["PROP_TEXTURE_chair_null_BaseColor_v002.png", "PROP_TEXTURE_chair_null_Roughness_v002.png"]

# soft: (route, body, Publisher function, its v1 result)
CASES = {
    "nuke": ("/dcc/nuke/publish",
             {"project_name": "PROJ", "filename": "SEQ010_SH010_COMP_main", "extension": ".exr",
              "export_options": {"compression": "zip"}, "is_sequence": True, "frame_range": [1001, 1050],
              "node_name": "Merge1", "colorspace": "ACES - ACEScg", "description": "comp $F", "user": "ADAM"},
             "dcc.nuke.nuke_publish.publish_from_nuke",
             {"ok": True, "path": "SEQ010_SH010_COMP_main_v004.####.exr", "version": 4, "version_str": "v004",
              "is_sequence": True}),
    "painter": ("/dcc/substance/publish",
                {**_TOKENS, "preset": "PBR Metallic Roughness", "file_format": "png", "bit_depth": "16",
                 "conform_tx": True, "texture_sets": ["chair"], "size": 2048, "padding": "color", "dilation": 8,
                 "maps": ["BaseColor"], "map_params": {"BaseColor": {"bit_depth": "8"}},
                 "channels": [{"id": "ao", "label": "AO", "gray": True}], "tx_only": True},
                "dcc.substance_painter.substance_export.publish_painter",
                {"ok": True, "published": _MAPS, "tx": [_MAPS[0][:-4] + ".tx"], "warnings": ["Height vide"]}),
    "designer": ("/dcc/designer/bridge/publish",
                 {**_TOKENS, "graphs": [{"package": "D:/w/chair.sbs", "graph": "chair", "outputs": ["basecolor"]}],
                  "file_format": "exr", "size": 4096, "bit_depth": "16f", "maps": True, "sbsar": True, "sbs": True,
                  "conform_tx": True, "tx_only": False},
                 "dcc.substance_designer.designer_export.publish_designer",
                 {"ok": True, "published": _MAPS, "tx": None, "warnings": []}),
    "mari": ("/dcc/mari/publish",
             {**_TOKENS, "file_format": "exr", "conform_tx": True, "channels": ["diffuse", "spec"],
              "channel_params": {"diffuse": {"bit_depth": "16"}}, "tx_only": True},
             "dcc.mari.mari_export.publish_mari",
             {"ok": True, "published": _MAPS, "tx": [_MAPS[0][:-4] + ".tx"], "warnings": []}),
    "marvelous": ("/dcc/marvelous/bridge/publish",
                  {"project_name": "PROJ", "target_name": "CHAR_CLOTH_dress_null", "file_format": "abc",
                   "options": {"garment": True, "scale": 10}, "with_zprj": True, "description": "sim",
                   "user": "ADAM"},
                  "dcc.marvelous.marvelous_export.publish_marvelous",
                  {"ok": True, "published": ["CHAR_CLOTH_dress_null_v003.abc", "CHAR_CLOTH_dress_null_v003.zprj"],
                   "warnings": ["avatar cache"]}),
    "zbrush": ("/dcc/zbrush/publish",
               {"project_name": "PROJ", "filename": "CHAR_SCULPT_head_null", "extension": ".obj",
                "export_options": {"subdiv": 2}, "description": "sculpt", "user": "ADAM"},
               "dcc.zbrush.zbrush_export.publish_zbrush",
               {"ok": True, "path": "CHAR_SCULPT_head_null_LAST.obj", "version": 5, "version_str": "v005"}),
}

# Differences between the two calls that are not differences of behaviour:
# the ZBrush route resolves the project path, the core passes the same Path.
_SAME = {"zbrush": lambda args: {**args, "project_path": Path(args["project_path"])}}


def _real(target: str):
    module, name = target.rsplit(".", 1)
    return getattr(importlib.import_module(module), name)


class PublishParity(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_pub_parity_"))
        self.project = self.tmp / "PROJ"
        self.project.mkdir()
        from features.folder_manager import project_config as pc

        pc.ensure_project_config(self.project)
        self.cfg_path = pc.project_config_path(self.project)
        self.team = self.tmp / "team"
        self.team.mkdir()
        self.instance: dict | None = {"pid": 1}
        roots = lambda user=None, project=None: {"shipped": locations.shipped_dir(), "team": self.team,  # noqa: E731
                                                 "project": None, "perso": None}
        self._p = [mock.patch("core.paths.get_project_path", side_effect=lambda name: self.tmp / name),
                   mock.patch.object(locations, "roots_for", side_effect=roots),
                   mock.patch("flux_flows.runs.runs_dir", return_value=None),
                   mock.patch("flux_flows.bridges.session.find_instance", side_effect=self._find),
                   mock.patch("flux_flows.bridges.session.scene_of", return_value=""),
                   mock.patch.object(primitives, "ping", side_effect=lambda soft, port=None: {"ok": True,
                                                                                              "version": "t"}),
                   mock.patch("dcc.zbrush.client.zbrush_client.release")]
        for p in self._p:
            p.start()
        app = FastAPI()
        from routers import dcc as dcc_router

        app.include_router(dcc_router.router, prefix="/dcc")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _find(self, soft, **_kw):
        if self.instance is None:
            return None
        rng = softs.port_range(soft)
        return {**self.instance, "port": rng.start if rng else None}

    def _engine(self, value) -> None:
        cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        cfg["publish_engine"] = value
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    def _publish(self, soft: str, engine, result=None):
        """(response, [bound arguments of each call of the Publisher function])."""
        route, body, target, v1_result = CASES[soft]
        sig = inspect.signature(_real(target))
        calls: list = []

        def fake(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            calls.append(_SAME.get(soft, dict)(dict(bound.arguments)))
            return dict(result if result is not None else v1_result)

        from flux_flows import publish_runner

        real_run = publish_runner.run_publish
        self.verdicts: list = []

        async def spy(*args, **kwargs):
            out = await real_run(*args, **kwargs)
            self.verdicts.append(out.status)
            return out

        self._engine(engine)
        h.reset()
        with mock.patch(target, side_effect=fake), mock.patch.object(publish_runner, "run_publish", new=spy):
            r = self.client.post(route, json=body)
        return r, calls

    def test_both_paths_publish_the_same(self) -> None:
        for soft in CASES:
            with self.subTest(soft=soft):
                r1, c1 = self._publish(soft, "v1")
                r2, c2 = self._publish(soft, "v2")
                self.assertEqual((r1.status_code, r2.status_code), (200, 200), r2.text)
                self.assertEqual((len(c1), len(c2)), (1, 1))
                self.assertEqual(self.verdicts, ["ok"])          # v2 really went through the flow
                self.assertEqual(c2[0], c1[0])
                self.assertEqual(r2.json(), r1.json())

    def test_switch_values(self) -> None:
        # Absent / unknown = v1: the flow never runs, a broken flow would not matter.
        with mock.patch("flux_flows.publish_runner.run_publish") as runner:
            for value in (None, "v3", "V1", ""):
                with self.subTest(value=value):
                    r, calls = self._publish("nuke", value)
                    self.assertEqual((r.status_code, len(calls)), (200, 1))
            runner.assert_not_called()

    def test_no_instance_falls_back_before_the_core(self) -> None:
        self.instance = None
        for soft in CASES:
            with self.subTest(soft=soft):
                r, calls = self._publish(soft, "v2")
                self.assertEqual((r.status_code, len(calls)), (200, 1), r.text)
                self.assertTrue(r.json()["warnings"][0].startswith("publie par l'ancien chemin : "))
                self.assertEqual(self.verdicts, ["fallback"])

    def test_invalid_team_copy_falls_back(self) -> None:
        text = store.shipped_file(locations.shipped_dir(), "publish_nuke").read_text(encoding="utf-8")
        path = store.working_file(self.team, "publish_nuke")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.replace("type: dcc.nk_publish,", "type: dcc.nk_publish_typo,"), encoding="utf-8")
        r, calls = self._publish("nuke", "v2")
        self.assertEqual((r.status_code, len(calls)), (200, 1), r.text)
        self.assertIn("publish_nuke", r.json()["warnings"][0])
        self.assertEqual(self.verdicts, ["fallback"])

    def test_refusal_never_publishes(self) -> None:
        text = store.shipped_file(locations.shipped_dir(), "publish_painter").read_text(encoding="utf-8")
        text = text.replace("  - {from: inst.then, to: pub.exec}\n", "  - {from: inst.then, to: refuse.exec}\n")
        text = text.replace("  pub: {type: dcc.sp_publish,",
                            "  refuse: {type: flux.refuse_publish, pos: [480, 0], params: {message: \"Pas de 16 bits\"}}\n"
                            "  pub: {type: dcc.sp_publish,")
        path = store.working_file(self.team, "publish_painter")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        r, calls = self._publish("painter", "v2")
        self.assertEqual((r.status_code, r.json()["detail"], len(calls)), (409, "Pas de 16 bits", 0))
        self.assertEqual(self.verdicts, ["refused"])

    def test_failure_after_the_core_never_publishes_twice(self) -> None:
        for soft in CASES:
            with self.subTest(soft=soft):
                r, calls = self._publish(soft, "v2", result={"ok": False, "error": "disque plein"})
                self.assertEqual((r.status_code, len(calls)), (503, 1), r.text)
                self.assertIn("disque plein", r.json()["detail"])
                self.assertEqual(self.verdicts, ["error"])       # the core failed: v1 never ran


if __name__ == "__main__":
    unittest.main()
