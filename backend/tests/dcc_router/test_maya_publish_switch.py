# P8 step 4 (2026-10-29, ADR 0070): POST /dcc/maya/publish publishes by the flow publish_maya
# when the project is in publish v2, with the v1 response shape; a run that fails before
# its core falls back to v1 (warning in the response), a refusal is a 409, a failure after
# the core a 503 and never a second publish. The runner and the v1 action are mocked.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows.publish_runner import Outcome

BODY = {"project_name": "PROJ", "filename": "CHAR_ANIM_chair_null", "extension": ".abc", "scope": "selection",
        "frame_range": [1001, 1010, 0.5], "export_options": {"uv": True}, "description": "d {x}", "user": "ADAM",
        "port": 7005}


class MayaPublishSwitch(unittest.TestCase):
    def setUp(self) -> None:
        from routers import dcc as dcc_router

        self.tmp = Path(tempfile.mkdtemp(prefix="flux_maya_switch_"))
        (self.tmp / "PROJ").mkdir()
        self.dest = self.tmp / "PROJ" / "CHAR_ANIM_chair_null_LAST.abc"
        app = FastAPI()
        app.include_router(dcc_router.router, prefix="/dcc")
        self.client = TestClient(app)
        self.run_publish = mock.AsyncMock()
        self.v1 = mock.Mock(return_value=self.dest)
        self._p = [mock.patch("core.paths.get_project_path", side_effect=lambda name: self.tmp / name),
                   mock.patch.object(dcc_router, "_maya_target", new=mock.AsyncMock(return_value=7005)),
                   mock.patch("features.publisher.publish_core.resolve_publish_path", return_value=None),
                   mock.patch("flux_flows.publish_runner.run_publish", new=self.run_publish),
                   mock.patch("flux_actions.runner.run_maya_publish_action", new=self.v1),
                   mock.patch.dict("os.environ", {"FLUX_LEGACY_PUBLISH": ""})]
        for p in self._p:
            p.start()

    def tearDown(self) -> None:
        for p in self._p:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _post(self, v2: bool):
        with mock.patch("flux_flows.switch.flows_publish_enabled", return_value=v2) as switch:
            r = self.client.post("/dcc/maya/publish", json=BODY)
        switch.assert_called_once_with("PROJ", "maya")
        return r

    def test_v1_project_keeps_the_current_path(self) -> None:
        r = self._post(False)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"ok": True, "version_str": "001", "dest": str(self.dest)})
        self.run_publish.assert_not_called()
        self.assertEqual(self.v1.call_count, 1)

    def test_v2_publishes_by_the_flow(self) -> None:
        self.run_publish.return_value = Outcome("ok", {"path": str(self.dest), "version": 4, "files": [str(self.dest)],
                                                       "warnings": ["uv vides"]})
        r = self._post(True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"ok": True, "version_str": "v004", "dest": str(self.dest), "warnings": ["uv vides"]})
        self.v1.assert_not_called()
        args, kwargs = self.run_publish.call_args
        self.assertEqual(args, ("maya",))
        self.assertEqual((kwargs["project"], kwargs["user"]), ("PROJ", "ADAM"))
        self.assertEqual(kwargs["values"], {"name": "CHAR_ANIM_chair_null", "format": ".abc", "scope": "selection",
                                            "description": "d {x}", "frame_range": "1001.0 1010.0 0.5",
                                            "options": {"uv": True}, "port": 7005})

    def test_v2_without_version_keeps_the_preflight_one(self) -> None:
        self.run_publish.return_value = Outcome("ok", {"path": str(self.dest), "version": None})
        r = self._post(True)
        self.assertEqual(r.json(), {"ok": True, "version_str": "001", "dest": str(self.dest)})

    def test_failure_before_the_core_falls_back_to_v1(self) -> None:
        self.run_publish.return_value = Outcome("fallback", message="aucune instance Maya ouverte")
        r = self._post(True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.v1.call_count, 1)
        self.assertEqual(r.json()["warnings"], ["publie par l'ancien chemin : aucune instance Maya ouverte"])
        self.assertEqual(r.json()["dest"], str(self.dest))

    def test_refusal_is_a_409_and_never_v1(self) -> None:
        self.run_publish.return_value = Outcome("refused", message="Le nom doit finir par _null")
        r = self._post(True)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "Le nom doit finir par _null"))
        self.v1.assert_not_called()

    def test_failure_after_the_core_never_publishes_twice(self) -> None:
        self.run_publish.return_value = Outcome("error", message="pub : publish Maya echoue")
        r = self._post(True)
        self.assertEqual(r.status_code, 503)
        self.assertIn("publish Maya echoue", r.json()["detail"])
        self.v1.assert_not_called()


if __name__ == "__main__":
    unittest.main()
