# test_zbrush_save_increment.py - the ZBrush "Save +1" button names the next version.
# The plugin binds its socket at import, so the pure function is loaded from its source.

from __future__ import annotations

import ast
import os
import re
import unittest
from pathlib import Path

_PLUGIN = Path(__file__).resolve().parents[2] / "dcc" / "zbrush" / "zbrush_bridge_plugin.py"


def _load(name: str):
    tree = ast.parse(_PLUGIN.read_text(encoding="utf-8"))
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name in ("next_increment_path", "autosave_ztl_path"))
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("_VERSION_RE", "_AUTOSAVE_FALLBACK_DIR")
                                                  for t in n.targets))]
    ns = {"re": re, "os": os}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(_PLUGIN), "exec"), ns)
    return ns[name]


def _load_next_increment_path():
    return _load("next_increment_path")


class SaveIncrement(unittest.TestCase):
    def setUp(self):
        self.nxt = _load_next_increment_path()

    def test_keeps_padding(self):
        self.assertEqual(self.nxt("D:/p/Dragon_v004.zpr"), "D:/p/Dragon_v005.zpr")
        self.assertEqual(self.nxt("D:/p/Dragon_v099.zpr"), "D:/p/Dragon_v100.zpr")
        self.assertEqual(self.nxt("D:/p/Dragon_v999.zpr"), "D:/p/Dragon_v1000.zpr")

    def test_no_version_starts_at_v001(self):
        self.assertEqual(self.nxt("D:/p/Dragon.zpr"), "D:/p/Dragon_v001.zpr")

    def test_other_extension_becomes_a_project(self):
        self.assertEqual(self.nxt("D:/p/Dragon_v002.ZTL"), "D:/p/Dragon_v003.zpr")


class AutosaveZtl(unittest.TestCase):
    def setUp(self):
        self.path = _load("autosave_ztl_path")

    def test_next_to_the_project(self):
        d = str(Path(__file__).parent).replace("\\", "/")
        self.assertEqual(self.path(f"{d}/Dragon_v004.zpr", "Dragon"), f"{d}/Dragon_v004_autosave.ztl")

    def test_fallback_folder_without_project(self):
        self.assertEqual(self.path("", "Tool/My Dragon", "C:/x"), "C:/x/My_Dragon_autosave.ztl")
        self.assertEqual(self.path("D:/missing/dir/a.zpr", "", "C:/x"), "C:/x/tool_autosave.ztl")


if __name__ == "__main__":
    unittest.main()
