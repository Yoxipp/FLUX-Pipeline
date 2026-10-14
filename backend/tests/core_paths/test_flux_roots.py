"""Known FLUX directories: several registered, exactly one active."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import paths


class FluxRootsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        cfg = Path(self._tmp.name) / "config.json"
        self._patch = mock.patch("core.paths.get_config_json_path", return_value=cfg)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_legacy_config_lists_the_active_root(self):
        paths._write_config_json({"workspace": "D:/FLUX_A"})
        self.assertEqual(paths.get_flux_roots(), [str(Path("D:/FLUX_A"))])

    def test_add_does_not_activate_and_dedupes(self):
        paths.set_flux_root("D:/FLUX_A")
        paths.add_flux_root("D:/FLUX_B")
        paths.add_flux_root("d:/flux_b/")
        self.assertEqual(paths.get_flux_roots(), [str(Path("D:/FLUX_A")), str(Path("D:/FLUX_B"))])
        self.assertEqual(paths.get_flux_root(), Path("D:/FLUX_A"))

    def test_activating_switches_the_single_active_root(self):
        paths.set_flux_root("D:/FLUX_A")
        paths.set_flux_root("D:/FLUX_B")
        self.assertEqual(paths.get_flux_root(), Path("D:/FLUX_B"))
        self.assertEqual(len(paths.get_flux_roots()), 2)

    def test_remove_forgets_inactive_and_refuses_active(self):
        paths.set_flux_root("D:/FLUX_A")
        paths.add_flux_root("D:/FLUX_B")
        paths.remove_flux_root("D:/FLUX_B")
        self.assertEqual(paths.get_flux_roots(), [str(Path("D:/FLUX_A"))])
        with self.assertRaises(ValueError):
            paths.remove_flux_root("d:/flux_a")


if __name__ == "__main__":
    unittest.main()
