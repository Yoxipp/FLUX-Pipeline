# test_montage_export.py - export of the Timeline auto edit (media + otio + edl + mov).

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.production import montage_export, ref_media
from tests.repository._backend import setUpModule, tearDownModule  # noqa: F401


class MontageExport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "PROJ"
        self.dest = Path(self._tmp.name) / "OUT"
        self.dest.mkdir()
        pub = self.root / "shot/SEQ001/SHOT010/anim/capture"
        pub.mkdir(parents=True)
        (pub / "A_v001.png").write_bytes(b"png")
        (pub / "A_LAST.png").write_bytes(b"png")
        ref_media.deposit(self.root, "shot/SEQ001/SHOT020/layout", "l.mp4", b"mp4", "ADAM")
        self.clips = [
            {"seq": "SEQ001", "shot": "SHOT010", "frames": 48, "media": {
                "task": "ANIM", "label": "Animation", "rel_path": "shot/SEQ001/SHOT010/anim/capture",
                "file": "A_LAST.png", "source": "publish"}},
            {"seq": "SEQ001", "shot": "SHOT020", "frames": 24, "media": {
                "task": "LAYOUT", "label": "Layout", "rel_path": "shot/SEQ001/SHOT020/layout",
                "file": "LAST.mp4", "source": "ref"}},
            {"seq": "SEQ001", "shot": "SHOT030", "frames": 12, "media": None},
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_folder_export_copies_media_and_writes_timelines(self):
        r = montage_export.export_montage(self.root, self.clips, 24, str(self.dest), "SEQ001", mov=False)
        out = Path(r["dir"])
        self.assertEqual(sorted(p.name for p in (out / "media").iterdir()),
                         ["0010_SEQ001_SHOT010_ANIM.png", "0020_SEQ001_SHOT020_LAYOUT.mp4"])
        self.assertEqual((r["shots"], r["missing"], r["mov"]), (3, 1, None))
        otio = json.loads(Path(r["otio"]).read_text(encoding="utf-8"))
        kids = otio["tracks"]["children"][0]["children"]
        self.assertEqual([k["OTIO_SCHEMA"] for k in kids], ["Clip.2", "Clip.2", "Gap.1"])
        self.assertEqual(kids[0]["source_range"]["duration"]["value"], 48.0)
        edl = Path(r["edl"]).read_text(encoding="utf-8")
        self.assertIn("001  AX       V     C        00:00:00:00 00:00:02:00 01:00:00:00 01:00:02:00", edl)
        self.assertIn("002  AX       V     C        00:00:00:00 00:00:01:00 01:00:02:00 01:00:03:00", edl)

    def test_media_outside_the_project_is_refused_as_a_gap(self):
        clips = [{"seq": "S", "shot": "X", "frames": 10,
                  "media": {"task": "ANIM", "rel_path": "..", "file": "A_LAST.png", "source": "publish"}}]
        r = montage_export.export_montage(self.root, clips, 24, str(self.dest), "x", mov=False)
        self.assertEqual(r["missing"], 1)
        self.assertTrue(r["warnings"])

    def test_no_ffmpeg_still_exports_the_folder(self):
        with mock.patch.object(montage_export, "find_ffmpeg", return_value=None):
            r = montage_export.export_montage(self.root, self.clips, 24, str(self.dest), "m")
        self.assertIsNone(r["mov"])
        self.assertTrue(Path(r["edl"]).is_file())
        self.assertTrue(any("ffmpeg" in w for w in r["warnings"]))

    def test_bad_destination(self):
        with self.assertRaises(ValueError):
            montage_export.export_montage(self.root, self.clips, 24, str(self.dest / "nope"), "m")


if __name__ == "__main__":
    unittest.main()
