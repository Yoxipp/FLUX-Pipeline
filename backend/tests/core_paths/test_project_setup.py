# tests/core_paths/test_project_setup.py — the per-project _flux_setup/ folder:
# path fallback, migration of legacy root files, lock + Folder Manager filter.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import project_setup as ps
from core.constants import JSON_CHAT, JSON_PRODUCTION, JSON_PROJECT, JSON_TOKENS, SETUP_DIR


class SetupPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_new_project_goes_to_setup_dir(self) -> None:
        self.assertEqual(ps.setup_path(self.project, JSON_TOKENS), self.project / SETUP_DIR / JSON_TOKENS)

    def test_legacy_root_file_is_used_until_migrated(self) -> None:
        (self.project / JSON_TOKENS).write_text("{}", encoding="utf-8")
        self.assertEqual(ps.setup_path(self.project, JSON_TOKENS), self.project / JSON_TOKENS)

    def test_setup_dir_wins_over_root(self) -> None:
        (self.project / JSON_TOKENS).write_text("{}", encoding="utf-8")
        (self.project / SETUP_DIR).mkdir()
        (self.project / SETUP_DIR / JSON_TOKENS).write_text("{}", encoding="utf-8")
        self.assertEqual(ps.setup_path(self.project, JSON_TOKENS), self.project / SETUP_DIR / JSON_TOKENS)

    def test_migration_moves_files_and_media_once(self) -> None:
        (self.project / JSON_PROJECT).write_text(json.dumps({"project_id": "abc"}), encoding="utf-8")
        (self.project / JSON_CHAT).write_text("[]", encoding="utf-8")
        (self.project / f"{JSON_CHAT}.lock").write_text("", encoding="utf-8")
        thumbs = self.project / "_production" / "thumbnails" / "id1"
        thumbs.mkdir(parents=True)
        (thumbs / "v001.png").write_bytes(b"x")
        (self.project / "assets").mkdir()

        moved = ps.migrate_project_setup(self.project)

        self.assertEqual(set(moved), {JSON_PROJECT, JSON_CHAT, "_production"})
        self.assertFalse((self.project / JSON_PROJECT).exists())
        self.assertFalse((self.project / f"{JSON_CHAT}.lock").exists())
        self.assertTrue((self.project / SETUP_DIR / "_production/thumbnails/id1/v001.png").is_file())
        self.assertTrue((self.project / "assets").is_dir())
        self.assertEqual(ps.migrate_project_setup(self.project), [])   # idempotent
        # The stored "_production/..." rel path still resolves.
        self.assertEqual(ps.resolve_project_rel(self.project, "_production/thumbnails/id1"),
                         self.project / SETUP_DIR / "_production" / "thumbnails" / "id1")
        self.assertEqual(ps.resolve_project_rel(self.project, "assets/HERO"), self.project / "assets" / "HERO")

    def test_migration_never_overwrites(self) -> None:
        (self.project / JSON_PRODUCTION).write_text('{"old": 1}', encoding="utf-8")
        (self.project / SETUP_DIR).mkdir()
        (self.project / SETUP_DIR / JSON_PRODUCTION).write_text('{"new": 1}', encoding="utf-8")
        self.assertEqual(ps.migrate_project_setup(self.project), [])
        self.assertEqual((self.project / JSON_PRODUCTION).read_text(encoding="utf-8"), '{"old": 1}')
        self.assertEqual((self.project / SETUP_DIR / JSON_PRODUCTION).read_text(encoding="utf-8"), '{"new": 1}')

    def test_is_project_root_both_layouts(self) -> None:
        self.assertFalse(ps.is_project_root(self.project))
        (self.project / SETUP_DIR).mkdir()
        (self.project / SETUP_DIR / JSON_TOKENS).write_text("{}", encoding="utf-8")
        self.assertTrue(ps.is_project_root(self.project))

    def test_is_setup_rel(self) -> None:
        for rel in (SETUP_DIR, f"{SETUP_DIR}/tokens.json", "_production/thumbnails", "teamChat.json.lock", "tokens.json"):
            self.assertTrue(ps.is_setup_rel(rel), rel)
        for rel in ("", "assets", "shot/SEQ010", "notes.json.lock"):
            self.assertFalse(ps.is_setup_rel(rel), rel)


class SetupLockAndBrowseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        (self.project / SETUP_DIR).mkdir(parents=True)
        (self.project / SETUP_DIR / JSON_TOKENS).write_text("{}", encoding="utf-8")
        (self.project / "assets").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_setup_folder_is_always_locked(self) -> None:
        from features.folder_manager import locks

        with mock.patch.object(locks, "get_repository") as repo:
            repo.return_value.get.return_value = {"locked": ["assets"]}
            self.assertIn(SETUP_DIR, locks.with_setup(locks.load_locks(self.project)))
            self.assertTrue(locks.is_locked(self.project, f"{SETUP_DIR}/tokens.json"))
            self.assertTrue(locks.is_locked(self.project, "assets"))
            self.assertFalse(locks.is_locked(self.project, "shot"))
            locks.set_lock(self.project, SETUP_DIR, False)        # refused silently
            written = repo.return_value.set.call_args[0][2]
            self.assertEqual(written, {"locked": ["assets"]})

    def test_browse_filter(self) -> None:
        from routers.files import _filter_setup

        root = self.project.resolve()
        folders, files = _filter_setup(root, root, [SETUP_DIR, "assets"], [], setup=False)
        self.assertEqual(folders, ["assets"])
        folders, _ = _filter_setup(root, root, [SETUP_DIR, "assets"], [], setup=True)
        self.assertEqual(folders, [SETUP_DIR, "assets"])
        _, files = _filter_setup(root, root / SETUP_DIR, [], [], setup=True)
        self.assertEqual([f.name for f in files], [JSON_TOKENS])


if __name__ == "__main__":
    unittest.main()
