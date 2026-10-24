# test_work_profiles.py - project work profiles in project.json "ui" (ADR 0042).

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import main
from features.folder_manager import project_config as pc
from core.project_setup import setup_path


class SanitizeWorkProfilesTests(unittest.TestCase):
    def test_keeps_well_formed_entries_only(self):
        clean = pc.sanitize_work_profiles([
            {"id": "anim", "name": "Animation", "prefs": {"startPage": "/production", "launcher": "compact", "x": [1]}},
            {"id": "anim", "name": "Duplicate"},
            {"id": "", "name": "No id"},
            "garbage",
            {"id": "lgt", "name": "  Lighting  ", "prefs": "bad"},
        ])
        self.assertEqual(clean, [
            {"id": "anim", "name": "Animation", "prefs": {"startPage": "/production", "launcher": "compact"}},
            {"id": "lgt", "name": "Lighting", "prefs": {}},
        ])

    def test_not_a_list_and_limits(self):
        self.assertEqual(pc.sanitize_work_profiles({"id": "a"}), [])
        many = [{"id": str(i), "name": "n" * 80} for i in range(50)]
        clean = pc.sanitize_work_profiles(many)
        self.assertEqual(len(clean), pc.MAX_WORK_PROFILES)
        self.assertEqual(len(clean[0]["name"]), pc.MAX_PROFILE_NAME)


class WorkProfilesStorageTests(unittest.TestCase):
    def test_write_keeps_other_keys_and_stays_valid(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d) / "PROJ"
            project.mkdir()
            config, _ = pc.ensure_project_config(project)
            pc.write_work_profiles(project, [{"id": "a", "name": "Anim", "prefs": {"launcher": "full"}}])
            data = json.loads(setup_path(project, "project.json").read_text(encoding="utf-8"))
            self.assertEqual(data["project_id"], config["project_id"])
            self.assertEqual(data["ui"]["work_profiles"][0]["prefs"], {"launcher": "full"})
            self.assertEqual(pc.validate_project_config(data), [])
            self.assertEqual(pc.read_work_profiles(project)[0]["name"], "Anim")

    def test_read_without_config_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(pc.read_work_profiles(Path(d)), [])


class WorkProfilesRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        # Role gates are tested in tests/roles; here the active user may edit the project.
        p = mock.patch("features.roles.project_roles.require", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def test_round_trip_and_404(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "PROJ").mkdir()
            with mock.patch("routers.folder_manager.get_project_path", side_effect=lambda n: Path(d) / n), \
                    mock.patch("routers.folder_manager.get_projects_dir", return_value=Path(d)):
                self.assertEqual(self.client.get("/folder/projects/PROJ/work-profiles").json(), {"profiles": []})
                r = self.client.put("/folder/projects/PROJ/work-profiles",
                                    json={"profiles": [{"id": "p", "name": "Prod", "prefs": {"startPage": "/production"}}]})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(self.client.get("/folder/projects/PROJ/work-profiles").json()["profiles"][0]["id"], "p")
                self.assertEqual(self.client.get("/folder/projects/NOPE/work-profiles").status_code, 404)


if __name__ == "__main__":
    unittest.main()
