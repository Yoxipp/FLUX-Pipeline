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
        self.assertEqual(media[1]["source"], "ref")

    def test_shot_previews_fall_back_to_published_media(self):
        pub = self.root / "shot/SEQ010/SHOT020/anim/capture"
        pub.mkdir(parents=True)
        for name in ("ANIM_SHOT020_CAP_v001.png", "ANIM_SHOT020_CAP_v002.png", "ANIM_SHOT020_CAP_LAST.png", "scene_LAST.ma"):
            (pub / name).write_bytes(b"x")
        media = ref_media.shot_previews(self.root, "SEQ010", "SHOT020", ["ANIM"])
        self.assertEqual(len(media), 1)
        m = media[0]
        self.assertEqual((m["source"], m["rel_path"], m["file"], m["version"], m["version_count"], m["kind"]),
                         ("publish", "shot/SEQ010/SHOT020/anim/capture", "ANIM_SHOT020_CAP_LAST.png", "v002", 2, "image"))
        self.assertEqual(ref_media.resolve_publish_file(self.root, m["rel_path"], m["file"]), (pub / m["file"]).resolve())

    def test_ref_drop_wins_over_publish(self):
        pub = self.root / "shot/SEQ010/SHOT020/anim/main"
        pub.mkdir(parents=True)
        (pub / "A_LAST.mp4").write_bytes(b"x")
        ref_media.deposit(self.root, "shot/SEQ010/SHOT020/anim", "a.png", b"a", "TOM")
        media = ref_media.shot_previews(self.root, "SEQ010", "SHOT020", ["ANIM"])
        self.assertEqual(media[0]["source"], "ref")

    def test_publish_stream_refuses_other_files(self):
        (self.root / "shot").mkdir()
        (self.root / "shot" / "scene_LAST.ma").write_bytes(b"x")
        for rel, name in (("shot", "scene_LAST.ma"), ("..", "x_LAST.png"), ("shot", "../x_LAST.png")):
            with self.assertRaises(ValueError):
                ref_media.resolve_publish_file(self.root, rel, name)


if __name__ == "__main__":
    unittest.main()
