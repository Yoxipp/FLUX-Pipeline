# B3 (2026-09-28): folder listings cached by the folder mtime, never stale on add / remove.

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from routers import files


class BrowseCache(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="flux_browse_")).resolve()
        (self.project / "a").mkdir()
        (self.project / "a" / "x.ma").write_text("x")

    def tearDown(self) -> None:
        shutil.rmtree(self.project, ignore_errors=True)

    def _list(self) -> tuple[list[str], list[str]]:
        target = self.project / "a"
        folders, fs = files._list_dir_cached(self.project, "a", target)
        return folders, [f.name for f in fs]

    def _bump(self, path: Path, step: int) -> None:
        st = path.stat()   # coarse filesystem clocks: force a distinct mtime
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + step * 1_000_000_000))

    def test_new_and_removed_entries_are_seen(self) -> None:
        self.assertEqual(self._list(), ([], ["x.ma"]))
        (self.project / "a" / "y.ma").write_text("y")
        (self.project / "a" / "sub").mkdir()
        self._bump(self.project / "a", 1)
        self.assertEqual(self._list(), (["sub"], ["x.ma", "y.ma"]))
        (self.project / "a" / "x.ma").unlink()
        self._bump(self.project / "a", 2)
        self.assertEqual(self._list(), (["sub"], ["y.ma"]))

    def test_hit_returns_copies(self) -> None:
        folders, fs = files._list_dir_cached(self.project, "a", self.project / "a")
        fs.clear()
        self.assertEqual(self._list(), ([], ["x.ma"]))


if __name__ == "__main__":
    unittest.main()
