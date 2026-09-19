# Live 2026-09-19: a shot archived from Production kept its SHOT token and came back.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from features.folder_manager.tokens import build_default_tokens, load_tokens, save_tokens
from features.production import archive


class ArchiveDropsTokens(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="flux_archtok_"))
        tokens = build_default_tokens()
        tokens["SEQ"] = {"SEQ001": "shot/SEQ001", "SEQ002": "shot/SEQ002"}
        tokens["SHOT"] = {"SEQ001/SHOT010": "shot/SEQ001/SHOT010", "SEQ001/SHOT0100": "shot/SEQ001/SHOT0100",
                          "SEQ002/SHOT010": "shot/SEQ002/SHOT010"}
        tokens["NAME"] = {"DINGO": "assets/chara/DINGO"}
        save_tokens(self.project, tokens)
        for rel in ("shot/SEQ001/SHOT010", "shot/SEQ002/SHOT010", "assets/chara/DINGO"):
            (self.project / rel).mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_a_shot_archive_drops_only_its_token(self) -> None:
        archive.archive_folder(self.project, "shot/SEQ001/SHOT010")
        self.assertEqual(archive.drop_tokens_under(self.project, "shot/SEQ001/SHOT010"), ["SHOT/SEQ001/SHOT010"])
        self.assertEqual(sorted(load_tokens(self.project)["SHOT"]), ["SEQ001/SHOT0100", "SEQ002/SHOT010"])

    def test_a_sequence_archive_drops_its_shots(self) -> None:
        removed = archive.drop_tokens_under(self.project, "shot\\SEQ002")
        self.assertEqual(removed, ["SEQ/SEQ002", "SHOT/SEQ002/SHOT010"])
        self.assertIn("SEQ001", load_tokens(self.project)["SEQ"])

    def test_an_asset_archive_drops_its_name(self) -> None:
        self.assertEqual(archive.drop_tokens_under(self.project, "assets/chara/DINGO"), ["NAME/DINGO"])
        self.assertEqual(archive.drop_tokens_under(self.project, ""), [])


if __name__ == "__main__":
    unittest.main()
