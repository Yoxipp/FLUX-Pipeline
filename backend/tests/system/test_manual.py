"""The bundled manual lands in FLUX_UPDATE and is refreshed when it changes."""

import tempfile
import unittest
from pathlib import Path

from features.system.manual import MANUAL_FILENAME, MANUAL_SOURCE, ensure_manual


class EnsureManual(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "src.html"
        self.source.write_text("<html>v1</html>", encoding="utf-8")
        self.update = self.root / "FLUX_UPDATE"

    def tearDown(self):
        self._tmp.cleanup()

    def test_bundled_manual_exists(self):
        self.assertTrue(MANUAL_SOURCE.is_file())

    def test_copies_when_missing(self):
        dest = ensure_manual(self.update, self.source)
        self.assertEqual(dest, self.update / MANUAL_FILENAME)
        self.assertEqual(dest.read_text(encoding="utf-8"), "<html>v1</html>")

    def test_refreshes_when_different(self):
        ensure_manual(self.update, self.source)
        self.source.write_text("<html>v2</html>", encoding="utf-8")
        dest = ensure_manual(self.update, self.source)
        self.assertEqual(dest.read_text(encoding="utf-8"), "<html>v2</html>")

    def test_missing_source_is_noop(self):
        self.assertIsNone(ensure_manual(self.update, self.root / "nope.html"))
        self.assertFalse(self.update.exists())


if __name__ == "__main__":
    unittest.main()
