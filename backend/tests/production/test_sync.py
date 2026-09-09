# test_sync.py — Production → Disk sync is create-only and never destructive.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.folder_manager.tokens import build_default_tokens, save_tokens
from features.production import production_store as store
from features.production.sync import sync_production_to_disk


def _project() -> Path:
    d = Path(tempfile.mkdtemp())
    save_tokens(d, build_default_tokens())
    return d


class ProductionSyncCreatesFolders(unittest.TestCase):
    def test_asset_task_subtask_created(self):
        proj = _project()
        data = store.default_schema()
        asset = store.add_asset(data, "CHAR", "HERO")
        task = store.add_task(asset, "RIG", type_tokens=["RIG"])
        store.add_known_subtask(task, "BODY")

        created = sync_production_to_disk(proj, data)

        # CHAR -> assets/chara ; NAME fallback -> assets/chara/HERO ; RIG -> rig
        asset_root = proj / "assets" / "chara" / "HERO"
        task_dir   = asset_root / "rig"
        sub_dir    = task_dir / "body"
        self.assertTrue(asset_root.is_dir())
        self.assertTrue(task_dir.is_dir())
        self.assertTrue(sub_dir.is_dir())
        self.assertGreaterEqual(created["assets"], 1)

    def test_null_subtask_is_not_materialized(self):
        proj = _project()
        data = store.default_schema()
        asset = store.add_asset(data, "PROPS", "SWORD")
        task = store.add_task(asset, "GEO", type_tokens=["GEO"])
        store.add_known_subtask(task, "null")   # placeholder, must be ignored

        sync_production_to_disk(proj, data)

        # GEO resolves to the same subfolder the publisher uses (TYPE map: GEO->model).
        task_dir = proj / "assets" / "props" / "SWORD" / "model"
        self.assertTrue(task_dir.is_dir())
        self.assertFalse((task_dir / "null").exists())

    def test_idempotent_second_run_creates_nothing_new(self):
        proj = _project()
        data = store.default_schema()
        asset = store.add_asset(data, "CHAR", "HERO")
        store.add_task(asset, "RIG", type_tokens=["RIG"])
        sync_production_to_disk(proj, data)

        created2 = sync_production_to_disk(proj, data)
        self.assertEqual(created2["assets"], 0)
        self.assertEqual(created2["tasks"], 0)


class ProductionSyncNeverDestroys(unittest.TestCase):
    def test_existing_files_are_preserved(self):
        proj = _project()
        data = store.default_schema()
        asset = store.add_asset(data, "CHAR", "HERO")
        store.add_task(asset, "RIG", type_tokens=["RIG"])

        # Pre-existing published file in the target task folder.
        task_dir = proj / "assets" / "chara" / "HERO" / "rig"
        task_dir.mkdir(parents=True)
        precious = task_dir / "CHAR_RIG_HERO_null_LAST.mb"
        precious.write_text("precious bytes")

        sync_production_to_disk(proj, data)

        # The sync only adds folders — the file is byte-for-byte untouched.
        self.assertTrue(precious.exists())
        self.assertEqual(precious.read_text(), "precious bytes")

    def test_rename_creates_new_leaves_old(self):
        # Renaming an asset in Production must never move/delete the old folder.
        proj = _project()
        data = store.default_schema()
        a1 = store.add_asset(data, "CHAR", "OLDNAME")
        store.add_task(a1, "RIG", type_tokens=["RIG"])
        sync_production_to_disk(proj, data)
        old_root = proj / "assets" / "chara" / "OLDNAME"
        (old_root / "rig").mkdir(parents=True, exist_ok=True)
        (old_root / "rig" / "keep.txt").write_text("keep")

        # Simulate a rename in the planning layer.
        a1["name"] = "NEWNAME"
        sync_production_to_disk(proj, data)

        self.assertTrue((proj / "assets" / "chara" / "NEWNAME").is_dir())  # new created
        self.assertTrue(old_root.is_dir())                                # old preserved
        self.assertEqual((old_root / "rig" / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
