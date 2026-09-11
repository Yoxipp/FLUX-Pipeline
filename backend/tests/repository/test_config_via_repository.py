# test_config_via_repository.py - config.json routes through the repository (Phase 1a).
#
# End-to-end: config.get / set / get_theme / set_theme go through the process
# repository (config collection = the single per-user prefs file). Proves the
# reroute keeps the on-disk format (a dict), the missing-file default ({}), the
# write path, and the public signatures. The prefs path is a process global, so we
# patch it at the one place the factory resolves it.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import config


def _patch_prefs(path: Path):
    return mock.patch("core.repository_factory.get_prefs_path", return_value=path)


class ConfigViaRepositoryTests(unittest.TestCase):
    def test_missing_file_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d) / "config.json"
            with _patch_prefs(prefs):
                # No file on disk yet: get() must not crash and returns defaults.
                self.assertIsNone(config.get("username"))
                self.assertEqual(config.get("theme", {}), {})

    def test_set_then_get_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d) / "config.json"
            with _patch_prefs(prefs):
                config.set("last_project", "SHOW_A")
                self.assertEqual(config.get("last_project"), "SHOW_A")

    def test_on_disk_format_stays_a_dict(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d) / "config.json"
            with _patch_prefs(prefs):
                config.set("username", "ADAM")
                raw = json.loads(prefs.read_text(encoding="utf-8"))
                self.assertIsInstance(raw, dict)
                self.assertEqual(raw["username"], "ADAM")

    def test_set_theme_and_get_theme(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d) / "config.json"
            with _patch_prefs(prefs):
                config.set_theme("#111111", "#222222", "#333333", "#444444")
                t = config.get_theme()
                self.assertEqual(t["bg"], "#111111")
                self.assertEqual(t["accent"], "#444444")

    def test_dcc_exe_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d) / "config.json"
            with _patch_prefs(prefs):
                config.set_dcc_exe("maya", "C:/maya/maya.exe")
                self.assertEqual(config.get_dcc_exe("maya"), "C:/maya/maya.exe")


if __name__ == "__main__":
    unittest.main()
