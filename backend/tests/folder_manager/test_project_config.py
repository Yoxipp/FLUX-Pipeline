# test_project_config.py - V8 U1: <project>/project.json auto (ADR 0006, 0011).

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import main
from features.folder_manager import project_config as pc
from features.folder_manager.project_init import create_project
from core.project_setup import setup_path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class EnsureProjectConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        self.path = self.project / "project.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_with_defaults_and_houdini_units(self):
        config, warnings = pc.ensure_project_config(self.project)
        self.assertEqual(warnings, [])
        self.assertTrue((self.project / "_flux_setup" / "project.json").is_file())   # new layout (ADR 0054)
        self.assertEqual(config["usd"], {"meters_per_unit": 1.0, "up_axis": "Y"})
        self.assertEqual(config["schema_version"], pc.SCHEMA_VERSION)
        self.assertTrue(config["project_id"])
        self.assertEqual(pc.validate_project_config(config), [])

    def test_idempotent_keeps_project_id(self):
        first, _ = pc.ensure_project_config(self.project)
        path = pc.project_config_path(self.project)
        mtime = path.stat().st_mtime_ns
        second, _ = pc.ensure_project_config(self.project)
        self.assertEqual(first["project_id"], second["project_id"])
        self.assertEqual(path.stat().st_mtime_ns, mtime)  # no rewrite

    def test_heals_missing_keys_keeps_values(self):
        self.path.write_text(json.dumps({"project_id": "abc", "fps": 25, "usd": {"up_axis": "Z"}}), encoding="utf-8")
        config, warnings = pc.ensure_project_config(self.project)
        self.assertEqual(warnings, [])
        self.assertEqual(config["project_id"], "abc")
        self.assertEqual(config["fps"], 25)
        self.assertEqual(config["usd"], {"meters_per_unit": 1.0, "up_axis": "Z"})
        self.assertEqual(_read(self.path)["resolution"], [1920, 1080])

    def test_exclusive_create_never_overwrites(self):
        self.path.write_text(json.dumps({"project_id": "other"}), encoding="utf-8")
        self.assertFalse(pc._create_exclusive(self.path, pc.default_project_config()))
        self.assertEqual(_read(self.path)["project_id"], "other")

    def test_corrupt_file_is_kept_aside(self):
        self.path.write_text("{not json", encoding="utf-8")
        config, warnings = pc.ensure_project_config(self.project)
        self.assertTrue(config["project_id"])
        self.assertTrue(any("illisible" in w for w in warnings))
        self.assertEqual(len(list(self.project.glob("project.corrupt-*.json"))), 1)

    def test_conflict_copy_oldest_project_id_wins(self):
        self.path.write_text(json.dumps({"project_id": "new", "created_at": "2026-09-16T10:00:00+00:00"}), encoding="utf-8")
        (self.project / "project-PC-MILO.json").write_text(
            json.dumps({"project_id": "old", "created_at": "2026-09-15T10:00:00+00:00"}), encoding="utf-8")
        config, warnings = pc.ensure_project_config(self.project)
        self.assertEqual(config["project_id"], "old")
        self.assertEqual(_read(self.path)["project_id"], "old")
        self.assertTrue(any("conflit" in w for w in warnings))
        # Conflict copy is never deleted by FLUX.
        self.assertTrue((self.project / "project-PC-MILO.json").is_file())

    def test_invalid_values_are_reported_not_fixed(self):
        self.path.write_text(json.dumps({"project_id": "abc", "usd": {"meters_per_unit": 1.0, "up_axis": "X"}}), encoding="utf-8")
        config, warnings = pc.ensure_project_config(self.project)
        self.assertEqual(config["usd"]["up_axis"], "X")
        self.assertTrue(any("invalide" in w for w in warnings))


class DirectProjectDirTests(unittest.TestCase):
    def test_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "DOSSIER_PROJETS"
            (root / "PROJ").mkdir(parents=True)
            self.assertTrue(pc.is_direct_project_dir(root / "PROJ", root))
            self.assertFalse(pc.is_direct_project_dir(root / "..", root))
            self.assertFalse(pc.is_direct_project_dir(root / "MISSING", root))


class CreateProjectWritesConfigTests(unittest.TestCase):
    def test_create_project_writes_project_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = create_project("demo", projects_root=Path(d))
            self.assertTrue(setup_path(path, "project.json").is_file())
            self.assertEqual(pc.validate_project_config(_read(setup_path(path, "project.json"))), [])


class ProjectConfigRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_config_route_creates_on_first_open(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "PROJ").mkdir()
            with mock.patch("routers.folder_manager.get_project_path", side_effect=lambda n: Path(d) / n), \
                    mock.patch("routers.folder_manager.get_projects_dir", return_value=Path(d)):
                r = self.client.get("/folder/projects/PROJ/config")
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.json()["config"]["project_id"])
                self.assertTrue(setup_path(Path(d) / "PROJ", "project.json").is_file())

    def test_config_route_404(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("routers.folder_manager.get_project_path", side_effect=lambda n: Path(d) / n), \
                    mock.patch("routers.folder_manager.get_projects_dir", return_value=Path(d)):
                r = self.client.get("/folder/projects/NOPE/config")
                self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
