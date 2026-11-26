"""Rez-prep env overrides: unset = historical behaviour, set = values follow."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import constants, paths
from dcc import bridge_secret

_ROOT = Path(paths.__file__).resolve().parent.parent.parent
_VARS = [paths.USER_DIR_ENV, bridge_secret.ENV_FILE,
         *constants.DCC_PORT_ENV.values(), *constants.DCC_EXE_ENV.values()]


def _clean_env(**extra: str):
    env = {k: v for k, v in os.environ.items() if k not in _VARS}
    env.update(extra)
    return mock.patch.dict(os.environ, env, clear=True)


class UserDirTests(unittest.TestCase):
    def test_unset_dev_keeps_project_root(self):
        with _clean_env():
            self.assertEqual(paths.get_config_json_path(), _ROOT / "config.json")
            self.assertEqual(paths.get_prefs_path(), _ROOT / "config.json")

    def test_unset_frozen_keeps_appdata(self):
        with _clean_env(APPDATA="C:/AppData"), mock.patch.object(sys, "frozen", True, create=True):
            base = Path("C:/AppData") / "FluxPipeline"
            self.assertEqual(paths.get_config_json_path(), base / "config.json")
            self.assertEqual(paths.get_prefs_path(), base / "prefs.json")
            self.assertEqual(bridge_secret.secret_path(), base / "bridge_secret.txt")

    def test_blank_value_is_unset(self):
        with _clean_env(FLUX_USER_DIR="  "):
            self.assertEqual(paths.get_config_json_path(), _ROOT / "config.json")

    def test_set_moves_every_user_file_in_both_modes(self):
        base = Path("D:/flux_user")
        for frozen in (False, True):
            with _clean_env(FLUX_USER_DIR=str(base)), \
                    mock.patch.object(sys, "frozen", frozen, create=True):
                self.assertEqual(paths.get_config_json_path(), base / "config.json")
                self.assertEqual(paths.get_prefs_path(), base / "prefs.json")
                self.assertEqual(bridge_secret.secret_path(), base / "bridge_secret.txt")


class PortEnvTests(unittest.TestCase):
    DEFAULTS = {"Maya": (7001, 8), "SubstanceP": (7030, 8), "SubstanceD": (7040, 8),
                "Mari": (7070, 8), "ZBrush": (9876, 8)}

    def test_unset_keeps_ranges(self):
        with _clean_env():
            self.assertEqual(constants._apply_port_env(self.DEFAULTS), self.DEFAULTS)

    def test_set_moves_the_base(self):
        with _clean_env(FLUX_MAYA_PORT="7101", FLUX_MARI_PORT="7170"):
            out = constants._apply_port_env(self.DEFAULTS)
        self.assertEqual(out["Maya"], (7101, 8))
        self.assertEqual(out["Mari"], (7170, 8))
        self.assertEqual(out["SubstanceP"], (7030, 8))

    def test_bad_values_are_ignored(self):
        for bad in ("abc", "0", "-1", "70000", "65535"):
            with _clean_env(FLUX_MAYA_PORT=bad):
                self.assertEqual(constants._apply_port_env(self.DEFAULTS), self.DEFAULTS, bad)


class ExeEnvTests(unittest.TestCase):
    GROUPS = {"Maya": [["C:/default/maya.exe"]], "Nuke": [["C:/default/nuke.exe"]]}

    def test_unset_keeps_patterns(self):
        with _clean_env():
            self.assertEqual(constants._apply_exe_env(self.GROUPS), self.GROUPS)

    def test_set_replaces_one_dcc_and_escapes_brackets(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "apps [x]" / "maya.exe"
            exe.parent.mkdir()
            exe.write_bytes(b"x")
            with _clean_env(FLUX_MAYA_EXE=f'"{exe.as_posix()}"'):
                out = constants._apply_exe_env(self.GROUPS)
        self.assertEqual(out["Maya"], [[exe.as_posix().replace("[", "[[]")]])
        self.assertEqual(out["Nuke"], self.GROUPS["Nuke"])

    def test_missing_file_keeps_the_default_patterns(self):
        with _clean_env(FLUX_MAYA_EXE="D:/nowhere/maya.exe"):
            self.assertEqual(constants._apply_exe_env(self.GROUPS), self.GROUPS)


if __name__ == "__main__":
    unittest.main()
