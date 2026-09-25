# test_path_containment.py — S5: browse/rename/move never leave the project folder.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import main
from routers import files, folder_manager


class PathContainmentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.projects = root / "DOSSIER_PROJETS"
        self.project = self.projects / "DEMO"
        (self.project / "assets").mkdir(parents=True)
        (self.project / "assets" / "a.txt").write_text("a")
        (root / "secret.txt").write_text("secret")
        get_project = lambda name: self.projects / name  # noqa: E731
        for target in (files, folder_manager):
            p = mock.patch.object(target, "get_project_path", side_effect=get_project)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(files, "get_projects_dir", return_value=self.projects)
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(main.app)

    def tearDown(self):
        self._tmp.cleanup()

    def test_browse_inside_project_works(self):
        r = self.client.get("/files/projects/DEMO/browse", params={"subpath": "assets"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([f["name"] for f in r.json()["files"]], ["a.txt"])

    def test_browse_subpath_traversal_is_refused(self):
        r = self.client.get("/files/projects/DEMO/browse", params={"subpath": "../.."})
        self.assertEqual(r.status_code, 403)

    def test_browse_project_name_traversal_is_refused(self):
        r = self.client.get("/files/projects/../browse")
        self.assertIn(r.status_code, (403, 404))
        r = self.client.get("/files/projects/%2E%2E/browse")
        self.assertIn(r.status_code, (403, 404))

    def test_copy_source_outside_project_is_refused(self):
        r = self.client.post("/folder/copy", json={
            "project": "DEMO", "subpath": "../..", "name": "secret.txt", "dst_subpath": "assets"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse((self.project / "assets" / "secret.txt").exists())

    def test_rename_source_outside_project_is_refused(self):
        r = self.client.patch("/folder/items", json={
            "project": "DEMO", "subpath": "../..", "name": "secret.txt", "new_subpath": "assets"})
        self.assertIn(r.status_code, (403, 422))
        self.assertTrue((Path(self._tmp.name) / "secret.txt").exists())


if __name__ == "__main__":
    unittest.main()
