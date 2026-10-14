"""Root-scoped prefs: switching workspace forgets the other root's projects, coming back restores them."""

import unittest
from unittest import mock

from core import config


class WorkspacePrefs(unittest.TestCase):
    def setUp(self):
        self.store: dict = {}
        p1 = mock.patch.object(config, "_load", lambda: dict(self.store))
        p2 = mock.patch.object(config, "_save", lambda d: self.store.update(d) or None)
        p1.start(); p2.start()
        self.addCleanup(mock.patch.stopall)

    def _switch(self, old, new):
        config.stash_workspace_prefs(old)
        config.restore_workspace_prefs(new)

    def test_new_root_starts_empty_and_old_root_comes_back(self):
        self.store["last_project"] = "PROJ_A"
        self._switch("D:/ROOT_A", "E:/ROOT_B")
        self.assertIsNone(self.store["last_project"])
        self.store["last_project"] = "PROJ_B"
        self._switch("E:/ROOT_B", "d:\ROOT_A\\")
        self.assertEqual(self.store["last_project"], "PROJ_A")
        self._switch("D:/ROOT_A", "E:/ROOT_B")
        self.assertEqual(self.store["last_project"], "PROJ_B")

    def test_restore_without_memory_keeps_prefs(self):
        self.store["last_project"] = "OWN"
        config.restore_workspace_prefs("X:/R")
        self.assertEqual(self.store["last_project"], "OWN")


if __name__ == "__main__":
    unittest.main()
