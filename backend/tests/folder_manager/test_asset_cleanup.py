# Putting an asset / a project back on the current FLUX layout (ADR 0033, 2026-09-25):
# files go back to their FLUX place, identical duplicates are dropped, anything unsure
# is a warning; a journal undoes it. Never a break.

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
        _touch(self.geo / "CHAR_GEO_OGRE_null_v002.abc", "v2")
        _touch(self.geo / "CHAR_GEO_OGRE_null_LAST.abc", "v2")
        # older per-format layout: its v001 is missing from the flat folder (goes back),
        # its LAST is the same as the current one (duplicate)
        _touch(self.geo / "abc" / "CHAR_GEO_OGRE_null_v001.abc", "v1")
        _touch(self.geo / "abc" / "CHAR_GEO_OGRE_null_LAST.abc", "v2")
        # older nested layout: <base>_<FMT>_V003/<inner> -> <base>_v003.fbx
        _touch(self.geo / "FBX" / "CHAR_GEO_OGRE_null_FBX_V003" / "CHAR_GEO_OGRE_null.fbx", "fbx3")
        # a different old LAST where a current one exists: conflict, kept
        _touch(self.geo / "versions" / "CHAR_GEO_OGRE_null_LAST.abc", "something else")
        # a publish in an old hierarchy
        _touch(self.root / "old_textures" / "CHAR_SHADING_OGRE_BCOL_v003.png", "b3")
        self.bcol = resolve_publish_path(self.project, "CHAR_SHADING_OGRE_BCOL.png")
        _touch(self.bcol / "CHAR_SHADING_OGRE_BCOL_LAST.png", "b2")
        # older map name next to the canonical one
        self.col = resolve_publish_path(self.project, "CHAR_SHADING_OGRE_COL.png")
        _touch(self.col / "CHAR_SHADING_OGRE_COL_v001.png", "c1")
        _touch(self.col / "CHAR_SHADING_OGRE_COL_LAST.png", "b2")                # same as BCOL LAST
        # leftovers
        _touch(self.geo / (lp.TMP_PREFIX + "CHAR_GEO_OGRE_null_v003.abc"))
        (self.root / "rig" / "empty").mkdir(parents=True)
        # work files: never moved, even with a FLUX name
        _touch(self.root / "work" / "ogre_sculpt.ztl")
        _touch(self.root / "work" / "CHAR_GEO_OGRE_null.abc")

    def _by(self, scan, action=None):
        return [i for i in scan["items"] if action is None or i["action"] == action]

    def test_scan_proposes_the_right_places(self) -> None:
        scan = ac.scan_asset(self.project, "OGRE")
        moves = {(i["path"], i["target"]): i for i in self._by(scan, "move")}
        geo = self.geo.relative_to(self.project).as_posix()
        self.assertIn((f"{geo}/abc", geo), moves)
        self.assertIn(("CHAR_GEO_OGRE_null_v001.abc", ), [tuple(n.split(" -> ")[:1]) for n in moves[(f"{geo}/abc", geo)]["names"]])
        nested = moves[(f"{geo}/FBX/CHAR_GEO_OGRE_null_FBX_V003", geo)]
        self.assertEqual(nested["names"], ["CHAR_GEO_OGRE_null.fbx -> CHAR_GEO_OGRE_null_v003.fbx"])
        bcol = self.bcol.relative_to(self.project).as_posix()
        self.assertIn(("assets/chara/OGRE/old_textures", bcol), moves)
        col = self.col.relative_to(self.project).as_posix()
        self.assertIn((col, bcol), moves)                                          # COL v001 -> BCOL v001
        self.assertTrue(any(i["kind"] == "old_map_name" and i["action"] == "drop_dup" for i in scan["items"]))
        self.assertTrue(any(i["path"] == f"{geo}/abc" and i["action"] == "drop_dup" for i in scan["items"]))
        warn = [i for i in scan["items"] if not i["safe"]]
        self.assertEqual(len(warn), 1)
        self.assertIn("fichier different", warn[0]["warning"])
        self.assertTrue(self._by(scan, "drop_tmp"))
        self.assertTrue(any(i["path"] == "assets/chara/OGRE/rig" for i in self._by(scan, "rm_empty")))
        self.assertFalse(any("work" in i["path"] for i in scan["items"]))
        self.assertIn("assets/chara/OGRE/work/CHAR_GEO_OGRE_null.abc", scan["unknown"])

    def test_apply_puts_files_back_and_undo_restores_everything(self) -> None:
        before = {str(p.relative_to(self.project)): p.read_text() for p in self.project.rglob("*") if p.is_file()}
        scan = ac.scan_asset(self.project, "OGRE")
        res = ac.apply_cleanup(self.project, "OGRE", [i["id"] for i in scan["items"]])
        self.assertTrue(res["journal"])
        self.assertTrue(any("pas sur" in e for e in res["errors"]))
        self.assertEqual((self.geo / "CHAR_GEO_OGRE_null_v001.abc").read_text(), "v1")
        self.assertEqual((self.geo / "CHAR_GEO_OGRE_null_v003.fbx").read_text(), "fbx3")
        self.assertEqual((self.geo / "CHAR_GEO_OGRE_null_LAST.abc").read_text(), "v2")     # never overwritten
        self.assertFalse((self.geo / "abc").exists())
        self.assertTrue((self.geo / "versions" / "CHAR_GEO_OGRE_null_LAST.abc").is_file())  # conflict kept
        self.assertEqual((self.bcol / "CHAR_SHADING_OGRE_BCOL_v003.png").read_text(), "b3")
        self.assertEqual((self.bcol / "CHAR_SHADING_OGRE_BCOL_v001.png").read_text(), "c1")
        self.assertFalse(self.col.exists())
        self.assertFalse((self.root / "rig").exists())
        self.assertFalse((self.root / "old_textures").exists())
        self.assertTrue((self.root / "work" / "ogre_sculpt.ztl").is_file())
        self.assertFalse(any(p.name.startswith(lp.TMP_PREFIX) for p in self.project.rglob("*")))
        # nothing certain left
        self.assertFalse([i for i in ac.scan_asset(self.project, "OGRE")["items"] if i["safe"]])
        # undo: every file back where it was, with its content (temp files excepted)
        jid = ac.list_backups(self.project)[0]["id"]
        ac.restore_cleanup(self.project, jid)
        after = {str(p.relative_to(self.project)): p.read_text() for p in self.project.rglob("*") if p.is_file()}
        self.assertEqual({k: v for k, v in before.items() if lp.TMP_PREFIX not in k}, after)

    def test_a_scene_or_usd_naming_a_path_keeps_it(self) -> None:
        _touch(self.project / "seq/SEQ001/SHOT010/light.hipnc",
               "tex = $FLUX/PROJ/" + self.col.relative_to(self.project).as_posix()
               + "/CHAR_SHADING_OGRE_COL_v001.png")
        scan = ac.scan_asset(self.project, "OGRE")
        kept = [i for i in scan["items"] if i["kind"] == "old_map_name" and not i["safe"]]
        self.assertTrue(kept)
        self.assertIn("light.hipnc", kept[0]["warning"])

    def test_project_clone_is_put_on_the_current_layout_and_the_original_is_untouched(self) -> None:
        res = ac.clone_project(self.project, "PROJ_CLEAN")
        clone = self.project.parent / "PROJ_CLEAN"
        geo = clone / self.geo.relative_to(self.project)
        self.assertEqual(res["project"], "PROJ_CLEAN")
        self.assertEqual((geo / "CHAR_GEO_OGRE_null_v001.abc").read_text(), "v1")
        self.assertFalse((geo / "abc").exists())
        self.assertEqual(res["warnings"], 1)
        self.assertNotEqual(json.loads((clone / "project.json").read_text())["project_id"], "old")
        self.assertTrue((self.geo / "abc" / "CHAR_GEO_OGRE_null_v001.abc").is_file())      # original
        with self.assertRaises(ValueError):
            ac.clone_project(self.project, "PROJ_CLEAN")


if __name__ == "__main__":
    unittest.main()
