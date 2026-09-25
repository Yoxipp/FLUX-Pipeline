# test_force_remove.py — force_remove/force_rmtree delete read-only trees (WinError 5).

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from core import paths


class ForceRemoveReadOnly(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._force_cleanup)

    def _force_cleanup(self):
        # Make sure nothing read-only is left behind for TemporaryDirectory.
        for p in self.root.rglob("*"):
            try:
                os.chmod(p, stat.S_IWRITE)
            except OSError:
                pass
        self._tmp.cleanup()

    def test_force_rmtree_deletes_tree_with_readonly_file(self):
        d = self.root / "ARCHIVE" / "shot" / "SEQ001"
        d.mkdir(parents=True)
        f = d / "CHAR_REN_X_null_LAST.exr"
        f.write_text("bytes")
        os.chmod(f, stat.S_IREAD)          # read-only → plain rmtree would WinError 5
        top = self.root / "ARCHIVE"
        paths.force_rmtree(top)
        self.assertFalse(top.exists())

    def test_force_remove_single_readonly_file(self):
        f = self.root / "locked.txt"
        f.write_text("x")
        os.chmod(f, stat.S_IREAD)
        paths.force_remove(f)
        self.assertFalse(f.exists())

    def test_force_rmtree_missing_path_is_noop(self):
        paths.force_rmtree(self.root / "does_not_exist")  # must not raise


if __name__ == "__main__":
    unittest.main()
