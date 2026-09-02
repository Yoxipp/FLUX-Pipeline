# test_importer_resolve_layout.py — end-to-end token->folder->import over the
# nested per-version / per-format publish layout, with a real tokens.json project.

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


class ImporterResolveNestedLayout(unittest.TestCase):
    def setUp(self):
        ir._BCACHE.clear()  # backend TTL cache would otherwise hide fresh disk state

    def test_token_resolves_to_expected_folder(self):
        proj = _project()
        dest = resolve_publish_path(proj, f"{_BASE}_LAST.usd")
        self.assertEqual(dest, proj.joinpath(*_EXPECT_REL))
        # and it matches what the importer resolves internally
        self.assertEqual(ir._resolve_folder(proj, _CLASS, _TYPE, _NAME, _INST), dest)

    def test_first_publish_import_finds_nested_last(self):
        proj = _project()
        dest = _publish(proj, 1)
        ir._BCACHE.clear()
        self.assertEqual(ir.get_available_iters(proj, _CLASS, _TYPE, _NAME, _INST), ["LAST"])
        res = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "LAST")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["ext"], ".usd")
        self.assertEqual(
            Path(res["path"]),
            dest / "USD" / f"{_BASE}_USD_LAST" / f"{_BASE}_LAST.usd",
        )
        self.assertEqual(Path(res["path"]).read_text(), "v1")

    def test_second_publish_exposes_last_and_v001(self):
        proj = _project()
        dest = _publish(proj, 2)
        ir._BCACHE.clear()
        self.assertEqual(
            ir.get_available_iters(proj, _CLASS, _TYPE, _NAME, _INST),
            ["LAST", "v001"],
        )
        # LAST -> newest bytes
        last = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "LAST")
        self.assertTrue(last["ok"], last)
        self.assertEqual(Path(last["path"]).read_text(), "v2")
        # v001 -> archived nested version folder
        v1 = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "v001")
        self.assertTrue(v1["ok"], v1)
        self.assertEqual(
            Path(v1["path"]),
            dest / "USD" / f"{_BASE}_USD_V001" / f"{_BASE}_v001.usd",
        )
        self.assertEqual(Path(v1["path"]).read_text(), "v1")

    def test_missing_iter_reports_not_found(self):
        proj = _project()
        _publish(proj, 1)
        ir._BCACHE.clear()
        res = ir.resolve_import_path(proj, _CLASS, _TYPE, _NAME, _INST, "v999")
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()
