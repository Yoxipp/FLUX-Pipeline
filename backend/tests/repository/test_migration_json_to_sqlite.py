# test_migration_json_to_sqlite.py - JSON -> SQLite one-shot migration (V5).
#
# Builds a fake workspace on disk (projects, users, config feeds/archives), runs
# the migration, and PROVES data-for-data equality JSON == SQLite (get by get,
# read_log by read_log) through the SAME (collection, doc_id) keys the stores use
# at runtime. Then re-migrates and checks idempotence (no duplicates, same state).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import core.json_manager as jm
from core.constants import (
    ARCHIVE_DIRNAME,
    JSON_ACTIVITY,
    JSON_ACTIVITY_READ,
    JSON_CHAT,
    JSON_LOCKS,
    JSON_MENTIONS,
    JSON_PRODUCTION,
    JSON_TOKENS,
    JSON_USER_SETTINGS,
)
from core.migrate_json_to_sqlite import migrate_to_sqlite
from core.doc_keys import LogicalKeyRepository, to_logical
from core.sqlite_repository import SqliteRepository


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        jm.invalidate_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)

        self.projects = root / "DOSSIER_PROJETS"
        self.users = root / "USER"
        self.config = root / "CONFIG"
        self.prefs = root / "config.json"
        self.db = root / "metadata.db"

        # ── fake JSON workspace ────────────────────────────────────────────────
        # project SHOW_A: tokens + locks (keyed by path) + production (keyed by name)
        self.proj_a = self.projects / "SHOW_A"
        self.proj_a.mkdir(parents=True)
        jm.write_json(self.proj_a / JSON_TOKENS, {"CLASS": {"CH": "chara"}, "NAME": {"HERO": "assets/HERO"}})
        jm.write_json(self.proj_a / JSON_LOCKS, {"locked": ["assets/HERO"]})
        jm.write_json(self.proj_a / JSON_PRODUCTION, {"seqs": {"SQ01": ["SH010"]}})

        # a second project with only tokens (proves per-project scan)
        self.proj_b = self.projects / "SHOW_B"
        self.proj_b.mkdir(parents=True)
        jm.write_json(self.proj_b / JSON_TOKENS, {"CLASS": {"PR": "props"}})

        # user ADAM: settings blob (keyed by name)
        (self.users / "ADAM" / "UserSettings").mkdir(parents=True)
        jm.write_json(self.users / "ADAM" / "UserSettings" / JSON_USER_SETTINGS,
                      {"favorites": ["SHOW_A"], "recents": []})

        # prefs (config, doc_id "prefs")
        jm.write_json(self.prefs, {"username": "ADAM", "workspace": str(root)})

        # config feeds: activity + chat + mentions (append-only JSONL logs)
        self.config.mkdir(parents=True)
        self.act = self.config / JSON_ACTIVITY
        self.chat = self.config / JSON_CHAT
        self.men = self.config / JSON_MENTIONS
        jm.append_jsonl(self.act, [{"id": "a1", "action": "publish"}, {"id": "a2", "action": "publish"}])
        jm.append_jsonl(self.chat, [{"id": "c1", "message": "hi"}])
        jm.append_jsonl(self.men, [{"id": "m1", "to_user": "ADAM"}])

        # read-status companion (document) + a cold archive (JSON array document)
        self.act_read = self.config / JSON_ACTIVITY_READ
        jm.write_json(self.act_read, {"read_ids": ["a1"]})
        (self.config / ARCHIVE_DIRNAME).mkdir(parents=True)
        self.archive = self.config / ARCHIVE_DIRNAME / "activite_202608.json"
        jm.write_json(self.archive, [{"id": "old1"}, {"id": "old2"}])

    def _db(self):
        # Read like the runtime does (V8 U2): store keys translated to logical keys.
        root = Path(self._tmp.name)
        return LogicalKeyRepository(
            SqliteRepository(self.db),
            key_fn=lambda c, d: to_logical(c, d, flux_root=root, projects_dir=self.projects),
        )

    def _migrate(self):
        return migrate_to_sqlite(
            self.db,
            projects_dir=self.projects,
            users_dir=self.users,
            config_dir=self.config,
            prefs_path=self.prefs,
        )

    # ── data-for-data equality ────────────────────────────────────────────────

    def test_documents_migrate_identically(self):
        self._migrate()
        db = self._db()
        # tokens/locks keyed by project PATH
        self.assertEqual(db.get("tokens", str(self.proj_a)),
                         {"CLASS": {"CH": "chara"}, "NAME": {"HERO": "assets/HERO"}})
        self.assertEqual(db.get("tokens", str(self.proj_b)), {"CLASS": {"PR": "props"}})
        self.assertEqual(db.get("locks", str(self.proj_a)), {"locked": ["assets/HERO"]})
        # production keyed by NAME
        self.assertEqual(db.get("production", "SHOW_A"), {"seqs": {"SQ01": ["SH010"]}})
        # user_settings keyed by NAME
        self.assertEqual(db.get("user_settings", "ADAM"), {"favorites": ["SHOW_A"], "recents": []})
        # config doc_id "prefs"
        self.assertEqual(db.get("config", "prefs"), {"username": "ADAM", "workspace": str(Path(self._tmp.name))})
        # read_state + feed_archive keyed by path
        self.assertEqual(db.get("read_state", str(self.act_read)), {"read_ids": ["a1"]})
        self.assertEqual(db.get("feed_archive", str(self.archive)), [{"id": "old1"}, {"id": "old2"}])

    def test_logs_migrate_identically(self):
        self._migrate()
        db = self._db()
        self.assertEqual([e["id"] for e in db.read_log("activity_log", str(self.act))], ["a1", "a2"])
        self.assertEqual([e["id"] for e in db.read_log("chat_log", str(self.chat))], ["c1"])
        self.assertEqual([e["id"] for e in db.read_log("mentions_log", str(self.men))], ["m1"])

    def test_report_counts(self):
        report = self._migrate()
        # tokens x2, locks, production, user_settings, config, read_state, feed_archive
        self.assertEqual(report.total_documents(), 8)
        self.assertEqual(report.documents["tokens"], 2)
        self.assertEqual(report.total_logs(), 3)

    def test_json_files_untouched(self):
        before = (self.proj_a / JSON_TOKENS).read_text(encoding="utf-8")
        self._migrate()
        after = (self.proj_a / JSON_TOKENS).read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertTrue(self.act.exists())  # feeds still present

    # ── idempotence ───────────────────────────────────────────────────────────

    def test_re_migration_is_idempotent(self):
        self._migrate()
        self._migrate()  # second run must not duplicate anything
        db = self._db()
        # documents unchanged
        self.assertEqual(db.get("tokens", str(self.proj_a)),
                         {"CLASS": {"CH": "chara"}, "NAME": {"HERO": "assets/HERO"}})
        # logs not doubled
        self.assertEqual([e["id"] for e in db.read_log("activity_log", str(self.act))], ["a1", "a2"])
        self.assertEqual([e["id"] for e in db.read_log("mentions_log", str(self.men))], ["m1"])

    def test_empty_workspace_migrates_nothing(self):
        empty = Path(self._tmp.name) / "empty"
        report = migrate_to_sqlite(
            empty / "meta.db",
            projects_dir=empty / "P",
            users_dir=empty / "U",
            config_dir=empty / "C",
            prefs_path=empty / "none.json",
        )
        self.assertEqual(report.total_documents(), 0)
        self.assertEqual(report.total_logs(), 0)


if __name__ == "__main__":
    unittest.main()
