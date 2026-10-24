# test_user_names.py - artist names can never address anything outside USER/.
#
# delete_user / rename_user act on USER/<name>. Before the guard, "%2E%2E" (..)
# resolved to FLUX_ROOT and a blank name to USER/ itself, so one DELETE call could
# force_rmtree the whole workspace. Runs on a temporary FLUX_ROOT.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils import user_utils as uu


class UserNameGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.users = self.root / "USER"
        (self.users / "ALICE").mkdir(parents=True)
        (self.users / "ÉLODIE").mkdir()
        (self.root / "keep.txt").write_text("workspace", encoding="utf-8")
        patches = [
            mock.patch("core.paths.get_users_dir", return_value=self.users),
            mock.patch.object(uu, "get_current_user", return_value="ACTIVE"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def _workspace_intact(self):
        self.assertTrue((self.root / "keep.txt").is_file())
        self.assertTrue((self.users / "ALICE").is_dir())

    def test_valid_names(self):
        for name in ("ALICE", "ÉLODIE", "JEAN PIERRE", "ADAM_COM", "A-B", "V2"):
            self.assertTrue(uu.is_valid_user_name(name), name)

    def test_unsafe_names(self):
        for name in ("", " ", ".", "..", "../X", "..\\X", "A/B", "A\\B", "C:", "A.",
                     "A ", " A", "A*", "A\x00", "CON", "nul", "COM1", "LPT9.TXT"):
            self.assertFalse(uu.is_valid_user_name(name), repr(name))

    def test_delete_parent_is_refused(self):
        for name in ("..", "../..", "..\\USER", " ", "", "."):
            ok, _ = uu.delete_user(name)
            self.assertFalse(ok, repr(name))
            self._workspace_intact()

    def test_rename_out_of_user_is_refused(self):
        for new in ("../EVIL", "..\\EVIL", "..", "A/B"):
            ok, _ = uu.rename_user("ALICE", new)
            self.assertFalse(ok, new)
        ok, _ = uu.rename_user("..", "X")
        self.assertFalse(ok)
        self._workspace_intact()
        self.assertFalse((self.root / "EVIL").exists())

    def test_create_user_dir_refuses_unsafe(self):
        with self.assertRaises(ValueError):
            uu.create_user_dir("../OUTSIDE")
        self.assertFalse((self.root / "OUTSIDE").exists())

    def test_valid_rename_and_delete_still_work(self):
        ok, _ = uu.rename_user("ALICE", "BOB")
        self.assertTrue(ok)
        self.assertTrue((self.users / "BOB").is_dir())
        ok, _ = uu.delete_user("ÉLODIE")
        self.assertTrue(ok)
        self.assertFalse((self.users / "ÉLODIE").exists())
        self.assertTrue((self.root / "keep.txt").is_file())


if __name__ == "__main__":
    unittest.main()
