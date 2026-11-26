# test_stale_save.py - a window holding a stale Production cannot overwrite a task status
# set meanwhile (Discord button): optimistic concurrency, JSON and SQLite backends.

from __future__ import annotations

import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from core.json_repository import JsonFileRepository
from core.sqlite_repository import SqliteRepository
from features.notify import dm_actions
from features.production import production_store as store
from routers import production as router

PROJECT = "PROJ"


def _production() -> dict:
    return {"sequences": [{"id": "q_1", "name": "SQ010"}],
            "shots": [{"id": "s_1", "seq_id": "q_1", "name": "SH010",
                       "task_details": {"ANIM": {"assignee": "LEA", "status": "WFA"}}}],
            "assets": []}


def _status(doc: dict) -> str:
    return doc["shots"][0]["task_details"]["ANIM"]["status"]


class _StaleSave:
    """Shared tests; subclasses give the repository."""

    def make_repository(self, root: Path):
        raise NotImplementedError

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        repo = self.make_repository(Path(tmp.name))
        for patch in (
            mock.patch.object(store, "get_repository", return_value=repo),
            mock.patch.object(router, "_ensure_project"),
            mock.patch.object(router, "get_project_path", return_value=Path(tmp.name)),
            mock.patch.object(router, "sync_production_to_disk", return_value={}),
            mock.patch.object(router, "_refresh_changed_shot_stages", return_value=[]),
            mock.patch("features.notify.hooks.on_production"),
            mock.patch("features.roles.project_roles.can", return_value=True),
            mock.patch("features.roles.project_roles.role_of", return_value="artist"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.assertTrue(store.save_production(PROJECT, _production()))

    def put(self, doc: dict, base: str | None) -> dict:
        payload = router.ProductionPayload(production=copy.deepcopy(doc), base_version=base)
        return asyncio.run(router.put_production(PROJECT, payload))

    def load_view(self) -> tuple[dict, str]:
        doc = copy.deepcopy(store.load_production(PROJECT))
        return doc, store.version_of(doc)

    def test_stale_view_cannot_overwrite_a_discord_status(self):
        view, base = self.load_view()
        dm_actions._task(PROJECT, "LEA", "ok", "s_1", "ANIM", "")
        view["shots"][0]["notes"] = "edit from the stale window"
        with self.assertRaises(HTTPException) as ctx:
            self.put(view, base)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(_status(ctx.exception.detail["production"]), "APPROVED")
        self.assertEqual(_status(store.load_production(PROJECT)), "APPROVED")
        self.assertNotIn("notes", store.load_production(PROJECT)["shots"][0])

    def test_returned_version_allows_the_next_save(self):
        view, base = self.load_view()
        view["shots"][0]["notes"] = "one"
        base = self.put(view, base)["production_version"]
        view["shots"][0]["notes"] = "two"
        base = self.put(view, base)["production_version"]
        self.assertEqual(base, self.load_view()[1])
        self.assertEqual(store.load_production(PROJECT)["shots"][0]["notes"], "two")

    def test_identical_rewrite_is_not_a_conflict(self):
        view, base = self.load_view()
        store.save_production(PROJECT, copy.deepcopy(view))
        self.assertTrue(self.put(view, base)["success"])

    def test_reload_after_409_saves(self):
        view, base = self.load_view()
        dm_actions._task(PROJECT, "LEA", "no", "s_1", "ANIM", "")
        with self.assertRaises(HTTPException):
            self.put(view, base)
        view, base = self.load_view()
        self.assertTrue(self.put(view, base)["success"])
        self.assertEqual(_status(store.load_production(PROJECT)), "RTK")

    def test_get_keeps_a_status_set_during_the_disk_scan(self):
        def scan(*_args):
            dm_actions._task(PROJECT, "LEA", "ok", "s_1", "ANIM", "")
            return []

        def reconcile(production, *_args):       # reconcile adds an entity: GET must persist
            if not production["assets"]:
                production["assets"].append({"id": "a_1", "class": "CHAR", "name": "BOB", "tasks": []})
            return production, {}, []

        with mock.patch.object(router, "get_all_events", return_value=[]), \
             mock.patch.object(router, "scan_project_assets", side_effect=scan), \
             mock.patch.object(router, "scan_project_shots", return_value=[]), \
             mock.patch.object(router, "reconcile", side_effect=reconcile), \
             mock.patch.object(router.prod_archive, "prune_absent_auto"):
            result = asyncio.run(router._compute_production(PROJECT))
        stored, version = self.load_view()
        self.assertEqual(_status(stored), "APPROVED")
        self.assertEqual(len(stored["assets"]), 1)
        self.assertEqual(result["production_version"], version)


class JsonStaleSave(_StaleSave, unittest.TestCase):
    def make_repository(self, root: Path):
        return JsonFileRepository(lambda collection, doc_id: root / f"{collection}_{doc_id}.json")


class SqliteStaleSave(_StaleSave, unittest.TestCase):
    def make_repository(self, root: Path):
        return SqliteRepository(root / "flux.db")


if __name__ == "__main__":
    unittest.main()
