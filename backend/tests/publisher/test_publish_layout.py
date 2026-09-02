# test_publish_layout.py — folder-per-version, per-format publish layout.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.publisher.publish_layout import (
    archive_last_folder, find_last_file, find_version_file, format_suffix,
    highest_version, highest_version_any, last_folder, parse_layout_folder,
    published_files, publish_into_layout,
)
from features.publisher.version_resolver import get_last_file, get_next_version

_BASE = "CHAR_RIG_CECILE_ALL_BODY_A"


def _src(dir_: Path, name: str, text: str = "x") -> Path:
    p = dir_ / name
    p.write_text(text)
    return p


class PublishLayout(unittest.TestCase):
    def test_format_suffix(self):
        self.assertEqual(format_suffix(".usd"), "USD")
        self.assertEqual(format_suffix(".fbx"), "FBX")
        self.assertEqual(format_suffix("usd"), "USD")

    def test_first_publish_creates_last_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = _src(tmp, "export.usd", "v1")
            dest = tmp / "all"
            path, ver = publish_into_layout(src, dest, _BASE)
            self.assertEqual(ver, 1)
            self.assertEqual(path, dest / f"{_BASE}_USD_LAST" / f"{_BASE}_LAST.usd")
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(), "v1")
            # no archive folder yet
            self.assertFalse((dest / f"{_BASE}_USD_V001").exists())

    def test_second_publish_archives_previous_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            p1, v1 = publish_into_layout(_src(tmp, "a.usd", "v1"), dest, _BASE)
            p2, v2 = publish_into_layout(_src(tmp, "b.usd", "v2"), dest, _BASE)
            self.assertEqual(v1, 1)
            self.assertEqual(v2, 2)
            # v001 archived (folder + inner file renamed, format NOT in file name)
            arch = dest / f"{_BASE}_USD_V001"
            self.assertTrue(arch.is_dir())
            self.assertTrue((arch / f"{_BASE}_v001.usd").exists())
            self.assertEqual((arch / f"{_BASE}_v001.usd").read_text(), "v1")
            # LAST now holds v2
            active = dest / f"{_BASE}_USD_LAST" / f"{_BASE}_LAST.usd"
            self.assertTrue(active.exists())
            self.assertEqual(active.read_text(), "v2")

    def test_third_publish_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            publish_into_layout(_src(tmp, "a.usd", "1"), dest, _BASE)
            publish_into_layout(_src(tmp, "b.usd", "2"), dest, _BASE)
            _, v3 = publish_into_layout(_src(tmp, "c.usd", "3"), dest, _BASE)
            self.assertEqual(v3, 3)
            self.assertTrue((dest / f"{_BASE}_USD_V001" / f"{_BASE}_v001.usd").exists())
            self.assertTrue((dest / f"{_BASE}_USD_V002" / f"{_BASE}_v002.usd").exists())
            self.assertEqual(highest_version(dest, _BASE, "USD"), 2)

    def test_formats_are_independent_lineages(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            # publish USD twice, FBX once
            publish_into_layout(_src(tmp, "a.usd", "u1"), dest, _BASE)
            _, uv2 = publish_into_layout(_src(tmp, "b.usd", "u2"), dest, _BASE)
            _, fv1 = publish_into_layout(_src(tmp, "c.fbx", "f1"), dest, _BASE)
            self.assertEqual(uv2, 2)
            self.assertEqual(fv1, 1)  # FBX starts its own line at v001
            self.assertTrue(last_folder(dest, _BASE, "USD").is_dir())
            self.assertTrue(last_folder(dest, _BASE, "FBX").is_dir())
            self.assertTrue((dest / f"{_BASE}_FBX_LAST" / f"{_BASE}_LAST.fbx").exists())
            # FBX has no archive yet, USD has V001
            self.assertFalse((dest / f"{_BASE}_FBX_V001").exists())
            self.assertTrue((dest / f"{_BASE}_USD_V001").is_dir())


class LayoutReaders(unittest.TestCase):
    def test_parse_layout_folder(self):
        self.assertEqual(parse_layout_folder(f"{_BASE}_USD_LAST"), (_BASE, "USD", "LAST"))
        self.assertEqual(parse_layout_folder(f"{_BASE}_FBX_V002"), (_BASE, "FBX", "v002"))
        # lowercase Houdini sequence folder must NOT be seen as a single-file archive
        self.assertIsNone(parse_layout_folder(f"{_BASE}_v001"))
        self.assertIsNone(parse_layout_folder("not_a_layout"))

    def test_find_last_and_version_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            publish_into_layout(_src(tmp, "a.usd", "1"), dest, _BASE)
            publish_into_layout(_src(tmp, "b.usd", "2"), dest, _BASE)
            self.assertEqual(find_last_file(dest, _BASE).read_text(), "2")
            self.assertEqual(find_last_file(dest, _BASE, fmt="usd").read_text(), "2")
            self.assertIsNone(find_last_file(dest, _BASE, fmt="fbx"))
            self.assertEqual(find_version_file(dest, _BASE, "v001").read_text(), "1")
            self.assertIsNone(find_version_file(dest, _BASE, "v999"))

    def test_published_files_bounded_descent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            dest.mkdir()
            # a Houdini-style sequence folder that must be ignored by descent
            seq = dest / f"{_BASE}_v001"
            seq.mkdir()
            (seq / f"{_BASE}_v001.0001.exr").write_text("frame")
            publish_into_layout(_src(tmp, "a.usd", "1"), dest, _BASE)
            names = {p.name for p in published_files(dest, _BASE)}
            self.assertIn(f"{_BASE}_LAST.usd", names)
            self.assertNotIn(f"{_BASE}_v001.0001.exr", names)  # sequence not slurped

    def test_find_last_file_light_export_folder(self):
        # usd_export light layout: fmt-less <base>_LAST/ with inner <base>.usd (no _LAST)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "usd"
            light = dest / f"{_BASE}_LAST"
            light.mkdir(parents=True)
            (light / f"{_BASE}.usd").write_text("root")
            got = find_last_file(dest, _BASE)
            self.assertIsNotNone(got)
            self.assertEqual(got.name, f"{_BASE}.usd")
            self.assertEqual(get_last_file(dest, _BASE).name, f"{_BASE}.usd")

    def test_get_last_file_nested_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            publish_into_layout(_src(tmp, "a.usd", "1"), dest, _BASE)
            # version_resolver primitive should see the nested LAST
            got = get_last_file(dest, _BASE)
            self.assertIsNotNone(got)
            self.assertEqual(got.name, f"{_BASE}_LAST.usd")

    def test_get_next_version_counts_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            publish_into_layout(_src(tmp, "a.usd", "1"), dest, _BASE)
            publish_into_layout(_src(tmp, "b.usd", "2"), dest, _BASE)  # V001 archived
            self.assertEqual(highest_version_any(dest, _BASE), 1)
            self.assertEqual(get_next_version(dest, _BASE), 2)

    def test_archive_last_folder_for_rop(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            # simulate a Houdini render straight into the LAST folder
            last = dest / f"{_BASE}_USD_LAST"
            last.mkdir(parents=True)
            (last / f"{_BASE}_LAST.usd").write_text("old")
            ver = archive_last_folder(dest, _BASE, "USD", ".usd")
            self.assertEqual(ver, 1)
            self.assertTrue((dest / f"{_BASE}_USD_V001" / f"{_BASE}_v001.usd").exists())
            self.assertFalse(last.exists())  # renamed away, ready to be recreated
            # nothing to archive on a clean folder
            self.assertIsNone(archive_last_folder(dest, _BASE, "FBX", ".fbx"))


if __name__ == "__main__":
    unittest.main()
