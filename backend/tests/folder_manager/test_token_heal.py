# test_token_heal.py — heal_tokens_from_disk adopts on-disk assets/shots into tokens.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.folder_manager.asset_creator import heal_tokens_from_disk
from features.folder_manager.tokens import build_default_tokens, load_tokens, save_tokens


def _project() -> Path:
    d = Path(tempfile.mkdtemp())
    save_tokens(d, build_default_tokens())
    return d


class TokenHealFromDisk(unittest.TestCase):
    def test_adds_missing_name_token_for_ondisk_asset(self):
        proj = _project()
        # CHAR → assets/chara (default). Asset folder on disk, no NAME token.
        (proj / "assets" / "chara" / "UTAH").mkdir(parents=True)
        added = heal_tokens_from_disk(proj)
        self.assertGreaterEqual(added, 1)
        tokens = load_tokens(proj)
        self.assertEqual(tokens["NAME"].get("UTAH"), "assets/chara/UTAH")

    def test_does_not_overwrite_existing_name_token(self):
        proj = _project()
        (proj / "assets" / "chara" / "UTAH").mkdir(parents=True)
        tokens = load_tokens(proj)
        tokens["NAME"]["UTAH"] = "assets/chara/CUSTOM_PATH"  # user-defined, must survive
        save_tokens(proj, tokens)
        heal_tokens_from_disk(proj)
        self.assertEqual(load_tokens(proj)["NAME"]["UTAH"], "assets/chara/CUSTOM_PATH")

    def test_adds_seq_and_shot_tokens(self):
        proj = _project()
        (proj / "shot" / "SEQ001" / "SHOT010").mkdir(parents=True)
        heal_tokens_from_disk(proj)
        tokens = load_tokens(proj)
        self.assertEqual(tokens["SEQ"].get("SEQ001"), "shot/SEQ001")
        self.assertEqual(tokens["SHOT"].get("SEQ001/SHOT010"), "shot/SEQ001/SHOT010")

    def test_idempotent_second_run_adds_nothing(self):
        proj = _project()
        (proj / "assets" / "chara" / "UTAH").mkdir(parents=True)
        (proj / "shot" / "SEQ001" / "SHOT010").mkdir(parents=True)
        first = heal_tokens_from_disk(proj)
        second = heal_tokens_from_disk(proj)
        self.assertGreaterEqual(first, 3)
        self.assertEqual(second, 0)


if __name__ == "__main__":
    unittest.main()
