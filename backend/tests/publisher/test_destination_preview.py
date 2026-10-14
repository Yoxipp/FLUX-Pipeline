# test_destination_preview.py - the read-only publisher "Destination" card data.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.publisher import destination_preview as dp

BASE = "CHAR_MOD_HERO_null"


class DestinationPreviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.dest = self.project / "chars" / "hero" / "mod" / "null"
        patcher = mock.patch.object(dp, "resolve_publish_path", return_value=self.dest)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_first_publish(self):
        info = dp.destination_preview(self.project, BASE, ".mb")
        self.assertEqual(info["version"], "v001")
        self.assertTrue(info["first"])
        self.assertFalse(info["last_exists"])
        self.assertEqual(info["rel_path"], "chars/hero/mod/null")

    def test_existing_folder(self):
        self.dest.mkdir(parents=True)
        for n in (f"{BASE}_v001.mb", f"{BASE}_v002.mb", f"{BASE}_LAST.mb",
                  f"{BASE}_LAST.usd", f"{BASE}_v001.usd", "notes.txt"):
            (self.dest / n).write_text("x")
        info = dp.destination_preview(self.project, BASE, "mb")
        # The LAST.mb here has no metadata (pre-0017 copy): it gets archived, so +1.
        self.assertEqual(info["version"], "v004")
        self.assertFalse(info["first"])
        self.assertTrue(info["last_exists"])
        self.assertEqual(info["existing"], [f"{BASE}_v002.mb", f"{BASE}_LAST.usd"])
        self.assertEqual(info["more"], 3)
        # The other format's LAST shows its own lineage (pre-0017 copy: its top vNNN).
        self.assertEqual(info["existing_versions"][f"{BASE}_LAST.usd"], "v001")

    def test_unresolved(self):
        with mock.patch.object(dp, "resolve_publish_path", return_value=None):
            self.assertIsNone(dp.destination_preview(self.project, BASE, ".mb"))


if __name__ == "__main__":
    unittest.main()
