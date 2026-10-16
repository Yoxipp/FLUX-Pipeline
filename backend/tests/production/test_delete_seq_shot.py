# Live 2026-09-27: a shot deleted in Production came back with its folder a few seconds
# later (reconcile re-created it from its old publishes, a stale save re-synced it).

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from core.constants import LEGACY_SHOT_ROOT_TOKENS
from features.folder_manager.tokens import build_default_tokens, save_tokens
from features.production import archive
from features.production.reconcile import reconcile


def _production() -> dict:
    return {
        "version": 1,
        "sequences": [{"id": "seq_a", "name": "SEQ001"}, {"id": "seq_b", "name": "SEQ002"}],
        "shots": [{"id": "sh_1", "seq_id": "seq_a", "name": "SHOT001", "tasks": []},
                  {"id": "sh_2", "seq_id": "seq_a", "name": "SHOT002", "tasks": []},
                  {"id": "sh_3", "seq_id": "seq_b", "name": "SHOT001", "tasks": []}],
        "assets": [], "asset_groups": [],
    }


def _event(seq: str, shot: str, date: str, time: str) -> dict:
    return {"action": "publish", "file": f"{seq}_{shot}_ANIM_v001.usd", "date": date, "time": time,
            "dest_folder": f"shot/{seq}/{shot}/anim"}


class DeleteSeqShot(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="flux_delseq_"))
        tokens = build_default_tokens()
        # comp/ and lighting/ at the project root: a project made before ADR 0055.
        tokens["TYPE_SHOT"].update(LEGACY_SHOT_ROOT_TOKENS)
        tokens["SEQ"] = {"SEQ001": "shot/SEQ001", "SEQ002": "shot/SEQ002"}
        tokens["SHOT"] = {"SEQ001/SHOT001": "shot/SEQ001/SHOT001", "SEQ001/SHOT002": "shot/SEQ001/SHOT002",
                          "SEQ002/SHOT001": "shot/SEQ002/SHOT001"}
        save_tokens(self.project, tokens)
        for rel in ("shot/SEQ001/SHOT001/anim", "shot/SEQ001/SHOT002/anim", "comp/SEQ001/SHOT002",
                    "comp/SEQ001/SHOT001", "lighting/SEQ001", "shot/SEQ002/SHOT001"):
            (self.project / rel).mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_a_shot_delete_archives_its_folders_and_entity(self) -> None:
        prod = _production()
        res = archive.delete_seq_shot(self.project, prod, "shot", "SEQ001", "SHOT002")
        self.assertEqual(res["removed_ids"], ["sh_2"])
        self.assertFalse((self.project / "shot/SEQ001/SHOT002").exists())
        self.assertFalse((self.project / "comp/SEQ001/SHOT002").exists())
        # The sequence lighting and the other shots stay.
        for rel in ("shot/SEQ001/SHOT001", "comp/SEQ001/SHOT001", "lighting/SEQ001"):
            self.assertTrue((self.project / rel).exists(), rel)
        self.assertEqual([s["id"] for s in prod["shots"]], ["sh_1", "sh_3"])

    def test_a_sequence_delete_takes_its_shots_comp_and_lighting(self) -> None:
        prod = _production()
        res = archive.delete_seq_shot(self.project, prod, "seq", "SEQ001")
        self.assertEqual(res["removed_ids"], ["seq_a", "sh_1", "sh_2"])
        for rel in ("shot/SEQ001", "comp/SEQ001", "lighting/SEQ001"):
            self.assertFalse((self.project / rel).exists(), rel)
        self.assertTrue((self.project / "shot/SEQ002/SHOT001").exists())
        self.assertEqual([s["id"] for s in prod["sequences"]], ["seq_b"])

    def test_archives_are_named_by_day_and_artist(self) -> None:
        # 2026-09-28: ARCHIVE/<date>_<artist>/..., a second one the same day gets _2.
        from datetime import datetime

        day = datetime.now().strftime("%Y-%m-%d")
        first = archive.archive_folder(self.project, "shot/SEQ001/SHOT001", user="Adam")
        (self.project / "shot/SEQ001/SHOT001").mkdir(parents=True)
        second = archive.archive_folder(self.project, "shot/SEQ001/SHOT001", user="Adam")
        self.assertEqual(first, f"ARCHIVE/{day}_ADAM/shot/SEQ001/SHOT001")
        self.assertEqual(second, f"ARCHIVE/{day}_ADAM_2/shot/SEQ001/SHOT001")
        self.assertEqual(archive.archive_label("", datetime(2026, 9, 28)), "2026-09-28_INCONNU")

    def test_old_publishes_do_not_bring_the_shot_back(self) -> None:
        prod = _production()
        archive.remove_entity(prod, "shot", "SEQ001", "SHOT002", at="2026-09-27 14:00")
        events = [_event("SEQ001", "SHOT002", "2026-09-27", "13:59")]
        prod, _, _ = reconcile(prod, events, {"ANIM"})
        self.assertNotIn("SHOT002", [s["name"] for s in prod["shots"] if s["seq_id"] == "seq_a"])
        # A publish made after the delete re-creates it (the shot is used again).
        events.append(_event("SEQ001", "SHOT002", "2026-09-27", "14:05"))
        prod, _, _ = reconcile(prod, events, {"ANIM"})
        self.assertIn("SHOT002", [s["name"] for s in prod["shots"] if s["seq_id"] == "seq_a"])

    def test_a_stale_save_cannot_restore_a_deleted_shot(self) -> None:
        saved = _production()
        archive.remove_entity(saved, "seq", "SEQ001")
        stale = _production()          # another window still holds SEQ001
        dropped = archive.keep_archived_out(stale, saved)
        self.assertEqual(dropped, 3)
        self.assertEqual([s["name"] for s in stale["sequences"]], ["SEQ002"])
        self.assertEqual(len(stale[archive.ARCHIVED_KEY]), 1)
        # A shot re-created by name gets a new id: kept.
        stale["shots"].append({"id": "sh_new", "seq_id": "seq_b", "name": "SHOT002"})
        self.assertEqual(archive.keep_archived_out(stale, saved), 0)


if __name__ == "__main__":
    unittest.main()
