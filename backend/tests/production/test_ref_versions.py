# test_ref_versions.py - /ref versions come from the folder's modif log (retake 10).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.production import ref_media
from tests.repository._backend import setUpModule, tearDownModule  # noqa: F401


class RefVersions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.rel = "shot/SEQ010/SHOT020/anim"

    def tearDown(self):
        self._tmp.cleanup()

    def test_single_deposit_is_the_latest_and_logged(self):
        ref_media.deposit(self.root, self.rel, "playblast_A.mp4", b"a", "TOM")
        rows = ref_media.versions(self.root, self.rel)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["version"], row["file"], row["user"], row["source_name"]),
                         ("v001", "v001.mp4", "TOM", "playblast_A.mp4"))
        self.assertTrue(row["latest"] and row["available"] and row["playable"] and row["logged"])

    def test_versions_newest_first_with_formats(self):
        ref_media.deposit(self.root, self.rel, "a.mp4", b"1", "TOM")
        ref_media.deposit(self.root, self.rel, "b.mov", b"2", "ADAM")
        ref_media.deposit(self.root, self.rel, "c.png", b"3", "TOM")
        rows = ref_media.versions(self.root, self.rel)
        self.assertEqual([r["version"] for r in rows], ["v003", "v002", "v001"])
        self.assertEqual([r["latest"] for r in rows], [True, False, False])
        self.assertFalse(rows[1]["playable"])            # mov: Keyframe, not the browser
        self.assertEqual(rows[0]["kind"], "image")

    def test_deleted_version_stays_listed_as_unavailable(self):
        ref_media.deposit(self.root, self.rel, "a.mp4", b"1", "TOM")
        ref_media.deposit(self.root, self.rel, "b.mp4", b"2", "TOM")
        (self.root / self.rel / "ref" / "v002.mp4").unlink()
        rows = ref_media.versions(self.root, self.rel)
        self.assertFalse(rows[0]["available"])
        self.assertFalse(rows[0]["latest"])
        self.assertTrue(rows[1]["latest"])                 # newest file still on disk

    def test_unlogged_files_are_flagged(self):
        ref_dir = self.root / self.rel / "ref"
        ref_dir.mkdir(parents=True)
        (ref_dir / "v001.mp4").write_bytes(b"old")
        (ref_dir / "LAST.mp4").write_bytes(b"old")
        rows = ref_media.versions(self.root, self.rel)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["logged"])

    def test_empty_zone(self):
        self.assertEqual(ref_media.versions(self.root, self.rel), [])

    def test_shot_previews_follow_task_order(self):
        ref_media.deposit(self.root, "shot/SEQ010/SHOT020/layout", "l.mp4", b"l", "TOM")
        ref_media.deposit(self.root, "shot/SEQ010/SHOT020/anim", "a.mp4", b"a", "TOM")
        media = ref_media.shot_previews(self.root, "SEQ010", "SHOT020", ["STORYBOARD", "LAYOUT", "ANIM", "anim"])
        self.assertEqual([m["task"] for m in media], ["LAYOUT", "ANIM"])
        self.assertEqual(media[1]["version"], "v001")
        self.assertTrue(Path(media[1]["abs_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
