# ADR 0019: a shot publish carries its department in the TYPE slot, like an asset
# (SEQ###_SHOT###_TYPE[_VARIANTE]); the legacy CLASS_SEQ###_SHOT### names still read.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.folder_manager import tokens as tok
from features.folder_manager.naming_validator import build_shot_filename, parse_filename
from features.publisher.publish_core import resolve_publish_path


class ShotNaming(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tok.save_tokens(self.project, tok.build_default_tokens())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_and_parse_the_current_form(self) -> None:
        name = build_shot_filename("SEQ010", "SHOT020", "ANIM", version="v003", extension=".abc")
        self.assertEqual(name, "SEQ010_SHOT020_ANIM_null_v003.abc")
        parsed = parse_filename(name)
        self.assertTrue(parsed["is_shot"])
        self.assertEqual((parsed["SEQ"], parsed["SHOT"], parsed["TYPE"]), ("SEQ010", "SHOT020", "ANIM"))
        self.assertEqual(parsed["ITER"], "v003")

    def test_legacy_form_still_parses_to_the_same_department(self) -> None:
        legacy = parse_filename("ANIM_SEQ010_SHOT020_null_v001.abc")
        self.assertTrue(legacy["is_shot"])
        self.assertEqual((legacy["SEQ"], legacy["SHOT"], legacy["TYPE"]), ("SEQ010", "SHOT020", "ANIM"))
        self.assertEqual(legacy["CLASS"], "ANIM")     # old readers keep working

    def test_both_forms_publish_to_the_same_folder(self) -> None:
        for name in ("SEQ010_SHOT020_ANIM_null_v001.abc", "ANIM_SEQ010_SHOT020_null_v001.abc"):
            path = resolve_publish_path(self.project, name)
            self.assertEqual(path, self.project / "shot" / "SEQ010" / "SHOT020" / "anim" / "null", name)

    def test_departments_of_a_shot_are_type_tokens(self) -> None:
        tokens = tok.load_tokens(self.project)
        self.assertEqual(tokens["TYPE_SHOT"]["LIGHT"], "shot/{seq}/{shot}/lighting")
        self.assertEqual(resolve_publish_path(self.project, "SEQ010_SHOT020_LIGHT_null_v001.hip"),
                         self.project / "shot" / "SEQ010" / "SHOT020" / "lighting" / "null")
        self.assertEqual(resolve_publish_path(self.project, "SEQ010_SHOT020_COMP_null_v001.nk"),
                         self.project / "shot" / "SEQ010" / "SHOT020" / "comp" / "null")
        # a project written before ADR 0019 has no TYPE_SHOT section: defaults fill it in
        raw = tok.build_default_tokens()
        raw.pop("TYPE_SHOT")
        tok.save_tokens(self.project, raw)
        self.assertIn("TYPE_SHOT", tok.load_tokens(self.project))
        # ...but LIGHT / COMP keep their pre-ADR 0055 roots there.
        self.assertEqual(resolve_publish_path(self.project, "SEQ010_SHOT020_LIGHT_null_v001.hip"),
                         self.project / "lighting" / "SEQ010" / "null")
        self.assertIsNotNone(resolve_publish_path(self.project, "SEQ010_SHOT020_FX_null_v001.bgeo"))

    def test_an_asset_name_is_not_read_as_a_shot(self) -> None:
        parsed = parse_filename("CHAR_GEO_UTAH_null_v001.usd")
        self.assertFalse(parsed["is_shot"])
        self.assertEqual((parsed["CLASS"], parsed["TYPE"], parsed["NAME"]), ("CHAR", "GEO", "UTAH"))


if __name__ == "__main__":
    unittest.main()
