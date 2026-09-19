# X4 (ADR 0017, V9-06): FLUX imports in Maya follow LAST, a vNNN import stays frozen.

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from features.importer import import_tracking as it


class ImportTracking(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)
        self.last = self.project / "assets/chara/DINGO/usd/DINGO_LAST.usda"
        self.frozen = self.project / "assets/chara/DINGO/usd/DINGO_v003/DINGO.usda"
        for f in (self.last, self.frozen):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("#usda 1.0\n", encoding="utf-8")

    def _item(self, rel: str, stamp: str, node="|DINGO", mode="import") -> dict:
        return {"node": node, "project": "P", "source": rel, "stamp": stamp, "mode": mode}

    def test_statuses(self) -> None:
        last_rel = "assets/chara/DINGO/usd/DINGO_LAST.usda"
        stamp = it.source_stamp(self.last)
        items = [self._item(last_rel, stamp, "|A"),
                 self._item(last_rel, "old", "|B"),
                 self._item("assets/chara/DINGO/usd/DINGO_v003/DINGO.usda", "old", "|C"),
                 self._item("assets/chara/GONE/usd/GONE_LAST.usda", "x", "|D"),
                 {"node": "|E", "project": "OTHER", "source": last_rel, "stamp": stamp}]
        plan = it.plan_updates(items, {"P": self.project})
        self.assertEqual([p["status"] for p in plan], ["current", "update", "frozen", "missing", "missing"])
        self.assertEqual(plan[1]["stamp"], stamp)

    def test_a_republish_changes_the_stamp(self) -> None:
        before = it.source_stamp(self.last)
        time.sleep(0.01)
        self.last.write_text("#usda 1.0\n# v004\n", encoding="utf-8")
        os.utime(self.last, None)
        self.assertNotEqual(it.source_stamp(self.last), before)
        self.assertEqual(it.source_stamp(self.project / "nope.usda"), "")

    def test_frozen_names(self) -> None:
        self.assertTrue(it.is_frozen("a/CHAR_GEO_X_null_v012/CHAR_GEO_X_null.usda"))
        self.assertTrue(it.is_frozen("a\\X_v003.abc"))
        self.assertFalse(it.is_frozen("a/CHAR_GEO_X_null_LAST.abc"))
        self.assertFalse(it.is_frozen("assets/chara/DINGO/usd/DINGO_LAST.usda"))

    def test_summary(self) -> None:
        self.assertEqual(it.summary([], 0, []), "Aucun import FLUX dans la scene")
        plan = [{"status": "updated"}, {"status": "current"}, {"status": "frozen"}]
        self.assertEqual(it.summary(plan, 1, []),
                         "Imports FLUX : 1 mis a jour, 1 deja a jour, 1 figes (vNNN)")
        self.assertNotIn("—", it.summary(plan, 0, ["DINGO"]))


class PipelineShelf(unittest.TestCase):
    def test_the_update_button_is_always_on_the_flux_shelf(self) -> None:
        from features.shelf_manager.shelf_core import build_flux_shelf_mel

        for ids in ([], ["flux_anim"], ["flux_anim", "adam_rig"]):
            mel = build_flux_shelf_mel(ids)
            self.assertEqual(mel.count("maya_update.update_imports()"), 1, ids)
            self.assertTrue(mel.rstrip().endswith("}"))

    def test_the_maya_side_module_is_importable_outside_maya(self) -> None:
        from dcc.maya import maya_update

        self.assertEqual(maya_update.TAG_ATTRS, ("flux_project", "flux_source", "flux_stamp", "flux_mode"))


if __name__ == "__main__":
    unittest.main()
