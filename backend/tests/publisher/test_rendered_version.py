# test_rendered_version.py - ADR 0017 for writers that render straight to disk (U3b):
# reserve vNNN, the writer fills it, LAST is derived; failed renders are discarded.
# Houdini is faked: export_via_node writes the file the ROP would have cooked.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dcc.houdini import houdini_export as hx
from features.folder_manager.tokens import build_default_tokens, save_tokens
from features.publisher.publish_core import resolve_publish_path
from features.publisher.publish_layout import (
    discard_rendered_version, finalize_rendered_version, last_version_label, reserve_version,
)

_BASE = "CHAR_RIG_CECILE_ALL"


def _project(tmp: str) -> Path:
    proj = Path(tmp)
    save_tokens(proj, build_default_tokens())
    return proj


def _fake_cook(frames=(1001, 1002)):
    """export_via_node stand-in: write what the ROP would write at output_path."""
    def cook(_node, ext, output_path, *_args, **_kwargs):
        out = Path(output_path)
        if "$F4" in out.name:
            for f in frames:
                (out.parent / out.name.replace("$F4", f"{f:04d}")).write_text(f"frame {f}")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(f"cook {out.name}")
        return {"ok": True, "result": {"rop": "/out/rop1"}}
    return cook


class ReserveAndFinalize(unittest.TestCase):
    def test_reserve_skips_taken_slots_and_archives_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / f"{_BASE}_LAST.abc").write_text("legacy")
            (dest / f"{_BASE}_v002").mkdir()           # empty folder of a failed cook
            ver = reserve_version(dest, _BASE, ".abc")
            self.assertEqual((dest / f"{_BASE}_v001.abc").read_text(), "legacy")
            self.assertEqual(ver, 3)

    def test_finalize_missing_version_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            self.assertIsNone(finalize_rendered_version(dest, _BASE, ".abc", 1))
            (dest / f"{_BASE}_v001").mkdir()
            self.assertIsNone(finalize_rendered_version(dest, _BASE, ".exr", 1, is_sequence=True))

    def test_discard(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "null"
            dest.mkdir()
            (dest / f"{_BASE}_v001.abc").write_text("partial")
            (dest / "keep.txt").write_text("other publish")
            seq = dest / f"{_BASE}_v002"
            seq.mkdir()
            (seq / f"{_BASE}_v002.0001.exr").write_text("x")
            discard_rendered_version(dest, _BASE, ".abc", 1)
            discard_rendered_version(dest, _BASE, ".exr", 2, is_sequence=True)
            self.assertFalse((dest / f"{_BASE}_v001.abc").exists())
            self.assertFalse(seq.exists())
            self.assertTrue(dest.is_dir())  # not empty: kept

    def test_discard_of_a_first_publish_removes_the_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "shading" / "null"
            ver = reserve_version(dest, _BASE, ".usda")
            (dest / f"{_BASE}_v{ver:03d}").mkdir()
            discard_rendered_version(dest, _BASE, ".usda", ver, is_sequence=True)
            self.assertFalse(dest.exists())
            self.assertTrue(dest.parent.is_dir())  # the task folder stays


class HoudiniRop(unittest.TestCase):
    def _publish(self, proj, ext, **kw):
        with mock.patch.object(hx, "export_via_node", side_effect=_fake_cook()), \
                mock.patch("flux_actions.switch.portable_paths_enabled", return_value=False), \
                mock.patch("features.activity.activity_writer.log_publish"):
            return hx.publish_houdini_rop(proj, _BASE, ext, rop_node_path="/out/rop1",
                                          user="adam", **kw)

    def test_single_file_writes_version_then_copy_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _project(tmp)
            dest = resolve_publish_path(proj, f"{_BASE}_LAST.abc")
            r1 = self._publish(proj, ".abc")
            r2 = self._publish(proj, ".abc")
            self.assertTrue(r2["ok"], r2)
            self.assertEqual((r1["version"], r2["version"]), (1, 2))
            self.assertEqual(Path(r2["path"]), dest / f"{_BASE}_LAST.abc")
            self.assertEqual((dest / f"{_BASE}_v001.abc").read_text(), f"cook {_BASE}_v001.abc")
            self.assertEqual((dest / f"{_BASE}_LAST.abc").read_text(), f"cook {_BASE}_v002.abc")
            self.assertEqual(last_version_label(dest, _BASE, ".abc"), "v002")
            self.assertFalse((dest / f"{_BASE}_v003.abc").exists())

    def test_bgeo_sc_sequence_gets_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _project(tmp)
            dest = resolve_publish_path(proj, f"{_BASE}_LAST.bgeo.sc")
            self._publish(proj, ".bgeo.sc", is_sequence=True, frame_range=(1001, 1002, 1))
            r2 = self._publish(proj, ".bgeo.sc", is_sequence=True, frame_range=(1001, 1002, 1))
            self.assertEqual(r2["version"], 2)
            seq = dest / f"{_BASE}_v002"
            self.assertTrue((seq / f"{_BASE}_v002.1001.bgeo.sc").is_file())
            link = json.loads((dest / f"{_BASE}_LAST.bgeo.sc.link").read_text())
            self.assertEqual(link["target"], f"{_BASE}_v002/")
            self.assertEqual(link["pattern"], f"{_BASE}_v002.$F4.bgeo.sc")
            self.assertEqual(link["version"], "v002")

    def test_failed_cook_leaves_no_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _project(tmp)
            dest = resolve_publish_path(proj, f"{_BASE}_LAST.abc")

            def failing(_node, _ext, output_path, *_a, **_k):
                Path(output_path).write_text("partial")
                return {"ok": False, "error": "cook failed"}

            with mock.patch.object(hx, "export_via_node", side_effect=failing):
                res = hx.publish_houdini_rop(proj, _BASE, ".abc", rop_node_path="/out/rop1")
            self.assertFalse(res["ok"])
            # First publish failed: no version, and no empty instance folder left.
            self.assertFalse(dest.exists() and any(p.suffix == ".abc" for p in dest.iterdir()))

    def test_scene_publish_saves_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _project(tmp)
            dest = resolve_publish_path(proj, f"{_BASE}_LAST.hip")

            def save(path, _ext):
                Path(path).write_text("hip")
                return {"ok": True, "path": str(path)}

            with mock.patch.object(hx, "export_scene", side_effect=save), \
                    mock.patch("features.activity.activity_writer.log_publish"):
                res = hx.publish_houdini_rop(proj, _BASE, ".hip", user="adam")
            self.assertTrue(res["ok"], res)
            self.assertTrue((dest / f"{_BASE}_v001.hip").is_file())
            self.assertEqual(Path(res["path"]), dest / f"{_BASE}_LAST.hip")


if __name__ == "__main__":
    unittest.main()
