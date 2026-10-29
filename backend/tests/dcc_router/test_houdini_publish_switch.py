# P8 step 5 (2026-10-29, ADR 0070): POST /dcc/houdini/publish publishes by the flow
# publish_houdini when the project is in publish v2, with the v1 response shape (rop_node
# included); a run that fails before its core falls back to v1 with a warning, a refusal is
# a 409, a failure after the core a 503 and never a second publish. Runner and v1 mocked.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows.publish_runner import Outcome

BODY = {"project_name": "PROJ", "filename": "FX_SIM_smoke_null", "extension": ".bgeo.sc", "rop_node_path": None,
        "is_sequence": True, "frame_range": [1001, 1050, 1], "frame_padding": 4, "export_options": {"trange": 1},
        "attr_filter": {"mode": "keep", "names": ["P"]}, "description": "d $F", "user": "ADAM"}


class HoudiniPublishSwitch(unittest.TestCase):
    def setUp(self) -> None:
        from routers import dcc as dcc_router

        self.tmp = Path(tempfile.mkdtemp(prefix="flux_hou_switch_"))
        (self.tmp / "PROJ").mkdir()
        self.dest = str(self.tmp / "PROJ" / "FX_SIM_smoke_null_v004")
        self.v1_result = {"ok": True, "path": self.dest, "version": 4, "version_str": "v004",
                          "rop_node": "/out/smoke", "is_sequence": True}
        app = FastAPI()
        app.include_router(dcc_router.router, prefix="/dcc")
        self.client = TestClient(app)
        self.run_publish = mock.AsyncMock()
        self.v1 = mock.Mock(return_value=self.v1_result)
        self._p = [mock.patch("core.paths.get_project_path", side_effect=lambda name: self.tmp / name),
                   mock.patch("flux_flows.publish_runner.run_publish", new=self.run_publish),
                   mock.patch("flux_actions.runner.run_houdini_publish_action", new=self.v1),
                   mock.patch.dict("os.environ", {"FLUX_LEGACY_PUBLISH": ""})]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _post(self, v2: bool):
        with mock.patch("flux_flows.switch.flows_publish_enabled", return_value=v2) as switch:
            r = self.client.post("/dcc/houdini/publish", json=BODY)
        switch.assert_called_once_with("PROJ", "houdini")
        return r

    def test_v1_project_keeps_the_current_path(self) -> None:
        r = self._post(False)
        self.assertEqual((r.status_code, r.json()), (200, self.v1_result))
        self.run_publish.assert_not_called()

    def test_v2_gives_the_v1_shape(self) -> None:
        self.run_publish.return_value = Outcome("ok", {"path": self.dest, "version": 4, "files": [self.dest],
                                                       "warnings": [], "rop_node": "/out/smoke"})
        r = self._post(True)
        self.assertEqual((r.status_code, r.json()), (200, self.v1_result))
        self.v1.assert_not_called()
        args, kwargs = self.run_publish.call_args
        self.assertEqual((args, kwargs["project"], kwargs["user"]), (("houdini",), "PROJ", "ADAM"))
        self.assertEqual(kwargs["values"], {"name": "FX_SIM_smoke_null", "node": "", "format": ".bgeo.sc",
                                            "description": "d $F", "sequence": True, "frame_padding": 4,
                                            "frame_range": "1001 1050 1", "options": {"trange": 1},
                                            "attr_filter": {"mode": "keep", "names": ["P"]}})

    def test_v2_warnings_are_added(self) -> None:
        self.run_publish.return_value = Outcome("ok", {"path": self.dest, "version": 4, "warnings": ["P manquant"],
                                                       "rop_node": "/out/smoke"})
        self.assertEqual(self._post(True).json()["warnings"], ["P manquant"])

    def test_failure_before_the_core_falls_back_to_v1(self) -> None:
        self.run_publish.return_value = Outcome("fallback", message="aucune instance Houdini ouverte")
        r = self._post(True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.v1.call_count, 1)
        self.assertEqual(r.json(), {**self.v1_result,
                                    "warnings": ["publie par l'ancien chemin : aucune instance Houdini ouverte"]})

    def test_refusal_is_a_409_and_never_v1(self) -> None:
        self.run_publish.return_value = Outcome("refused", message="Pas de cache sans plage")
        r = self._post(True)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Pas de cache sans plage"))
        self.v1.assert_not_called()

    def test_failure_after_the_core_never_publishes_twice(self) -> None:
        self.run_publish.return_value = Outcome("error", message="pub : publish Houdini echoue")
        r = self._post(True)
        self.assertEqual(r.status_code, 503)
        self.v1.assert_not_called()


if __name__ == "__main__":
    unittest.main()
