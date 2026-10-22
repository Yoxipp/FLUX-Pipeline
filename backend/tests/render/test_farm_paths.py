# test_farm_paths.py - paths as the farm sees them: UNC kept, drive letters mapped or refused.

from __future__ import annotations

import unittest
from unittest import mock

from features.render import farm_paths


class FarmPaths(unittest.TestCase):
    def test_unc_kept_and_normalized(self):
        self.assertEqual(farm_paths.to_farm_path(r"\\srv\share\proj\a.usd"), "//srv/share/proj/a.usd")
        self.assertEqual(farm_paths.to_farm_path("//srv/share/a.usd"), "//srv/share/a.usd")

    def test_relative_path_kept(self):
        self.assertEqual(farm_paths.to_farm_path(r"rel\dir\a.usd"), "rel/dir/a.usd")

    def test_mapped_drive_becomes_unc(self):
        with mock.patch.object(farm_paths, "_unc_of_drive", return_value=r"\\srv\share") as m:
            self.assertEqual(farm_paths.to_farm_path(r"x:\proj\a.usd"), "//srv/share/proj/a.usd")
            m.assert_called_once_with("X:")

    def test_mapped_drive_trailing_slash(self):
        with mock.patch.object(farm_paths, "_unc_of_drive", return_value="\\\\srv\\share\\"):
            self.assertEqual(farm_paths.to_farm_path(r"X:\proj"), "//srv/share/proj")

    def test_local_drive_is_none(self):
        with mock.patch.object(farm_paths, "_unc_of_drive", return_value=None):
            self.assertIsNone(farm_paths.to_farm_path(r"C:\proj\a.usd"))


if __name__ == "__main__":
    unittest.main()
