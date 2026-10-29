# P6a refactor (2026-10-23): the hub side of a Maya import and of the MAJ update, out of
# routers/dcc.py (shared by the routes and the Flows nodes mayImport / mayUpdateRef).

from __future__ import annotations

import base64
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dcc.maya import maya_hub


def _decoded_args(cmd: str) -> list:
    return [base64.b64decode(m).decode("utf-8") for m in re.findall(r"b64decode\('([^']*)'\)", cmd)]


class ImportIntoMaya(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_maya_hub_"))
        self.file = self.tmp / "chair_model_LAST.fbx"
        self.file.write_text("fbx", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _send(self, ok: bool):
        calls = []

        def send(cmd, timeout, port):
            calls.append((cmd, port))
            backend, src, result_path, tag = _decoded_args(cmd)
            Path(result_path).write_text(json.dumps({"ok": ok, "logs": [{"level": "ERROR", "msg": "boom"}]}),
                                         encoding="utf-8")
            return "ok"
        return send, calls

    def test_import_ok_sends_the_tagged_file(self) -> None:
        send, calls = self._send(True)
        out = maya_hub.import_into_maya(self.file, port=7002, project_name="P", rel_path="ASSET/chair_model_LAST.fbx",
                                        send=send)
        self.assertEqual(out["ok"], True)
        cmd, port = calls[0]
        self.assertEqual(port, 7002)
        tag = json.loads(_decoded_args(cmd)[3])
        self.assertEqual((tag["project"], tag["source"], tag["mode"]), ("P", "ASSET/chair_model_LAST.fbx", "import"))

    def test_failed_envelope_is_an_error(self) -> None:
        send, _ = self._send(False)
        with self.assertRaises(maya_hub.MayaHubError) as err:
            maya_hub.import_into_maya(self.file, port=7001, project_name="P", rel_path="a.fbx", send=send)
        self.assertEqual(err.exception.status, 500)
        self.assertIn("boom", err.exception.message)

    def test_no_answer_and_bad_inputs(self) -> None:
        with self.assertRaises(maya_hub.MayaHubError) as err:
            maya_hub.import_into_maya(self.file, port=7001, project_name="P", rel_path="a.fbx",
                                      send=lambda *a, **k: None)
        self.assertEqual(err.exception.status, 503)
        with self.assertRaises(maya_hub.MayaHubError):
            maya_hub.import_into_maya(self.tmp / "a.txt", port=7001, project_name="P", rel_path="a.txt")
        with self.assertRaises(maya_hub.MayaHubError):
            maya_hub.import_into_maya(self.file, port=7001, project_name="P", rel_path="a.fbx", mode="proxy")


class UpdateImports(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_maya_upd_"))
        (self.tmp / "P").mkdir()
        (self.tmp / "P" / "a_LAST.fbx").write_text("new", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _call(self, replaced):
        def call(port, func, *args, timeout=60.0):
            if func == "run_list":
                return {"items": [{"node": "|a_grp", "project": "P", "source": "a_LAST.fbx", "stamp": "old",
                                   "mode": "import"}]}
            replaced.append(args)
            return {"ok": True}
        return call

    def test_update_and_dry_plan(self) -> None:
        replaced = []
        with mock.patch("core.paths.get_project_path", side_effect=lambda p: self.tmp / p):
            dry = maya_hub.update_imports(7001, dry=True, call=self._call(replaced))
            self.assertEqual((replaced, dry["items"][0]["status"]), ([], "update"))
            out = maya_hub.update_imports(7001, call=self._call(replaced))
        self.assertEqual((out["ok"], out["updated"]), (True, ["|a_grp"]))
        self.assertEqual(replaced[0][0], "|a_grp")

    def test_maya_silent_is_503(self) -> None:
        with self.assertRaises(maya_hub.MayaHubError) as err:
            maya_hub.update_imports(7001, call=lambda *a, **k: None)
        self.assertEqual(err.exception.status, 503)


class Routes(unittest.TestCase):
    def test_route_maps_the_hub_error(self) -> None:
        from routers import dcc as dcc_router

        app = FastAPI()
        app.include_router(dcc_router.router, prefix="/dcc")
        client = TestClient(app)
        with mock.patch.object(maya_hub, "update_imports", side_effect=maya_hub.MayaHubError(503, "Maya ne repond pas")), \
             mock.patch.object(dcc_router, "_maya_target", new=mock.AsyncMock(return_value=7001)):
            r = client.post("/dcc/maya/update-imports", json={})
        self.assertEqual((r.status_code, r.json()["detail"]), (503, "Maya ne repond pas"))


if __name__ == "__main__":
    unittest.main()
