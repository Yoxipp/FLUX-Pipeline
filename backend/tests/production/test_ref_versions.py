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

    def test_both_origins_returned_with_versions(self):
        pub = self.root / "shot/SEQ010/SHOT020/anim/main"
        pub.mkdir(parents=True)
        for name in ("A_v001.mp4", "A_v002.mp4", "A_LAST.mp4"):
            (pub / name).write_bytes(b"x")
        ref_media.deposit(self.root, "shot/SEQ010/SHOT020/anim", "a.png", b"a", "TOM")
        ref_media.deposit(self.root, "shot/SEQ010/SHOT020/anim", "b.png", b"b", "TOM")
        media = ref_media.shot_previews(self.root, "SEQ010", "SHOT020", ["ANIM"])
        self.assertEqual([m["source"] for m in media], ["ref", "publish"])
        self.assertEqual([v["version"] for v in media[0]["versions"]], ["v002", "v001"])
        self.assertEqual(media[0]["versions"][1]["file"], "v001.png")
        self.assertEqual([v["file"] for v in media[1]["versions"]], ["A_v002.mp4", "A_v001.mp4"])
        # A chosen version streams for both origins.
        rel = media[0]["rel_path"]
        self.assertTrue(ref_media.resolve_file(self.root, rel, "v001.png").is_file())
        self.assertTrue(ref_media.resolve_publish_file(self.root, media[1]["rel_path"], "A_v001.mp4").is_file())

    def test_delete_version_repoints_last(self):
        for n in ("a.mp4", "b.mp4", "c.mp4"):
            ref_media.deposit(self.root, self.rel, n, n.encode(), "TOM")
        ref_dir = self.root / self.rel / "ref"
        r = ref_media.delete_version(self.root, self.rel, "v003.mp4")
        self.assertEqual((r["deleted"], r["last"]), ("v003.mp4", "LAST.mp4"))
        self.assertFalse((ref_dir / "v003.mp4").exists())
        self.assertEqual((ref_dir / "LAST.mp4").read_bytes(), b"b.mp4")      # newest remaining
        ref_media.delete_version(self.root, self.rel, "v001.mp4")
        ref_media.delete_version(self.root, self.rel, "v002.mp4")
        self.assertEqual(list(ref_dir.glob("LAST.*")), [])                   # none left: cleared
        self.assertIsNone(ref_media.latest(self.root, self.rel))

    def test_delete_refuses_last_and_escapes(self):
        ref_media.deposit(self.root, self.rel, "a.mp4", b"a", "TOM")
        for name in ("LAST.mp4", "../v001.mp4", "v001.exe", ""):
            with self.assertRaises(ValueError):
                ref_media.delete_version(self.root, self.rel, name)
        with self.assertRaises(ValueError):
            ref_media.delete_version(self.root, "../..", "v001.mp4")
        with self.assertRaises(FileNotFoundError):
            ref_media.delete_version(self.root, self.rel, "v009.mp4")
        self.assertTrue((self.root / self.rel / "ref" / "v001.mp4").exists())

    def test_restore_version_becomes_last(self):
        ref_media.deposit(self.root, self.rel, "a.mp4", b"first", "TOM")
        ref_media.deposit(self.root, self.rel, "b.mp4", b"second", "TOM")
        r = ref_media.restore_version(self.root, self.rel, "v001.mp4", "ADAM")
        self.assertEqual(r["version"], "v003")
        self.assertEqual((self.root / self.rel / "ref" / "LAST.mp4").read_bytes(), b"first")
        self.assertEqual(ref_media.versions(self.root, self.rel)[0]["source_name"], "v001.mp4")

    def test_publish_stream_refuses_other_files(self):
        (self.root / "shot").mkdir()
        (self.root / "shot" / "scene_LAST.ma").write_bytes(b"x")
        for rel, name in (("shot", "scene_LAST.ma"), ("..", "x_LAST.png"), ("shot", "../x_LAST.png")):
            with self.assertRaises(ValueError):
                ref_media.resolve_publish_file(self.root, rel, name)


if __name__ == "__main__":
    unittest.main()
