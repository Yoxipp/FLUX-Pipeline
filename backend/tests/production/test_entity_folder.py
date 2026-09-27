# B1 (2026-09-28): Production opens a sequence / shot in the Folder Manager.
# The folder comes from the SEQ / SHOT tokens; count=False skips the file walk.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from features.folder_manager.tokens import build_default_tokens, save_tokens
from features.production import archive


class EntityFolder(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="flux_entfold_"))
        tokens = build_default_tokens()
        tokens["SEQ"] = {"SEQ001": "shot/SEQ001"}
        tokens["SHOT"] = {"SEQ001/SHOT010": "shot/SEQ001/SHOT010"}
        save_tokens(self.project, tokens)
        shot = self.project / "shot/SEQ001/SHOT010/anim"
        shot.mkdir(parents=True)
        (shot / "a.ma").write_text("x")

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def test_shot_folder_is_resolved_from_its_token(self) -> None:
        rel = archive.resolve_entity_rel(self.project, "shot", seq="seq001", shot="shot010")
        self.assertEqual(rel, "shot/SEQ001/SHOT010")
        self.assertEqual(archive.inspect_folder(self.project, rel)["file_count"], 1)

    def test_count_false_skips_the_walk(self) -> None:
        info = archive.inspect_folder(self.project, "shot/SEQ001", count=False)
        self.assertEqual(info, {"rel_path": "shot/SEQ001", "exists": True, "file_count": 0})

    def test_missing_folder_is_reported(self) -> None:
        rel = archive.resolve_entity_rel(self.project, "shot", seq="SEQ001", shot="SHOT020")
        self.assertFalse(archive.inspect_folder(self.project, rel, count=False)["exists"])


if __name__ == "__main__":
    unittest.main()
