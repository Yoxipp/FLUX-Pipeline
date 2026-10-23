"""Image sequence found from a pasted path (denoise of an already rendered sequence)."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from features.render import image_sequence as seq


class Find(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for f in (1001, 1002, 1003, 1005):
            (self.dir / f"SQ01_SH010.{f}.exr").write_bytes(b"")
        (self.dir / "notes.txt").write_text("x")

    def test_from_one_frame_pattern_or_folder(self):
        for given in ("SQ01_SH010.1002.exr", "SQ01_SH010.####.exr", "SQ01_SH010.$F4.exr", ""):
            out = seq.find(str(self.dir / given) if given else str(self.dir))
            self.assertEqual((out["pattern"], out["first"], out["last"], out["count"], out["missing"]),
                             ("SQ01_SH010.$F4.exr", 1001, 1005, 4, [1004]), given)

    def test_refused(self):
        (self.dir / "other.0001.exr").write_bytes(b"")
        with self.assertRaises(seq.SequenceError):
            seq.find(str(self.dir))  # two sequences: ask for a frame
        for bad in ("", str(self.dir / "notes.txt"), str(self.dir / "nope" / "a.1.exr"), str(self.dir / "x.####.exr")):
            with self.assertRaises(seq.SequenceError):
                seq.find(bad)


if __name__ == "__main__":
    unittest.main()
