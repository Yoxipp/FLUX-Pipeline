# test_repository_factory.py - the factory picks the backend from config (V5).
#
# Proves the ONE point that flips local -> server behaves: JSON by default, SQLite
# when config asks, and - the real guarantee - a store (tokens) works identically
# whichever backend is active (same test body, two backends).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.repository_factory as rf
from core.json_repository import JsonFileRepository
from core.sqlite_repository import SqliteRepository


class FactorySelectionTests(unittest.TestCase):
    def tearDown(self) -> None:
        rf.reset_repository()  # never leak a patched backend to other test modules

    def test_defaults_to_json_when_backend_json(self):
        with mock.patch("core.paths.get_metadata_backend", return_value="json"):
            rf.reset_repository()
            self.assertIsInstance(rf.get_repository(), JsonFileRepository)

    def test_defaults_to_json_when_key_absent(self):
        # Real get_metadata_backend over an empty config.json -> "json".
        with mock.patch("core.paths._read_config_json", return_value={}):
            rf.reset_repository()
            self.assertIsInstance(rf.get_repository(), JsonFileRepository)

    def test_selects_sqlite_when_configured(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "metadata.db"
            with mock.patch("core.paths.get_metadata_backend", return_value="sqlite"), \
                 mock.patch("core.paths.get_sqlite_path", return_value=db), \
                 mock.patch("core.paths.get_flux_root", return_value=None):
                rf.reset_repository()
                self.assertIsInstance(rf.get_repository().inner, SqliteRepository)

    def test_repository_is_cached(self):
        with mock.patch("core.paths.get_metadata_backend", return_value="json"):
            rf.reset_repository()
            self.assertIs(rf.get_repository(), rf.get_repository())

    def test_reset_rebuilds_from_config(self):
        with mock.patch("core.paths.get_metadata_backend", return_value="json"):
            rf.reset_repository()
            first = rf.get_repository()
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "metadata.db"
            with mock.patch("core.paths.get_metadata_backend", return_value="sqlite"), \
                 mock.patch("core.paths.get_sqlite_path", return_value=db), \
                 mock.patch("core.paths.get_flux_root", return_value=None):
                rf.reset_repository()
                second = rf.get_repository()
        self.assertIsInstance(first, JsonFileRepository)
        self.assertIsInstance(second.inner, SqliteRepository)


class TokensStoreOnBothBackendsTests(unittest.TestCase):
    """The same store test body, run against JSON and SQLite: a store must not
    care which backend the factory built."""

    def tearDown(self) -> None:
        rf.reset_repository()

    def _tokens_roundtrip(self) -> None:
        from features.folder_manager import tokens as tk
        with tempfile.TemporaryDirectory() as project_dir:
            project = Path(project_dir)
            data = tk.build_default_tokens()
            data["NAME"]["HERO"] = "assets/chara/HERO"
            self.assertTrue(tk.save_tokens(project, data))
            loaded = tk.load_tokens(project)
            self.assertEqual(loaded["NAME"]["HERO"], "assets/chara/HERO")
            self.assertIn("CLASS", loaded)  # defaults still merged in
            # a fresh load reads the persisted value back (not an in-memory echo)
            self.assertTrue(tk.add_token(project, "NAME", "PROP_A", "assets/props/A"))
            self.assertEqual(tk.load_tokens(project)["NAME"]["PROP_A"], "assets/props/A")

    def test_tokens_store_on_json_backend(self):
        with mock.patch("core.paths.get_metadata_backend", return_value="json"):
            rf.reset_repository()
            self._tokens_roundtrip()

    def test_tokens_store_on_sqlite_backend(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "metadata.db"
            with mock.patch("core.paths.get_metadata_backend", return_value="sqlite"), \
                 mock.patch("core.paths.get_sqlite_path", return_value=db), \
                 mock.patch("core.paths.get_flux_root", return_value=None):
                rf.reset_repository()
                self._tokens_roundtrip()


if __name__ == "__main__":
    unittest.main()
