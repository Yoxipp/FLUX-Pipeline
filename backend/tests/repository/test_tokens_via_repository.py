# test_tokens_via_repository.py - tokens.json routes through the repository (Phase 1a).
#
# End-to-end: save_tokens / load_tokens / add_token / remove_token go through the
# process repository (tokens collection = one tokens.json per project folder).
# Proves the reroute keeps the on-disk format (a dict), the default-merge, the
# write-success bool, and the public signatures.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.constants import JSON_TOKENS
from features.folder_manager import tokens as tk


class TokensViaRepositoryTests(unittest.TestCase):
    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            data = tk.build_default_tokens()
            data["NAME"]["HERO"] = "assets/chara/HERO"
            self.assertTrue(tk.save_tokens(project, data))
            loaded = tk.load_tokens(project)
            self.assertEqual(loaded["NAME"]["HERO"], "assets/chara/HERO")

    def test_load_missing_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            loaded = tk.load_tokens(Path(d))
            self.assertIn("CLASS", loaded)  # defaults merged in

    def test_on_disk_format_stays_a_dict(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            tk.save_tokens(project, tk.build_default_tokens())
            raw = json.loads((project / JSON_TOKENS).read_text(encoding="utf-8"))
            self.assertIsInstance(raw, dict)
            self.assertIn("CLASS", raw)

    def test_add_and_remove_token(self):
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            tk.save_tokens(project, tk.build_default_tokens())
            self.assertTrue(tk.add_token(project, "NAME", "PROP_A", "assets/props/A"))
            self.assertEqual(tk.load_tokens(project)["NAME"]["PROP_A"], "assets/props/A")
            self.assertTrue(tk.remove_token(project, "NAME", "PROP_A"))
            self.assertNotIn("PROP_A", tk.load_tokens(project)["NAME"])


if __name__ == "__main__":
    unittest.main()
