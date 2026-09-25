# test_publish_layout.py — single-folder publish layout: every format's
# active-in-place LAST + flat vNNN archives share one <dest>/ folder.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from features.publisher.publish_layout import (
    archive_flat_last, find_last_file, find_version_file, format_suffix,
    highest_flat_version, highest_version_any, last_folder, parse_layout_folder,
    published_files, publish_into_layout, versions_dir,
)
from features.publisher.version_resolver import get_last_file, get_next_version

_BASE = "CHAR_RIG_CECILE_ALL_BODY_A"


def _src(dir_: Path, name: str, text: str = "x") -> Path:
    p = dir_ / name
    p.write_text(text)
    return p


class FlatPublishLayout(unittest.TestCase):
    def test_format_suffix(self):
        self.assertEqual(format_suffix(".usd"), "USD")
        self.assertEqual(format_suffix(".fbx"), "FBX")
        self.assertEqual(format_suffix("usd"), "USD")

    def test_first_publish_writes_version_then_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = _src(tmp, "export.abc", "v1")
            dest = tmp / "all"
            path, ver = publish_into_layout(src, dest, _BASE)
            self.assertEqual(ver, 1)
            # ADR 0017: v001 exists as soon as it is published, LAST is a copy of it
            self.assertEqual((dest / f"{_BASE}_v001.abc").read_text(), "v1")
            self.assertEqual(path, dest / f"{_BASE}_LAST.abc")
            self.assertEqual(path.read_text(), "v1")
            self.assertTrue((dest / f"{_BASE}_LAST.abc.flux.json").is_file())
            self.assertEqual(highest_flat_version(dest, _BASE), 1)
            self.assertFalse(versions_dir(dest).exists())

    def test_second_publish_never_rewrites_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            _p1, v1 = publish_into_layout(_src(tmp, "a.abc", "v1"), dest, _BASE)
            p2, v2 = publish_into_layout(_src(tmp, "b.abc", "v2"), dest, _BASE)
            self.assertEqual((v1, v2), (1, 2))
            self.assertEqual((dest / f"{_BASE}_v001.abc").read_text(), "v1")
            self.assertEqual((dest / f"{_BASE}_v002.abc").read_text(), "v2")
            self.assertEqual(p2, dest / f"{_BASE}_LAST.abc")
            self.assertEqual(p2.read_text(), "v2")
            self.assertFalse((dest / f"{_BASE}_v003.abc").exists())

    def test_last_path_is_stable_across_publishes(self):
        # The whole point of the flat layout: the active path never changes.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            p1, _ = publish_into_layout(_src(tmp, "a.abc", "1"), dest, _BASE)
            p2, _ = publish_into_layout(_src(tmp, "b.abc", "2"), dest, _BASE)
            p3, _ = publish_into_layout(_src(tmp, "c.abc", "3"), dest, _BASE)
            self.assertEqual(p1, p2)
            self.assertEqual(p2, p3)
            self.assertEqual(p3.read_text(), "3")

    def test_third_publish_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            publish_into_layout(_src(tmp, "a.abc", "1"), dest, _BASE)
            publish_into_layout(_src(tmp, "b.abc", "2"), dest, _BASE)
            _, v3 = publish_into_layout(_src(tmp, "c.abc", "3"), dest, _BASE)
            self.assertEqual(v3, 3)
            self.assertEqual(highest_flat_version(dest, _BASE), 3)

    def test_formats_are_independent_lineages(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            publish_into_layout(_src(tmp, "a.abc", "u1"), dest, _BASE)
            _, av2 = publish_into_layout(_src(tmp, "b.abc", "u2"), dest, _BASE)
            _, fv1 = publish_into_layout(_src(tmp, "c.fbx", "f1"), dest, _BASE)
            self.assertEqual(av2, 2)
            self.assertEqual(fv1, 1)  # FBX starts its own line at v001
            self.assertTrue((dest / f"{_BASE}_LAST.abc").exists())
            self.assertTrue((dest / f"{_BASE}_LAST.fbx").exists())
            self.assertFalse((dest / f"{_BASE}_v002.fbx").exists())
            self.assertEqual(highest_flat_version(dest, _BASE, ".fbx"), 1)


class LayoutReaders(unittest.TestCase):
    def test_parse_layout_folder(self):
        # nested parser is kept for backward-compat reads of existing data
        self.assertEqual(parse_layout_folder(f"{_BASE}_USD_LAST"), (_BASE, "USD", "LAST"))
        self.assertEqual(parse_layout_folder(f"{_BASE}_FBX_V002"), (_BASE, "FBX", "v002"))
        self.assertIsNone(parse_layout_folder(f"{_BASE}_v001"))
        self.assertIsNone(parse_layout_folder("not_a_layout"))

    def test_get_last_and_find_version_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            publish_into_layout(_src(tmp, "a.abc", "1"), dest, _BASE)
            publish_into_layout(_src(tmp, "b.abc", "2"), dest, _BASE)
            self.assertEqual(get_last_file(dest, _BASE).read_text(), "2")
            self.assertEqual(find_version_file(dest, _BASE, "v001").read_text(), "1")
            self.assertIsNone(find_version_file(dest, _BASE, "v999"))

    def test_published_files_includes_versions_and_ignores_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            dest.mkdir()
            # a Houdini-style sequence folder that must be ignored by descent
            seq = dest / f"{_BASE}_v001"
            seq.mkdir()
            (seq / f"{_BASE}_v001.0001.exr").write_text("frame")
            publish_into_layout(_src(tmp, "a.usd", "1"), dest, _BASE)
            publish_into_layout(_src(tmp, "b.abc", "2"), dest, _BASE)
            names = {p.name for p in published_files(dest, _BASE)}
            self.assertIn(f"{_BASE}_LAST.usd", names)          # active
            self.assertIn(f"{_BASE}_v001.usd", names)          # version
            self.assertNotIn(f"{_BASE}_LAST.abc.flux.json", names)  # sidecar hidden
            self.assertNotIn(f"{_BASE}_v001.0001.exr", names)  # sequence not slurped

    def test_get_next_version_counts_flat(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            publish_into_layout(_src(tmp, "a.usd", "1"), dest, _BASE)
            publish_into_layout(_src(tmp, "b.usd", "2"), dest, _BASE)
            self.assertEqual(highest_version_any(dest, _BASE), 2)
            self.assertEqual(get_next_version(dest, _BASE), 3)

    def test_archive_flat_last_keeps_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            active = dest / f"{_BASE}_LAST.usd"
            active.parent.mkdir(parents=True)
            active.write_text("old")
            ver = archive_flat_last(dest, _BASE, ".usd")
            self.assertEqual(ver, 1)
            self.assertTrue((dest / f"{_BASE}_v001.usd").exists())
            self.assertTrue(active.exists())            # copy, not move — LAST stays intact
            self.assertEqual(active.read_text(), "old")
            # nothing to archive when there is no active LAST
            self.assertIsNone(archive_flat_last(dest, _BASE, ".fbx"))

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

    def test_readers_backcompat_nested_layout(self):
        # Existing assets published under the OLD nested per-format layout must still
        # resolve (no migration): <dest>/<FMT>/<base>_<FMT>_{LAST,Vnnn}/<base>_{LAST,vnnn}.ext
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "all"
            nlast = last_folder(dest, _BASE, "USD")
            nlast.mkdir(parents=True)
            (nlast / f"{_BASE}_LAST.usd").write_text("last")
            nv1 = dest / "USD" / f"{_BASE}_USD_V001"
            nv1.mkdir(parents=True)
            (nv1 / f"{_BASE}_v001.usd").write_text("one")
            self.assertEqual(get_last_file(dest, _BASE).read_text(), "last")
            self.assertEqual(find_version_file(dest, _BASE, "v001").read_text(), "one")
            self.assertEqual(highest_version_any(dest, _BASE), 1)


if __name__ == "__main__":
    unittest.main()
