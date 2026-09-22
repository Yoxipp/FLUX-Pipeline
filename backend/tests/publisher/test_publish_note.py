# N7: the note of a published file (who, when, what) read from modif_logs.json.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.publisher import publish_note as pn

_LOGS = [  # newest first, as read_logs returns them
    {"name": "CHAR_GEO_DINGO_null", "date": "2026-09-19", "time": "10:00", "version": "v003",
     "modification": "fix uv", "user": "ADAM"},
    {"name": "CHAR_GEO_DINGO_null", "date": "2026-09-18", "time": "09:00", "version": "v002",
     "modification": "first pass", "user": "LOU"},
    {"name": "CHAR_GEO_DINGO_nullx", "date": "2026-09-18", "time": "09:00", "version": "v009",
     "modification": "other asset", "user": "LOU"},
]


class PublishNote(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)
        self.folder = self.project / "assets/chara/DINGO/model/null"
        (self.folder / "CHAR_GEO_DINGO_null_v002").mkdir(parents=True)
        (self.folder / "CHAR_GEO_DINGO_null_v002" / "CHAR_GEO_DINGO_null_model.usda").write_text("x")
        (self.folder / "CHAR_GEO_DINGO_null_LAST.usda").write_text("x")
        patcher = mock.patch.object(pn, "read_logs",
                                    side_effect=lambda f: _LOGS if Path(f) == self.folder else [])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _note(self, rel: str) -> dict:
        return pn.publish_notes(self.project, "assets/chara/DINGO/model/null/" + rel)

    def _log(self, rel: str) -> dict:
        return pn.file_log(self.project, "assets/chara/DINGO/model/null/" + rel)

    def test_file_log_returns_matched_and_folder(self) -> None:
        r = self._log("CHAR_GEO_DINGO_null_LAST.usda")
        # matched: entries whose name matches the file's base.
        self.assertEqual(len(r["matched"]), 2)
        # folder_log: everything in this folder's modif_logs.json (all 3 entries).
        self.assertEqual(len(r["folder_log"]), 3)
        self.assertEqual(r["folder_path"], str(self.folder))
        self.assertEqual(r["base"], "CHAR_GEO_DINGO_null")

    def test_last_shows_the_newest_note(self) -> None:
        note = self._note("CHAR_GEO_DINGO_null_LAST.usda")
        self.assertEqual((note["base"], note["version"]), ("CHAR_GEO_DINGO_null", None))
        self.assertEqual(note["latest"]["modification"], "fix uv")
        self.assertEqual([e["version"] for e in note["history"]], ["v003", "v002"])

    def test_a_version_folder_or_its_files_show_that_version(self) -> None:
        for rel in ("CHAR_GEO_DINGO_null_v002", "CHAR_GEO_DINGO_null_v002/CHAR_GEO_DINGO_null_model.usda"):
            note = self._note(rel)
            self.assertEqual(note["version"], "v002", rel)
            self.assertEqual(note["latest"]["user"], "LOU", rel)

    def test_no_log_no_note(self) -> None:
        note = pn.publish_notes(self.project, "assets/chara/DINGO/rig/null/CHAR_RIG_DINGO_null_LAST.usda")
        self.assertIsNone(note["latest"])
        self.assertEqual(note["history"], [])

    def test_link_and_meta_files_name_their_base(self) -> None:
        self.assertEqual(pn._base_and_version(self.folder / "CHAR_GEO_DINGO_null_LAST.bgeo.sc.link"),
                         ("CHAR_GEO_DINGO_null", None))
        self.assertEqual(pn._base_and_version(self.folder / "X_v012.abc"), ("X", "v012"))


if __name__ == "__main__":
    unittest.main()
