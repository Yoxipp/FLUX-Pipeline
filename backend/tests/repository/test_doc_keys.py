# test_doc_keys.py - V8 U2: logical document keys + automatic key migration (ADR 0004).

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.json_manager as jm
from core import doc_keys as dk
from core import repository_factory as rf
from core.constants import JSON_ACTIVITY, JSON_PRODUCTION, JSON_TOKENS
from core.export_sqlite_to_json import export_to_json
from core.sqlite_repository import SqliteRepository

_PID = "a" * 32


def _workspace(root: Path, pid: str | None = _PID) -> tuple[Path, Path]:
    projects = root / "DOSSIER_PROJETS"
    project = projects / "PROJ"
    project.mkdir(parents=True)
    (root / "CONFIG").mkdir()
    if pid:
        (project / "project.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    return projects, project


def _rows(db: Path) -> set[tuple[str, str]]:
    conn = sqlite3.connect(db)
    try:
        docs = conn.execute("SELECT collection, doc_id FROM documents").fetchall()
        logs = conn.execute("SELECT DISTINCT collection, doc_id FROM logs").fetchall()
    finally:
        conn.close()
    return set(docs) | set(logs)


class ToLogicalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "FLUX"
        self.projects, self.project = _workspace(self.root)
        self.kw = {"flux_root": self.root, "projects_dir": self.projects}

    def test_project_collections_use_project_id(self):
        self.assertEqual(dk.to_logical("tokens", str(self.project), **self.kw), _PID)
        self.assertEqual(dk.to_logical("locks", str(self.project), **self.kw), _PID)
        self.assertEqual(dk.to_logical("production", "PROJ", **self.kw), _PID)

    def test_modif_log_is_project_relative(self):
        folder = self.project / "assets" / "chara" / "HERO"
        self.assertEqual(dk.to_logical("modif_log", str(folder), **self.kw), f"{_PID}/assets/chara/HERO")

    def test_workspace_files_are_ws_relative(self):
        path = self.root / "CONFIG" / JSON_ACTIVITY
        self.assertEqual(dk.to_logical("activity_log", str(path), **self.kw), f"ws:CONFIG/{JSON_ACTIVITY}")
        archive = self.root / "CONFIG" / "archive" / "activite_202609.json"
        self.assertEqual(dk.to_logical("feed_archive", str(archive), **self.kw), "ws:CONFIG/archive/activite_202609.json")

    def test_untranslatable_keys_are_kept(self):
        outside = Path(self._tmp.name) / "elsewhere" / "x.json"
        self.assertEqual(dk.to_logical("read_state", str(outside), **self.kw), str(outside))
        self.assertEqual(dk.to_logical("user_settings", "ADAM", **self.kw), "ADAM")
        self.assertEqual(dk.to_logical("config", "prefs", **self.kw), "prefs")
        (self.projects / "NOCFG").mkdir()
        self.assertEqual(dk.to_logical("tokens", str(self.projects / "NOCFG"), **self.kw), str(self.projects / "NOCFG"))
        self.assertEqual(dk.to_logical("production", "NOCFG", **self.kw), "NOCFG")

    def test_idempotent(self):
        for coll, doc in (("tokens", str(self.project)), ("production", "PROJ"),
                          ("modif_log", str(self.project / "shot")),
                          ("chat_log", str(self.root / "CONFIG" / "teamChat.json"))):
            once = dk.to_logical(coll, doc, **self.kw)
            self.assertEqual(dk.to_logical(coll, once, **self.kw), once, coll)

    def test_to_store_roundtrip(self):
        for coll, doc in (("tokens", str(self.project)), ("production", "PROJ"),
                          ("modif_log", str(self.project / "shot" / "SQ01")),
                          ("mentions_log", str(self.root / "CONFIG" / "chatMentions.json"))):
            key = dk.to_logical(coll, doc, **self.kw)
            self.assertNotEqual(key, doc)
            self.assertEqual(Path(dk.to_store(coll, key, **self.kw)), Path(doc), coll)

    def test_two_machines_same_keys(self):
        # Same synced project, different roots per machine -> identical logical keys.
        other_root = Path(self._tmp.name) / "Users" / "Milo" / "FLUX"
        other_projects, other_project = _workspace(other_root)
        kw2 = {"flux_root": other_root, "projects_dir": other_projects}
        self.assertEqual(dk.to_logical("tokens", str(self.project), **self.kw),
                         dk.to_logical("tokens", str(other_project), **kw2))
        self.assertEqual(dk.to_logical("activity_log", str(self.root / "CONFIG" / JSON_ACTIVITY), **self.kw),
                         dk.to_logical("activity_log", str(other_root / "CONFIG" / JSON_ACTIVITY), **kw2))


class RekeyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "FLUX"
        self.projects, self.project = _workspace(self.root)
        self.db = Path(self._tmp.name) / "metadata.db"
        self.key = lambda c, d: dk.to_logical(c, d, flux_root=self.root, projects_dir=self.projects)

    def test_moves_path_keys_and_is_idempotent(self):
        base = SqliteRepository(self.db)
        base.set("tokens", str(self.project), {"NAME": {}})
        base.set("user_settings", "ADAM", {"x": 1})
        base.append_log("activity_log", str(self.root / "CONFIG" / JSON_ACTIVITY), [{"id": "a1"}])
        report = base.rekey(self.key)
        self.assertEqual(len(report["moved"]), 2)
        self.assertEqual(_rows(self.db), {("tokens", _PID), ("user_settings", "ADAM"),
                                          ("activity_log", f"ws:CONFIG/{JSON_ACTIVITY}")})
        again = base.rekey(self.key)
        self.assertEqual(again, {"moved": [], "conflicts": []})

    def test_conflict_keeps_both_rows(self):
        base = SqliteRepository(self.db)
        base.set("tokens", _PID, {"NAME": {"NEW": "x"}})
        base.set("tokens", str(self.project), {"NAME": {"OLD": "y"}})
        report = base.rekey(self.key)
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(base.get("tokens", _PID), {"NAME": {"NEW": "x"}})
        self.assertEqual(base.get("tokens", str(self.project)), {"NAME": {"OLD": "y"}})


class FactoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "FLUX"
        self.db = Path(self._tmp.name) / "metadata.db"
        self.addCleanup(rf.reset_repository)

    def _patches(self):
        return (
            mock.patch("core.paths.get_metadata_backend", return_value="sqlite"),
            mock.patch("core.paths.get_sqlite_path", return_value=self.db),
            mock.patch("core.paths.get_flux_root", return_value=self.root),
            mock.patch("core.paths.shared_location_reason", return_value=None),
        )

    def test_store_writes_logical_key_and_build_migrates(self):
        projects, project = _workspace(self.root)
        SqliteRepository(self.db).set("production", "PROJ", {"old": True})  # legacy name key
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            rf.reset_repository()
            from features.folder_manager.tokens import load_tokens, save_tokens
            self.assertTrue(save_tokens(project, {"CLASS": {"CH": "chara"}}))
            self.assertEqual(load_tokens(project)["CLASS"]["CH"], "chara")
            self.assertEqual(rf.get_repository().get("production", "PROJ"), {"old": True})
        self.assertEqual(_rows(self.db), {("tokens", _PID), ("production", _PID)})

    def test_project_json_creation_moves_existing_keys(self):
        projects, project = _workspace(self.root, pid=None)
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4:
            rf.reset_repository()
            repo = rf.get_repository()
            repo.set("locks", str(project), {"locked": ["assets/HERO"]})
            self.assertIn(("locks", str(project)), _rows(self.db))
            from features.folder_manager.project_config import ensure_project_config
            config, _ = ensure_project_config(project)
            self.assertEqual(_rows(self.db), {("locks", config["project_id"])})
            self.assertEqual(repo.get("locks", str(project)), {"locked": ["assets/HERO"]})

    def test_json_backend_unchanged(self):
        projects, project = _workspace(self.root)
        with mock.patch("core.paths.get_metadata_backend", return_value="json"):
            rf.reset_repository()
            self.assertNotIsInstance(rf.get_repository(), dk.LogicalKeyRepository)


class ExportLogicalKeysTests(unittest.TestCase):
    def test_export_resolves_logical_keys_to_this_machine(self):
        with tempfile.TemporaryDirectory() as d:
            jm.invalidate_cache()
            root = Path(d) / "FLUX"
            projects, project = _workspace(root)
            (root / "USER").mkdir()
            db = Path(d) / "metadata.db"
            base = SqliteRepository(db)
            base.set("tokens", _PID, {"NAME": {"HERO": "assets/HERO"}})
            base.set("production", _PID, {"shots": ["sh010"]})
            base.append_log("activity_log", f"ws:CONFIG/{JSON_ACTIVITY}", [{"id": "a1"}])
            export_to_json(db, projects_dir=projects, users_dir=root / "USER",
                           prefs_path=root / "config.json", apply=True)
            self.assertEqual(json.loads((project / JSON_TOKENS).read_text(encoding="utf-8")),
                             {"NAME": {"HERO": "assets/HERO"}})
            self.assertTrue((project / JSON_PRODUCTION).is_file())
            self.assertEqual([e["id"] for e in jm.read_jsonl(root / "CONFIG" / JSON_ACTIVITY)], ["a1"])


if __name__ == "__main__":
    unittest.main()
