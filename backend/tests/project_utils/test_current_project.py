# test_current_project.py — get_current_project validates last_project against disk.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils import project_utils


class GetCurrentProjectValidation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.projects_dir = Path(self._tmp.name)
        # Two real projects on disk.
        (self.projects_dir / "ALPHA").mkdir()
        (self.projects_dir / "BETA").mkdir()
        # Patch the projects dir used by list_projects / project_exists.
        self._p = mock.patch.object(
            project_utils.paths, "get_projects_dir", return_value=self.projects_dir
        )
        self._p.start()
        self.addCleanup(self._p.stop)
        self.addCleanup(self._tmp.cleanup)

    def _set_last(self, value):
        return mock.patch.object(project_utils.config, "get_last_project", return_value=value)

    def test_valid_stored_project_is_returned(self):
        with self._set_last("BETA"):
            self.assertEqual(project_utils.get_current_project(), "BETA")

    def test_dead_stored_project_falls_back_to_first_available(self):
        with self._set_last("SHOW_A"):  # never existed on disk
            self.assertEqual(project_utils.get_current_project(), "ALPHA")

    def test_none_stored_falls_back_to_first_available(self):
        with self._set_last(None):
            self.assertEqual(project_utils.get_current_project(), "ALPHA")

    def test_no_projects_returns_none(self):
        for d in self.projects_dir.iterdir():
            d.rmdir()
        with self._set_last("SHOW_A"):
            self.assertIsNone(project_utils.get_current_project())


if __name__ == "__main__":
    unittest.main()
