# test_sqlite_repository.py — the local SQLite MetadataRepository backend (V5).
#
# Runs the shared backend-agnostic conformance suite against SqliteRepository, so
# it is proven observably identical to the JSON backend through the surface, plus
# a few SQLite-specific proofs: no file-per-doc (one base file), WAL enabled, and
# a real transaction rolls back on error.

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.sqlite_repository import SqliteRepository
from tests.repository._contract import RepositoryContractMixin


class SqliteRepositoryContractTests(RepositoryContractMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._db = Path(self._dir.name) / "metadata.db"

    def make_repo(self) -> SqliteRepository:
        return SqliteRepository(self._db)


class SqliteRepositorySpecificTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._db = Path(self._dir.name) / "metadata.db"

    def test_one_base_file_not_a_file_per_document(self):
        repo = SqliteRepository(self._db)
        repo.set("tokens", "C:/proj/A", {"CLASS": {}})
        repo.set("tokens", "C:/proj/B", {"CLASS": {}})
        repo.set("production", "SHOW", {"seqs": []})
        # Everything lives in the single base; no companion JSON files appear.
        self.assertTrue(self._db.exists())
        self.assertEqual(list(Path(self._dir.name).glob("*.json")), [])

    def test_wal_mode_enabled(self):
        SqliteRepository(self._db)
        conn = sqlite3.connect(self._db)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(str(mode).lower(), "wal")

    def test_log_transaction_rolls_back_on_error(self):
        repo = SqliteRepository(self._db)
        repo.append_log("events", "feed", [{"id": "e1"}])
        with self.assertRaises(RuntimeError):
            with repo.log_transaction("events", "feed"):
                repo.append_log("events", "feed", [{"id": "e2"}])
                raise RuntimeError("boom")  # abort the scope
        # The aborted append must not have been committed.
        self.assertEqual([e["id"] for e in repo.read_log("events", "feed")], ["e1"])

    def test_reopen_same_base_sees_prior_writes(self):
        SqliteRepository(self._db).set("config", "prefs", {"username": "ADAM"})
        # A fresh instance on the same file reads what the first one wrote.
        self.assertEqual(
            SqliteRepository(self._db).get("config", "prefs"), {"username": "ADAM"}
        )

    def test_update_on_list_document_behaves_like_json_backend(self):
        # update() is a dict-merge; on a list doc it raises AttributeError, exactly
        # as the JSON backend does (identical code path). Guards against drift.
        repo = SqliteRepository(self._db)
        repo.set("logs", "a", [1, 2, 3])
        with self.assertRaises(AttributeError):
            repo.update("logs", "a", {"x": 1})


if __name__ == "__main__":
    unittest.main()
