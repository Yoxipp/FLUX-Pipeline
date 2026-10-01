# 2026-10-01: new sequences / shots are SEQ0010 / SHOT0010 (4 digits, steps of 10);
# an older project's SEQ001 / SHOT010 is reused, never re-padded into a second folder.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.folder_manager import seq_shot_creator as ssc
from features.folder_manager import tokens as tok
from features.folder_manager.naming_validator import format_seq, format_shot, parse_filename


class SeqShotLabels(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tok.save_tokens(self.project, tok.build_default_tokens())
        for target in (mock.patch.object(ssc, "create_sequence_render_scene_async"),
                       mock.patch("features.usd_assembler.shot_stage.write_stage")):
            target.start()
            self.addCleanup(target.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_new_labels_have_four_digits(self) -> None:
        self.assertEqual((format_seq(10), format_shot(15)), ("SEQ0010", "SHOT0015"))
        path = ssc.create_shot(self.project, 10, 20)
        self.assertEqual(path.relative_to(self.project).as_posix(), "shot/SEQ0010/SHOT0020")

    def test_existing_three_digit_names_are_reused(self) -> None:
        tok.add_token(self.project, "SEQ", "SEQ001", "shot/SEQ001")
        tok.add_token(self.project, "SHOT", "SEQ001/SHOT010", "shot/SEQ001/SHOT010")
        self.assertEqual(ssc.seq_label_for(self.project, 1), "SEQ001")
        self.assertEqual(ssc.shot_label_for(self.project, "SEQ001", 10), "SHOT010")
        # A new shot slotted in an old sequence keeps the sequence name, gets a 4-digit shot.
        path = ssc.create_shot(self.project, 1, 15)
        self.assertEqual(path.relative_to(self.project).as_posix(), "shot/SEQ001/SHOT0015")
        self.assertEqual(ssc.list_shots(self.project, 1), ["SEQ001/SHOT0015", "SEQ001/SHOT010"])

    def test_production_names_win(self) -> None:
        ssc.update_sequence(self.project, 1, [{"number": 10, "label": "SHOT010"}], seq_label="SEQ001")
        self.assertTrue((self.project / "shot/SEQ001/SHOT010").is_dir())
        self.assertFalse((self.project / "shot/SEQ0001").exists())

    def test_four_digit_publish_names_parse(self) -> None:
        parsed = parse_filename("SEQ0010_SHOT0015_ANIM_null_v003.abc")
        self.assertEqual((parsed["SEQ"], parsed["SHOT"], parsed["TYPE"]), ("SEQ0010", "SHOT0015", "ANIM"))


if __name__ == "__main__":
    unittest.main()
