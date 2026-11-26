# Production "Ouvrir le JSON": the backend resolves production.json and hands it
# to the system editor (os.startfile, mocked here).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.json_repository import JsonFileRepository
from routers import production


class OpenProductionJson(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="flux_openjson_"))
        self.path = self.root / "production.json"
        self.path.write_text("{}", encoding="utf-8")
        repo = JsonFileRepository(lambda collection, doc_id: self.path)
        self.exists = self._patch(production.project_utils, "project_exists", return_value=True)
        self.get_repo = self._patch(production, "get_repository", return_value=repo)
        self._patch(production, "get_project_production_path", return_value=self.path)
        self.startfile = self._patch(production.os, "startfile", create=True)
        app = FastAPI()
        app.include_router(production.router, prefix="/production")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _patch(self, target, name, **kwargs):
        patcher = mock.patch.object(target, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _post(self):
        return self.client.post("/production/DEMO/open-json")

    def test_opens_the_production_file(self) -> None:
        res = self._post()
        self.assertEqual((res.status_code, res.json()), (200, {"ok": True}))
        self.startfile.assert_called_once_with(str(self.path))

    def test_unknown_project_is_404(self) -> None:
        self.exists.return_value = False
        self.assertEqual(self._post().status_code, 404)
        self.startfile.assert_not_called()

    def test_missing_file_is_404(self) -> None:
        self.path.unlink()
        self.assertEqual(self._post().status_code, 404)
        self.startfile.assert_not_called()

    def test_non_file_backend_is_409_even_with_a_leftover_file(self) -> None:
        self.get_repo.return_value = object()
        res = self._post()
        self.assertEqual(res.status_code, 409)
        self.assertIn("base", res.json()["detail"])
        self.startfile.assert_not_called()

    def test_no_editor_associated_is_409(self) -> None:
        self.startfile.side_effect = OSError("no association")
        self.assertEqual(self._post().status_code, 409)


if __name__ == "__main__":
    unittest.main()
