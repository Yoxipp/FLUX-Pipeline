# test_first_launch_bootstrap.py — is_first_launch reads config.json (the FILE) via
# core.paths, never the metadata repository, so a stale/unreadable backend cannot make
# a configured install look fresh and reset the workspace on restart.

from __future__ import annotations

import unittest
from unittest import mock

import core.paths as paths
from core import config


def _patch(root, username):
    return (
        mock.patch.object(paths, "get_flux_root", return_value=root),
        mock.patch.object(paths, "get_config_username", return_value=username),
    )


class FirstLaunchReadsFile(unittest.TestCase):
    def test_configured_file_is_not_first_launch(self):
        p1, p2 = _patch("C:/ws", "ADAM")
        with p1, p2:
            self.assertFalse(config.is_first_launch())

    def test_missing_workspace_is_first_launch(self):
        p1, p2 = _patch(None, "ADAM")
        with p1, p2:
            self.assertTrue(config.is_first_launch())

    def test_missing_username_is_first_launch(self):
        p1, p2 = _patch("C:/ws", None)
        with p1, p2:
            self.assertTrue(config.is_first_launch())

    def test_backend_unreadable_does_not_reset(self):
        # Even if the metadata repository would raise, is_first_launch must consult only
        # the file and still report a configured install.
        def _boom(*_a, **_k):
            raise OSError("backend offline (OneDrive offloaded)")
        p1, p2 = _patch("C:/ws", "ADAM")
        with p1, p2, mock.patch.object(config, "get_repository", _boom):
            self.assertFalse(config.is_first_launch())


if __name__ == "__main__":
    unittest.main()
