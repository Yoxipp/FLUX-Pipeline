# test_importer_resolve_layout.py — end-to-end token->folder->import over the
# per-format single-file publish layout (active <ext>/<base>_LAST.ext + archived
# <ext>/<base>_vNNN.ext), with a real tokens.json project.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import features.importer.importer_resolve as ir
from features.folder_manager.tokens import build_default_tokens, save_tokens
from features.publisher.publish_core import resolve_publish_path
from features.publisher.publish_layout import publish_into_layout

# Uses only default tokens: CLASS CHAR -> assets/chara, TYPE RIG -> rig, and the
# NAME fallback (CLASS_path/NAME) -> assets/chara/CECILE. Instance "all".
_CLASS, _TYPE, _NAME, _INST = "CHAR", "RIG", "CECILE", "all"
_BASE = "CHAR_RIG_CECILE_ALL"                      # get_base_name of the token combo (uppercased)
_EXPECT_REL = ("assets", "chara", "CECILE", "rig", "all")


def _project() -> Path:
    d = Path(tempfile.mkdtemp())
    save_tokens(d, build_default_tokens())
    return d


def _publish(project: Path, n: int) -> Path:
    """Publish *n* successive USD versions; return the resolved publish folder."""
    dest = resolve_publish_path(project, f"{_BASE}_LAST.usd")
    src_dir = project / "_src"
    src_dir.mkdir(exist_ok=True)
    for i in range(1, n + 1):
        src = src_dir / f"v{i}.usd"
        src.write_text(f"v{i}")
        publish_into_layout(src, dest, _BASE)
    return dest


class ImporterResolveFlatLayout(unittest.TestCase):
    def setUp(self):
        ir._BCACHE.clear()  # backend TTL cache would otherwise hide fresh disk state

    def test_token_resolves_to_expected_folder(self):
        proj = _project()
        dest = resolve_publish_path(proj, f"{_BASE}_LAST.usd")
        self.assertEqual(dest, proj.joinpath(*_EXPECT_REL))
        # and it matches what the importer resolves internally
        self.assertEqual(ir._resolve_folder(proj, _CLASS, _TYPE, _NAME, _INST), dest)

    def test_first_publish_import_finds_flat_last(self):
        proj = _project()
        dest = _publish(proj, 1)
        ir._BCACHE.clear()
        self.assertEqual(ir.get_available_iters(proj, _CLASS, _TYPE, _NAME, _INST), ["LAST"])
        res = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "LAST")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["ext"], ".usd")
        self.assertEqual(Path(res["path"]), dest / f"{_BASE}_LAST.usd")
        self.assertEqual(Path(res["path"]).read_text(), "v1")

    def test_second_publish_exposes_last_and_v001(self):
        proj = _project()
        dest = _publish(proj, 2)
        ir._BCACHE.clear()
        self.assertEqual(
            ir.get_available_iters(proj, _CLASS, _TYPE, _NAME, _INST),
            ["LAST", "v001"],
        )
        # LAST -> newest bytes at the stable flat path
        last = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "LAST")
        self.assertTrue(last["ok"], last)
        self.assertEqual(Path(last["path"]), dest / f"{_BASE}_LAST.usd")
        self.assertEqual(Path(last["path"]).read_text(), "v2")
        # v001 -> archived flat file in the shared folder, beside LAST
        v1 = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "v001")
        self.assertTrue(v1["ok"], v1)
        self.assertEqual(Path(v1["path"]), dest / f"{_BASE}_v001.usd")
        self.assertEqual(Path(v1["path"]).read_text(), "v1")

    def test_missing_iter_reports_not_found(self):
        proj = _project()
        _publish(proj, 1)
        ir._BCACHE.clear()
        res = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "v999")
        self.assertFalse(res["ok"])


class ImporterResolveSequenceLayout(unittest.TestCase):
    """Frame-sequence import: <base>_vNNN/<base>_vNNN.<frame>.<ext> (Nuke/Houdini)."""

    def setUp(self):
        ir._BCACHE.clear()

    def _publish_sequence(self, project: Path, ver: int, frames: range) -> None:
        """Lay a Nuke-style EXR version folder <base>_vNNN/<base>_vNNN.<frame>.exr."""
        dest = resolve_publish_path(project, f"{_BASE}_LAST.exr")
        seq_dir = dest / f"{_BASE}_v{ver:03d}"
        seq_dir.mkdir(parents=True, exist_ok=True)
        for f in frames:
            (seq_dir / f"{_BASE}_v{ver:03d}.{f:04d}.exr").write_text("x")

    def test_last_maps_to_newest_version_sequence(self):
        proj = _project()
        # Two published sequence versions; LAST must resolve the newest (v002).
        self._publish_sequence(proj, 1, range(1001, 1004))
        self._publish_sequence(proj, 2, range(1001, 1006))
        ir._BCACHE.clear()
        res = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "LAST")
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["is_sequence"])
        self.assertEqual((res["first"], res["last"]), (1001, 1005))
        self.assertTrue(res["frame_pattern"].endswith("_v002.%04d.exr"))
        # path stays a real first-frame file for callers that only read `path`.
        self.assertTrue(Path(res["path"]).exists())

    def test_explicit_version_sequence(self):
        proj = _project()
        self._publish_sequence(proj, 1, range(1001, 1004))
        self._publish_sequence(proj, 2, range(1001, 1006))
        ir._BCACHE.clear()
        res = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "v001")
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["first"], res["last"]), (1001, 1003))
        self.assertTrue(res["frame_pattern"].endswith("_v001.%04d.exr"))


if __name__ == "__main__":
    unittest.main()
