# Bug A5 (2026-10-09): a shot sub-task made in Production was created on disk but the
# sync log said {'subtasks': 0, 'sequences': 2}; and shot task folders were resolved
# with the CLASS map instead of the shot TYPE map (TYPE_SHOT, ADR 0019).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.folder_manager import seq_shot_creator as ssc
from features.folder_manager.tokens import build_default_tokens, save_tokens
from features.production import ref_media
from features.production.sync import _shot_task_token, sync_production_to_disk


def _production(tasks: list[dict]) -> dict:
    return {"sequences": [{"id": "s1", "name": "SEQ0010"}, {"id": "s2", "name": "SEQ0020"}],
            "shots": [{"seq_id": "s1", "name": "SHOT0030", "tasks": tasks}]}


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="flux_a5_"))
        self.tokens = build_default_tokens()
        save_tokens(self.project, self.tokens)
        patcher = mock.patch.object(ssc, "create_sequence_render_scene_async", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.project, True)


class SyncCountsWhatItCreates(_Base):
    def test_subtask_counted_and_noop_counts_nothing(self) -> None:
        anim = {"name": "ANIM", "type_tokens": ["ANIM"], "known_subtasks": []}
        first = sync_production_to_disk(self.project, _production([anim]))
        self.assertEqual(first["sequences"], 2)
        self.assertEqual(first["shots"], 1)
        self.assertEqual(first["subtasks"], 0)

        anim["known_subtasks"] = ["Muscles"]
        second = sync_production_to_disk(self.project, _production([anim]))
        self.assertTrue((self.project / "shot/SEQ0010/SHOT0030/anim/muscles").is_dir())
        self.assertEqual(second, {"assets": 0, "sequences": 0, "shots": 0, "tasks": 0, "subtasks": 1})

        third = sync_production_to_disk(self.project, _production([anim]))
        self.assertFalse(any(third.values()), third)


class ShotTaskUsesTypeShot(_Base):
    def test_type_shot_wins_over_class(self) -> None:
        self.tokens["CLASS"]["LIGHT"] = "shot/{seq}/{shot}/light"      # legacy custom CLASS
        self.tokens["TYPE_SHOT"]["LIGHT"] = "lighting/{seq}"
        save_tokens(self.project, self.tokens)
        light = {"name": "LIGHT", "type_tokens": ["LIGHT"], "known_subtasks": ["key"]}
        sync_production_to_disk(self.project, _production([light]))
        self.assertTrue((self.project / "lighting/SEQ0010/key").is_dir())
        self.assertFalse((self.project / "shot/SEQ0010/SHOT0030/light").exists())

    def test_class_is_the_fallback_for_old_projects(self) -> None:
        self.tokens["CLASS"]["MATTE"] = "matte/{seq}/{shot}"
        save_tokens(self.project, self.tokens)
        task = {"name": "MATTE", "type_tokens": ["MATTE"], "known_subtasks": []}
        sync_production_to_disk(self.project, _production([task]))
        self.assertTrue((self.project / "matte/SEQ0010/SHOT0030").is_dir())

    def test_task_token_prefers_the_type_token(self) -> None:
        maps = (self.tokens["CLASS"], self.tokens["TYPE_SHOT"])
        self.assertEqual(_shot_task_token({"name": "Lighting", "type_tokens": ["LIGHT"]}, *maps), "LIGHT")
        self.assertEqual(_shot_task_token({"name": "LIGHT", "type_tokens": ["custom"]}, *maps), "LIGHT")
        self.assertEqual(_shot_task_token({"name": "Rotoscopy", "type_tokens": []}, *maps), "Rotoscopy")
        self.assertEqual(_shot_task_token({"name": "", "type_tokens": ["ROTO"]}, *maps), "ROTO")


class RefMediaShotRoot(_Base):
    def test_type_shot_resolution(self) -> None:
        self.tokens["CLASS"]["LIGHT"] = "shot/{seq}/{shot}/light"
        save_tokens(self.project, self.tokens)
        rel = ref_media.resolve_ref_root(self.project, "shot", seq="SEQ0010", shot="SHOT0030",
                                         task="LIGHT", subtask="key")
        self.assertEqual(rel, "shot/SEQ0010/SHOT0030/lighting/key")

    def test_existing_ref_under_the_old_location_is_kept(self) -> None:
        self.tokens["CLASS"]["LIGHT"] = "shot/{seq}/{shot}/light"
        save_tokens(self.project, self.tokens)
        (self.project / "shot/SEQ0010/SHOT0030/light/ref").mkdir(parents=True)
        rel = ref_media.resolve_ref_root(self.project, "shot", seq="SEQ0010", shot="SHOT0030",
                                         task="LIGHT")
        self.assertEqual(rel, "shot/SEQ0010/SHOT0030/light")

    def test_unknown_task_falls_back_under_the_shot(self) -> None:
        rel = ref_media.resolve_ref_root(self.project, "shot", seq="SEQ0010", shot="SHOT0030",
                                         task="Roto", subtask="Mask")
        self.assertEqual(rel, "shot/SEQ0010/SHOT0030/roto/mask")


if __name__ == "__main__":
    unittest.main()
