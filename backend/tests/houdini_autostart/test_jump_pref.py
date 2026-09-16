# test_jump_pref.py - $FLUX favourites in Houdini's file chooser (jump.pref).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dcc.houdini import autostart


class JumpPrefTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.prefs = Path(self._tmp.name)
        self.jump = self.prefs / "jump.pref"

    def test_creates_entries(self):
        self.assertTrue(autostart._write_flux_jump_pref(self.prefs))
        self.assertEqual(self.jump.read_text(encoding="utf-8").splitlines(),
                         ["$FLUX/", "$FLUX/DOSSIER_PROJETS/"])

    def test_keeps_user_entries_and_is_idempotent(self):
        self.jump.write_text("D:/refs/\n\n$HIP/\n", encoding="utf-8")
        autostart._write_flux_jump_pref(self.prefs)
        autostart._write_flux_jump_pref(self.prefs)
        lines = self.jump.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, ["D:/refs/", "$HIP/", "$FLUX/", "$FLUX/DOSSIER_PROJETS/"])
        self.assertNotIn("", lines)  # Houdini wants no empty line

    def test_remove_only_flux_entries(self):
        self.jump.write_text("D:/refs/\n$FLUX/\n$FLUX/DOSSIER_PROJETS/\n", encoding="utf-8")
        autostart._remove_flux_jump_pref(self.prefs)
        self.assertEqual(self.jump.read_text(encoding="utf-8").splitlines(), ["D:/refs/"])

    def test_remove_deletes_file_left_empty(self):
        autostart._write_flux_jump_pref(self.prefs)
        autostart._remove_flux_jump_pref(self.prefs)
        self.assertFalse(self.jump.exists())


if __name__ == "__main__":
    unittest.main()
