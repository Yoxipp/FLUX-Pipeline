# test_sqlite_guard_and_export.py - V8 U0: SQLite refused on shared workspaces,
# and the SQLite -> JSON export that brings its writes back to disk.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.json_manager as jm
import core.repository_factory as rf
from core import paths
from core.constants import JSON_ACTIVITY, JSON_PRODUCTION, JSON_TOKENS
from core.export_sqlite_to_json import _merge_log, export_to_json
from core.json_repository import JsonFileRepository
from core.sqlite_repository import SqliteRepository
from core.project_setup import setup_path


class SharedLocationReasonTests(unittest.TestCase):
    def test_local_path_is_safe(self):
        with mock.patch.dict("os.environ", {}, clear=False), \
             mock.patch("core.paths._is_remote_drive", return_value=False):
            self.assertIsNone(paths.shared_location_reason(r"D:\flux\CONFIG\metadata.db"))

    def test_none_is_safe(self):
        self.assertIsNone(paths.shared_location_reason(None))

    def test_onedrive_folder_name(self):
        reason = paths.shared_location_reason(
            r"C:\Users\x\OneDrive - Example School\Flux_Pipeline"
        )
        self.assertIn("synced folder", reason)

    def test_unc_path(self):
        self.assertIn("UNC", paths.shared_location_reason(r"\\nas\prods\metadata.db"))

    def test_onedrive_env_root(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict("os.environ", {"OneDrive": d}):
                self.assertIn("OneDrive", paths.shared_location_reason(Path(d) / "W"))


class FactoryGuardTests(unittest.TestCase):
    def tearDown(self) -> None:
        rf.reset_repository()

    def test_sqlite_refused_when_workspace_on_onedrive(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "metadata.db"
            with mock.patch("core.paths.get_metadata_backend", return_value="sqlite"), \
                 mock.patch("core.paths.get_sqlite_path", return_value=db), \
                 mock.patch("core.paths.get_flux_root",
                            return_value=Path(r"C:\Users\x\OneDrive\Flux")):
                rf.reset_repository()
                self.assertIsInstance(rf.get_repository(), JsonFileRepository)
            self.assertFalse(db.exists())  # the refused base is never created

    def test_sqlite_refused_when_base_on_share(self):
        with mock.patch("core.paths.get_metadata_backend", return_value="sqlite"), \
             mock.patch("core.paths.get_sqlite_path",
                        return_value=Path(r"\\nas\flux\metadata.db")), \
             mock.patch("core.paths.get_flux_root", return_value=None):
            rf.reset_repository()
            self.assertIsInstance(rf.get_repository(), JsonFileRepository)

    def test_sqlite_allowed_when_all_local(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("core.paths.get_metadata_backend", return_value="sqlite"), \
                 mock.patch("core.paths.get_sqlite_path", return_value=Path(d) / "m.db"), \
                 mock.patch("core.paths.get_flux_root", return_value=Path(d)):
                rf.reset_repository()
                self.assertIsInstance(rf.get_repository().inner, SqliteRepository)
                rf.reset_repository()


class MergeLogTests(unittest.TestCase):
    def test_union_by_id_sorted(self):
        disk = [{"id": "20260910_a", "m": 1}, {"id": "20260912_c", "m": 3}]
        base = [{"id": "20260910_a", "m": "base"}, {"id": "20260911_b", "m": 2}]
        merged, added = _merge_log(disk, base)
        self.assertEqual(added, 1)
        self.assertEqual([e["id"] for e in merged], ["20260910_a", "20260911_b", "20260912_c"])
        self.assertEqual(merged[0]["m"], 1)  # disk wins on a shared id


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        jm.invalidate_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.projects = root / "DOSSIER_PROJETS"
        self.users = root / "USER"
        self.config = root / "CONFIG"
        self.prefs = root / "config.json"
        self.project = self.projects / "PROJ"
        for p in (self.project, self.users, self.config):
            p.mkdir(parents=True)
        self.db = root / "metadata.db"
        base = SqliteRepository(self.db)
        base.set("tokens", str(self.project), {"NAME": {"HERO": "assets/HERO"}})
        base.set("production", "PROJ", {"shots": ["sh010"]})
        base.set("tokens", str(root / "GONE"), {"NAME": {}})
        base.set("config", "prefs", {"metadata_backend": "sqlite"})
        self.activity = self.config / JSON_ACTIVITY
        base.append_log("activity_log", str(self.activity),
                        [{"id": "20260912_base", "action": "publish"}])
        # a teammate wrote the disk feed and the tokens while the base was active
        jm.write_jsonl(self.activity, [{"id": "20260913_disk", "action": "chat"}])
        (self.project / JSON_TOKENS).write_text(json.dumps({"NAME": {}}), encoding="utf-8")
        self.root = root

    def _run(self, apply: bool):
        return export_to_json(self.db, projects_dir=self.projects, users_dir=self.users,
                              prefs_path=self.prefs, apply=apply)

    def test_dry_run_writes_nothing(self):
        report = self._run(apply=False)
        self.assertFalse(setup_path(self.project, JSON_PRODUCTION).exists())
        self.assertEqual(len(jm.read_jsonl(self.activity)), 1)
        self.assertIn(str(setup_path(self.project, JSON_PRODUCTION)), report.written)

    def test_apply_writes_merges_and_backs_up(self):
        report = self._run(apply=True)
        jm.invalidate_cache()
        tokens = json.loads(setup_path(self.project, JSON_TOKENS).read_text(encoding="utf-8"))
        self.assertEqual(tokens["NAME"]["HERO"], "assets/HERO")
        self.assertEqual(
            json.loads(setup_path(self.project, JSON_PRODUCTION).read_text(encoding="utf-8")),
            {"shots": ["sh010"]},
        )
        ids = [e["id"] for e in jm.read_jsonl(self.activity)]
        self.assertEqual(ids, ["20260912_base", "20260913_disk"])
        self.assertEqual(len(report.backed_up), 2)  # tokens + activity feed
        self.assertTrue(all(Path(p).exists() for p in report.backed_up))
        self.assertEqual(len(report.skipped_stale), 1)
        self.assertFalse((self.root / "GONE").exists())
        self.assertFalse(self.prefs.exists())  # config never exported

    def test_workspace_root_skips_foreign_targets(self):
        other = Path(self._tmp.name) / "OTHER_WORKSPACE"
        other.mkdir()
        report = export_to_json(self.db, projects_dir=self.projects, users_dir=self.users,
                                prefs_path=self.prefs, apply=True, workspace_root=other)
        self.assertEqual(report.written, [])
        self.assertGreater(len(report.skipped_foreign), 0)

    def test_second_apply_is_a_no_op(self):
        self._run(apply=True)
        jm.invalidate_cache()
        report = self._run(apply=True)
        self.assertEqual(report.written, [])
        self.assertEqual(report.backed_up, [])


if __name__ == "__main__":
    unittest.main()
