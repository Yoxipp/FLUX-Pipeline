# 2026-10-13: "Copy Path Relative" of the Folder Manager builds the path on the
# scene variables the FLUX Work HDA sets in Houdini ($PROD, $SEQ, $SHOT, $ASSET).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.folder_manager import tokens as tok
from features.folder_manager.relative_path import relative_path


class RelativePath(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tok.save_tokens(self.project, tok.build_default_tokens())
        tok.add_token(self.project, "SEQ", "SEQ0010", "shot/SEQ0010")
        tok.add_token(self.project, "SHOT", "SEQ0010/SHOT0020", "shot/SEQ0010/SHOT0020")
        tok.add_token(self.project, "NAME", "MECHANT", "assets/chara/MECHANT")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _rel(self, rel: str) -> str:
        return relative_path(self.project, "PROJ", rel)

    def test_project_root(self) -> None:
        self.assertEqual(self._rel(""), "$FLUX/DOSSIER_PROJETS/$PROD")

    def test_shot_folder_and_file(self) -> None:
        self.assertEqual(self._rel("shot/SEQ0010/SHOT0020/fx"),
                         "$FLUX/DOSSIER_PROJETS/$PROD/shot/$SEQ/$SHOT/fx")
        self.assertEqual(self._rel("shot/SEQ0010/SHOT0020/fx/SEQ0010_SHOT0020_fx.bgeo"),
                         "$FLUX/DOSSIER_PROJETS/$PROD/shot/$SEQ/$SHOT/fx/${SEQ}_${SHOT}_fx.bgeo")

    def test_render_folder_nests_seq_shot_too(self) -> None:
        self.assertEqual(self._rel("render/SEQ0010/SHOT0020"),
                         "$FLUX/DOSSIER_PROJETS/$PROD/render/$SEQ/$SHOT")

    def test_sequence_only_and_unknown_shot(self) -> None:
        self.assertEqual(self._rel("shot/SEQ0010/SHOT9999"),
                         "$FLUX/DOSSIER_PROJETS/$PROD/shot/$SEQ/SHOT9999")

    def test_character(self) -> None:
        self.assertEqual(self._rel("assets/chara/MECHANT/rig/MECHANT_rig.usd"),
                         "$FLUX/DOSSIER_PROJETS/$PROD/assets/chara/$ASSET/rig/${ASSET}_rig.usd")

    def test_prop_keeps_its_name(self) -> None:
        self.assertEqual(self._rel("assets/props/CHAISE"),
                         "$FLUX/DOSSIER_PROJETS/$PROD/assets/props/CHAISE")

    def test_value_needs_boundaries(self) -> None:
        self.assertEqual(self._rel("shot/SEQ0010/notes_SEQ00100.txt"),
                         "$FLUX/DOSSIER_PROJETS/$PROD/shot/$SEQ/notes_SEQ00100.txt")


if __name__ == "__main__":
    unittest.main()
