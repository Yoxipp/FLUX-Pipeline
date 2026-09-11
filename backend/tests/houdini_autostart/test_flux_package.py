# test_flux_package.py - the Houdini $FLUX package writer (priority n3, phase F1).
#
# Offline: every case passes an explicit prefs dir + root, so nothing depends on
# config.json / get_flux_root or on Houdini being installed. The writer targets a
# separate package file on purpose; these tests also assert houdini.env is never
# touched (it is the file whose PYTHONNOUSERSITE line crashed Houdini 22.0).

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dcc.houdini import autostart


class FluxPackageTextTests(unittest.TestCase):
    def test_sets_flux_env_var_with_posix_root(self):
        text = autostart._flux_package_text(Path(r"D:\Flux"))
        data = json.loads(text)
        self.assertEqual(data, {"env": [{"FLUX": "D:/Flux"}]})

    def test_output_is_valid_json(self):
        # Must parse cleanly - Houdini rejects a malformed package file.
        text = autostart._flux_package_text(Path("/mnt/pipe/Flux"))
        self.assertEqual(json.loads(text)["env"][0]["FLUX"], "/mnt/pipe/Flux")


class WriteFluxPackageTests(unittest.TestCase):
    def test_writes_package_under_packages_dir(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d)
            root = Path("D:/Flux")
            self.assertTrue(autostart._write_flux_package(prefs, root))
            pkg = prefs / "packages" / "flux.json"
            self.assertTrue(pkg.exists())
            self.assertEqual(json.loads(pkg.read_text(encoding="utf-8")),
                             {"env": [{"FLUX": "D:/Flux"}]})

    def test_none_root_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d)
            self.assertFalse(autostart._write_flux_package(prefs, None))
            self.assertFalse((prefs / "packages" / "flux.json").exists())

    def test_idempotent_no_rewrite_when_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d)
            root = Path("D:/Flux")
            self.assertTrue(autostart._write_flux_package(prefs, root))
            pkg = prefs / "packages" / "flux.json"
            first_mtime = pkg.stat().st_mtime_ns
            # Second call with the same root must not rewrite the file.
            self.assertTrue(autostart._write_flux_package(prefs, root))
            self.assertEqual(pkg.stat().st_mtime_ns, first_mtime)

    def test_root_change_rewrites_content(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d)
            autostart._write_flux_package(prefs, Path("D:/Flux"))
            autostart._write_flux_package(prefs, Path("E:/Pipeline/Flux"))
            pkg = prefs / "packages" / "flux.json"
            self.assertEqual(json.loads(pkg.read_text(encoding="utf-8")),
                             {"env": [{"FLUX": "E:/Pipeline/Flux"}]})

    def test_never_touches_houdini_env(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d)
            autostart._write_flux_package(prefs, Path("D:/Flux"))
            self.assertFalse((prefs / "houdini.env").exists())


class RemoveFluxPackageTests(unittest.TestCase):
    def test_removes_existing_package(self):
        with tempfile.TemporaryDirectory() as d:
            prefs = Path(d)
            autostart._write_flux_package(prefs, Path("D:/Flux"))
            pkg = prefs / "packages" / "flux.json"
            self.assertTrue(pkg.exists())
            autostart._remove_flux_package(prefs)
            self.assertFalse(pkg.exists())

    def test_absent_package_is_no_error(self):
        with tempfile.TemporaryDirectory() as d:
            # No package written; removal must be a silent no-op.
            autostart._remove_flux_package(Path(d))


if __name__ == "__main__":
    unittest.main()
