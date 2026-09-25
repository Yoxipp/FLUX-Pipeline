# Cleaning an asset / a project to the current FLUX layout (2026-09-25): only what
# is certain moves (to _backup_flux, restorable), the rest is a warning; never a break.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from features.folder_manager import asset_cleanup as ac
from features.folder_manager import tokens as tok
from features.publisher import last_pointer as lp
from features.publisher.publish_core import resolve_publish_path


def _touch(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


class AssetCleanup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["OGRE"] = "assets/chara/OGRE"
        tok.save_tokens(self.project, tokens)
        _touch(self.project / "project.json", json.dumps({"project_id": "old", "schema_version": 1, "usd": {}}))
        self.root = self.project / "assets/chara/OGRE"
        self.geo = resolve_publish_path(self.project, "CHAR_GEO_OGRE_null.abc")
        _touch(self.geo / "CHAR_GEO_OGRE_null_v001.abc")
        _touch(self.geo / "CHAR_GEO_OGRE_null_LAST.abc")
        # older per-format layout, superseded by the flat LAST above
        _touch(self.geo / "abc" / "CHAR_GEO_OGRE_null_LAST.abc")
        # older layout, only copy of the fbx
        _touch(self.geo / "fbx" / "CHAR_GEO_OGRE_null_LAST.fbx")
        # textures: COL (old name) next to BCOL (canonical)
        self.col = resolve_publish_path(self.project, "CHAR_SHADING_OGRE_COL.png")
        self.bcol = resolve_publish_path(self.project, "CHAR_SHADING_OGRE_BCOL.png")
        _touch(self.col / "CHAR_SHADING_OGRE_COL_LAST.png")
        _touch(self.bcol / "CHAR_SHADING_OGRE_BCOL_LAST.png")
        # a publish of the asset in an old hierarchy, superseded
        _touch(self.root / "old_textures" / "CHAR_SHADING_OGRE_BCOL_v001.png")
        # leftovers
        _touch(self.geo / (lp.TMP_PREFIX + "CHAR_GEO_OGRE_null_v002.abc"))
        (self.root / "rig" / "empty" / "deeper").mkdir(parents=True)
        # artist work files: FLUX does not know them, never moved (even with a FLUX name)
        _touch(self.root / "work" / "ogre_sculpt.ztl")
        _touch(self.root / "work" / "CHAR_GEO_OGRE_null.abc")

    def _items(self, scan):
        return {i["path"]: i for i in scan["items"]}

    def test_scan_sorts_certain_from_unsure(self) -> None:
        items = self._items(ac.scan_asset(self.project, "OGRE"))
        rel = lambda p: str(p.relative_to(self.project)).replace("\\\\", "/")   # noqa: E731
        self.assertTrue(items[rel(self.geo / "abc")]["safe"])
        fbx = items[rel(self.geo / "fbx")]
        self.assertFalse(fbx["safe"])
        self.assertIn("pas de version actuelle", fbx["reason"])
        self.assertIn("garde", fbx["warning"])
        self.assertTrue(items[rel(self.col)]["safe"])
        self.assertEqual(items[rel(self.col)]["kind"], "old_map_name")
        self.assertTrue(items["assets/chara/OGRE/old_textures"]["safe"])
        self.assertEqual(items["assets/chara/OGRE/old_textures"]["kind"], "wrong_place")
        self.assertTrue(any(i["kind"] == "temp" and i["safe"] for i in items.values()))
        self.assertIn("assets/chara/OGRE/rig", items)                       # outermost empty folder
        self.assertNotIn("assets/chara/OGRE/rig/empty", items)
        # current files and work files are never proposed
        self.assertFalse(any("CHAR_GEO_OGRE_null_LAST.abc" == Path(p).name and "/abc/" not in p for p in items))
        self.assertFalse(any("work" in p for p in items))

    def test_a_scene_that_names_a_path_keeps_it(self) -> None:
        _touch(self.project / "seq/SEQ001/SHOT010/light.hipnc",
               "texture = $FLUX/PROJ/assets/chara/OGRE/tex/col/CHAR_SHADING_OGRE_COL_LAST.png "
               + str(self.col).replace("/", "\\\\"))
        rel_col = str(self.col.relative_to(self.project)).replace("\\\\", "/")
        item = self._items(ac.scan_asset(self.project, "OGRE"))[rel_col]
        self.assertFalse(item["safe"])
        self.assertIn("light.hipnc", item["warning"])

    def test_apply_moves_only_safe_items_and_restore_puts_them_back(self) -> None:
        scan = ac.scan_asset(self.project, "OGRE")
        paths = [i["path"] for i in scan["items"]]
        res = ac.apply_cleanup(self.project, "OGRE", paths)
        self.assertTrue(res["backup"].startswith("_backup_flux/"))
        self.assertFalse((self.geo / "abc").exists())
        self.assertTrue((self.geo / "fbx" / "CHAR_GEO_OGRE_null_LAST.fbx").is_file())   # unsure: kept
        self.assertTrue(any("pas sur" in e for e in res["errors"]))
        self.assertFalse(self.col.exists())
        self.assertFalse((self.root / "rig").exists())
        self.assertTrue((self.root / "work" / "ogre_sculpt.ztl").is_file())
        self.assertTrue((self.geo / "CHAR_GEO_OGRE_null_LAST.abc").is_file())
        # nothing certain left
        self.assertFalse([i for i in ac.scan_asset(self.project, "OGRE")["items"] if i["safe"]])
        backups = ac.list_backups(self.project)
        self.assertEqual(len(backups), 1)
        out = ac.restore_cleanup(self.project, backups[0]["id"])
        self.assertGreater(out["restored"], 0)
        self.assertTrue((self.geo / "abc" / "CHAR_GEO_OGRE_null_LAST.abc").is_file())
        self.assertTrue((self.col / "CHAR_SHADING_OGRE_COL_LAST.png").is_file())

    def test_project_clone_leaves_out_what_is_certain_and_gets_its_own_id(self) -> None:
        res = ac.clone_project(self.project, "PROJ_CLEAN")
        clone = self.project.parent / "PROJ_CLEAN"
        self.assertEqual(res["project"], "PROJ_CLEAN")
        self.assertTrue((clone / "tokens.json").is_file() or any(clone.glob("*.json")))
        geo = clone / self.geo.relative_to(self.project)
        self.assertTrue((geo / "CHAR_GEO_OGRE_null_LAST.abc").is_file())
        self.assertFalse((geo / "abc").exists())
        self.assertTrue((geo / "fbx" / "CHAR_GEO_OGRE_null_LAST.fbx").is_file())
        self.assertTrue((clone / "assets/chara/OGRE/work/ogre_sculpt.ztl").is_file())
        self.assertNotEqual(json.loads((clone / "project.json").read_text())["project_id"], "old")
        # the original is untouched
        self.assertTrue((self.geo / "abc" / "CHAR_GEO_OGRE_null_LAST.abc").is_file())
        with self.assertRaises(ValueError):
            ac.clone_project(self.project, "PROJ_CLEAN")


if __name__ == "__main__":
    unittest.main()
