"""FLUX_<DCC>_EXE wins over registry / Epic detection only when the file exists."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.constants import DCC_EXE_ENV
from features.launcher import launcher_core as lc

_CASES = (("maya", "FLUX_MAYA_EXE"), ("photoshop", "FLUX_PHOTOSHOP_EXE"),
          ("unreal", "FLUX_UNREAL_EXE"))


class EnvExeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.detected = self._file("detected.exe")
        self.forced = self._file("forced.exe")
        env = {k: v for k, v in os.environ.items() if k not in DCC_EXE_ENV.values()}
        for patch in (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(lc, "_registry_candidates", return_value=[self.detected]),
            mock.patch.object(lc, "DCC_EXE_PATTERN_GROUPS", {}),
            mock.patch.object(lc, "_warned_missing", set()),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def _file(self, name: str) -> str:
        path = Path(self._tmp.name) / name
        path.write_bytes(b"x")
        return os.path.normpath(str(path))

    def test_set_and_existing_wins(self):
        for key, var in _CASES:
            os.environ[var] = self.forced
            self.assertEqual(lc.list_dcc_candidates(key), [self.forced], key)

    def test_set_but_missing_falls_back_and_logs_once(self):
        for key, var in _CASES:
            os.environ[var] = str(Path(self._tmp.name) / f"{key}_missing.exe")
            with mock.patch.object(lc.log, "warning") as warning:
                self.assertEqual(lc.list_dcc_candidates(key), [self.detected], key)
                self.assertEqual(lc.list_dcc_candidates(key), [self.detected], key)
            self.assertEqual(warning.call_count, 1, key)

    def test_unset_keeps_detection(self):
        for key, _var in _CASES:
            self.assertEqual(lc.list_dcc_candidates(key), [self.detected], key)

    def test_env_exe_is_not_saved_in_settings(self):
        os.environ["FLUX_MAYA_EXE"] = self.forced
        with mock.patch.object(lc.config, "set_dcc_exe") as save:
            self.assertEqual(lc.find_dcc_exe("maya"), self.forced)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
