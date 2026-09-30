# test_zbrush_save_increment.py - the ZBrush "Save +1" button names the next version.
# The plugin binds its socket at import, so the pure function is loaded from its source.

from __future__ import annotations

import ast
import os
import re
import unittest
from pathlib import Path

_PLUGIN = Path(__file__).resolve().parents[2] / "dcc" / "zbrush" / "zbrush_bridge_plugin.py"


def _load_next_increment_path():
    tree = ast.parse(_PLUGIN.read_text(encoding="utf-8"))
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "next_increment_path")
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_VERSION_RE" for t in n.targets))]
    ns = {"re": re, "os": os}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(_PLUGIN), "exec"), ns)
    return ns["next_increment_path"]


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


if __name__ == "__main__":
    unittest.main()
