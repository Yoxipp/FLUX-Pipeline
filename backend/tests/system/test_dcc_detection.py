# test_dcc_detection.py - DCC exe detection (retake F2): registry (Maya, Photoshop),
# every Program Files root, newest version first, missing custom path warned once.
# The registry is mocked and installs are fake files in a temp dir.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import constants
from features.launcher import launcher_core as lc


def _touch(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return str(path)


class VersionKey(unittest.TestCase):
    def test_numeric_sort(self):
        paths = [
            r"C:\PF\Adobe\Adobe Photoshop CC 2019\Photoshop.exe",
            r"C:\PF\Adobe\Adobe Photoshop 2025\Photoshop.exe",
            r"C:\PF\Adobe\Adobe Photoshop 2023\Photoshop.exe",
        ]
        best = sorted(paths, key=lc._version_key, reverse=True)[0]
        self.assertIn("2025", best)
        self.assertGreater(lc._version_key(r"C:\H\Houdini 20.5.332\bin\houdini.exe"),
                           lc._version_key(r"C:\H\Houdini 20.0.751\bin\houdini.exe"))
        self.assertGreater(lc._version_key(r"C:\Maya2025\bin\maya.exe"),
                           lc._version_key(r"C:\Maya2024\bin\maya.exe"))


class ProgramFilesRoots(unittest.TestCase):
    def test_all_roots_deduplicated(self):
        env = {"PROGRAMFILES": r"C:\Program Files (x86)", "PROGRAMW6432": r"C:\Program Files",
               "PROGRAMFILES(X86)": r"C:\Program Files (x86)"}
        with mock.patch.dict(os.environ, env):
            roots = constants._program_files_roots()
        self.assertEqual(roots, [r"C:\Program Files", r"C:\Program Files (x86)"])

    def test_maya_pattern_on_every_root(self):
        env = {"PROGRAMFILES": r"D:\PF86", "PROGRAMW6432": r"D:\PF", "PROGRAMFILES(X86)": r"D:\PF86"}
        with mock.patch.dict(os.environ, env):
            groups = constants._build_dcc_pattern_groups()
        self.assertEqual(groups["Maya"], [[r"D:\PF\Autodesk\Maya*\bin\maya.exe",
                                           r"D:\PF86\Autodesk\Maya*\bin\maya.exe"]])


class Candidates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        lc._warned_missing.clear()

    def tearDown(self):
        self._tmp.cleanup()

    def _groups(self, maya=None, ps=None, sp=None):
        return {"Maya": maya or [[]], "Photoshop": ps or [[]], "SubstanceP": sp or [[]]}

    def test_maya_glob_newest_first(self):
        old = _touch(self.root / "PF" / "Autodesk" / "Maya2024" / "bin" / "maya.exe")
        new = _touch(self.root / "PF" / "Autodesk" / "Maya2025" / "bin" / "maya.exe")
        pattern = str(self.root / "PF" / "Autodesk" / "Maya*" / "bin" / "maya.exe")
        with mock.patch.object(lc, "DCC_EXE_PATTERN_GROUPS", self._groups(maya=[[pattern]])), \
             mock.patch.object(lc, "_registry_candidates", return_value=[]):
            self.assertEqual(lc.list_dcc_candidates("maya"), [new, old])

    def test_maya_from_registry_outside_program_files(self):
        loc = self.root / "Apps" / "Maya2025"
        exe = _touch(loc / "bin" / "maya.exe")
        subkeys = {lc._MAYA_KEY: ["2025", "2024"]}
        values = {(rf"{lc._MAYA_KEY}\2025\Setup\InstallPath", "MAYA_INSTALL_LOCATION"): str(loc) + "\\",
                  (rf"{lc._MAYA_KEY}\2024\Setup\InstallPath", "MAYA_INSTALL_LOCATION"): str(self.root / "gone")}
        with mock.patch.object(lc, "DCC_EXE_PATTERN_GROUPS", self._groups()), \
             mock.patch.object(lc, "_reg_subkeys", side_effect=lambda k: subkeys.get(k, [])), \
             mock.patch.object(lc, "_reg_value", side_effect=lambda k, n="": values.get((k, n))):
            self.assertEqual(lc.list_dcc_candidates("maya"), [os.path.normpath(exe)])

    def test_photoshop_registry_and_app_paths(self):
        cc = _touch(self.root / "Adobe Photoshop CC 2019" / "Photoshop.exe")
        new = _touch(self.root / "Adobe Photoshop 2025" / "Photoshop.exe")
        subkeys = {lc._PHOTOSHOP_KEY: ["120.0"]}
        values = {(rf"{lc._PHOTOSHOP_KEY}\120.0", "ApplicationPath"): str(Path(cc).parent),
                  (lc._APP_PATHS_PHOTOSHOP, ""): f'"{new}"'}
        with mock.patch.object(lc, "DCC_EXE_PATTERN_GROUPS", self._groups()), \
             mock.patch.object(lc, "_reg_subkeys", side_effect=lambda k: subkeys.get(k, [])), \
             mock.patch.object(lc, "_reg_value", side_effect=lambda k, n="": values.get((k, n))):
            self.assertEqual(lc.list_dcc_candidates("photoshop"), [new, cc])

    def test_priority_group_beats_newer_legacy_install(self):
        adobe = _touch(self.root / "Adobe" / "Adobe Substance 3D Painter" / "Adobe Substance 3D Painter.exe")
        legacy = _touch(self.root / "Allegorithmic" / "Substance Painter 2021" / "Substance Painter.exe")
        groups = self._groups(sp=[[str(self.root / "Adobe" / "Adobe Substance 3D Painter*" / "Adobe Substance 3D Painter.exe")],
                                  [str(self.root / "Allegorithmic" / "Substance Painter*" / "Substance Painter.exe")]])
        with mock.patch.object(lc, "DCC_EXE_PATTERN_GROUPS", groups), \
             mock.patch.object(lc, "_registry_candidates", return_value=[]):
            self.assertEqual(lc.list_dcc_candidates("substance_painter"), [adobe, legacy])

    def test_missing_custom_path_warns_once_and_falls_back(self):
        exe = _touch(self.root / "Maya2025" / "bin" / "maya.exe")
        missing = str(self.root / "Maya2023" / "bin" / "maya.exe")
        with mock.patch.object(lc.config, "get_dcc_exe", side_effect=lambda k: missing if k == "maya" else None), \
             mock.patch.object(lc, "list_dcc_candidates", side_effect=lambda k: [exe] if k == "maya" else []), \
             self.assertLogs(lc.log.name, level="WARNING") as logs:
            self.assertEqual(lc.get_installed_dccs(), {"maya": exe})
            lc.get_installed_dccs()
        self.assertEqual(sum(missing in line for line in logs.output), 1)

    def test_existing_custom_path_wins(self):
        custom = _touch(self.root / "custom" / "maya.exe")
        with mock.patch.object(lc.config, "get_dcc_exe", side_effect=lambda k: custom if k == "maya" else None), \
             mock.patch.object(lc, "list_dcc_candidates", return_value=["other.exe"]):
            self.assertEqual(lc.get_installed_dccs()["maya"], custom)

    def test_registry_helpers_are_safe_without_winreg(self):
        with mock.patch.object(lc, "_winreg", None):
            self.assertEqual(lc._reg_subkeys(lc._MAYA_KEY), [])
            self.assertIsNone(lc._reg_value(lc._APP_PATHS_PHOTOSHOP))
            self.assertEqual(lc._registry_candidates("maya"), [])


if __name__ == "__main__":
    unittest.main()
