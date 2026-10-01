# 2026-09-27: renaming a shot / sequence in Production renames it on disk. Only an
# entity without artist files is renamed (publishes carry the name in their files).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.folder_manager import seq_shot_creator as ssc
from features.folder_manager.tokens import build_default_tokens, load_tokens, save_tokens
from features.production import rename
from features.production.reconcile import reconcile

_NO_HIP = {"ok": False, "error": "no hython in tests"}


def _production() -> dict:
    return {"version": 1, "assets": [], "asset_groups": [],
            "sequences": [{"id": "seq_a", "name": "SEQ001"}],
            "shots": [{"id": "sh_1", "seq_id": "seq_a", "name": "SHOT010", "tasks": []},
                      {"id": "sh_2", "seq_id": "seq_a", "name": "SHOT020", "tasks": []}]}


class RenameSeqShot(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="flux_rename_"))
        save_tokens(self.project, build_default_tokens())
        self.patches = [mock.patch.object(ssc, "_write_shot_stage"),
                         mock.patch.object(ssc, "create_sequence_render_scene_async"),
                         mock.patch("features.folder_manager.houdini_render_scene.create_sequence_render_scene_async")]
        for p in self.patches:
            p.start()
        ssc.create_shot(self.project, 1, 10, seq_label="SEQ001", shot_label="SHOT010")   # older 3-digit project
        ssc.create_shot(self.project, 1, 20, seq_label="SEQ001", shot_label="SHOT020")
        (self.project / "shot/SEQ001/SHOT010/anim/block").mkdir(parents=True)
        (self.project / "shot/SEQ001/SHOT010/usd").mkdir(exist_ok=True)     # the shot stage (FLUX)
        (self.project / "shot/SEQ001/SHOT010/usd/stage.usda").write_text("generated", encoding="utf-8")
        # A sequence made before ADR 0038: its render scene under usd/lighting.
        render = self.project / "shot/SEQ001/usd/lighting"
        render.mkdir(parents=True, exist_ok=True)
        (render / "SEQ001_render.hip").write_text("lighting work", encoding="utf-8")

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.project, ignore_errors=True)

    def test_an_empty_shot_is_renamed_on_disk(self) -> None:
        self.assertEqual(rename.blockers(self.project, "shot", "SEQ001", "SHOT010"), [])
        prod = _production()
        rename.rename_in_production(prod, "shot", "SEQ001", "SHOT010", "SHOT015")
        res = rename.rename_on_disk(self.project, "shot", "SEQ001", "SHOT010", "SHOT015")
        self.assertEqual(prod["shots"][0]["name"], "SHOT015")
        self.assertFalse((self.project / "shot/SEQ001/SHOT010").exists())
        self.assertTrue((self.project / "shot/SEQ001/SHOT015/anim/block").is_dir())   # empty folders kept
        self.assertTrue(res["archived"].startswith("ARCHIVE/"))                       # never deleted
        shots = load_tokens(self.project)["SHOT"]
        self.assertIn("SEQ001/SHOT015", shots)
        self.assertNotIn("SEQ001/SHOT010", shots)

    def test_a_shot_with_publishes_is_refused(self) -> None:
        pub = self.project / "shot/SEQ001/SHOT010/anim/block/SEQ001_SHOT010_ANIM_UTAH_LAST.usd"
        pub.write_text("x", encoding="utf-8")
        self.assertEqual(rename.blockers(self.project, "shot", "SEQ001", "SHOT010"),
                         ["shot/SEQ001/SHOT010/anim/block/SEQ001_SHOT010_ANIM_UTAH_LAST.usd"])

    def test_a_sequence_is_renamed_with_its_shots_and_keeps_its_render_scene(self) -> None:
        self.assertEqual(rename.blockers(self.project, "seq", "SEQ001"), [])
        prod = _production()
        rename.rename_in_production(prod, "seq", "SEQ001", "", "SEQ005")
        res = rename.rename_on_disk(self.project, "seq", "SEQ001", "", "SEQ005")
        self.assertEqual(prod["sequences"][0]["name"], "SEQ005")
        for rel in ("shot/SEQ005/SHOT010/anim/block", "shot/SEQ005/SHOT020"):
            self.assertTrue((self.project / rel).is_dir(), rel)
        self.assertFalse((self.project / "shot/SEQ001").exists())
        kept = self.project / "shot/SEQ005/SEQ005_render.hip"          # ADR 0038 place
        self.assertEqual(kept.read_text(encoding="utf-8"), "lighting work")
        self.assertTrue(any("SEQ001" in w for w in res["warnings"]))
        self.assertIn("SEQ005", load_tokens(self.project)["SEQ"])

    def test_old_publish_events_do_not_bring_the_old_name_back(self) -> None:
        prod = _production()
        rename.rename_in_production(prod, "shot", "SEQ001", "SHOT010", "SHOT015")
        prod["archived"][-1]["at"] = "2026-09-27 14:00"
        events = [{"file": "SEQ001_SHOT010_ANIM_v001.usd", "date": "2026-09-27", "time": "13:00"}]
        prod, _, _ = reconcile(prod, events, {"ANIM"})
        self.assertEqual(sorted(s["name"] for s in prod["shots"]), ["SHOT015", "SHOT020"])

    def test_a_stale_save_under_the_old_name_is_corrected(self) -> None:
        from features.production.archive import keep_archived_out

        saved = _production()
        rename.rename_in_production(saved, "shot", "SEQ001", "SHOT010", "SHOT015")
        stale = _production()                       # another window, still SHOT010
        keep_archived_out(stale, saved)
        self.assertEqual(sorted(s["name"] for s in stale["shots"]), ["SHOT015", "SHOT020"])

    def test_bad_or_taken_names_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            rename.rename_in_production(_production(), "shot", "SEQ001", "SHOT010", "SHOT020")
        with self.assertRaises(ValueError):
            rename.rename_in_production(_production(), "shot", "SEQ001", "SHOT010", "PLAN1")


if __name__ == "__main__":
    unittest.main()
