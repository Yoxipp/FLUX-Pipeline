# test_user_settings_via_repository.py - User.json routes through the repository.
#
# End-to-end: user_utils.read_user_data / write_user_data go through the process
# repository (user_settings collection = one User.json per artist, keyed by name).
# Proves the reroute keeps the on-disk format (a dict), the missing-file default
# ({}), the parent-dir auto-creation via set(), and the public signatures. The
# path is resolved by the factory (get_user_dir), so we patch it there.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.constants import JSON_USER_SETTINGS
from utils import user_utils as uu


def _patch_user_dir(user_dir: Path):
    # The factory resolves user_settings via get_user_dir(name)/UserSettings/User.json.
    return mock.patch(
        "core.repository_factory.get_user_dir",
        return_value=user_dir,
    )


class UserSettingsViaRepositoryTests(unittest.TestCase):
    def test_read_missing_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as d:
            with _patch_user_dir(Path(d)):
                self.assertEqual(uu.read_user_data("ADAM"), {})

    def test_write_then_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            with _patch_user_dir(Path(d)):
                self.assertTrue(uu.write_user_data("ADAM", {"favorites": ["HERO"]}))
                self.assertEqual(uu.read_user_data("ADAM"), {"favorites": ["HERO"]})

    def test_write_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as d:
            # UserSettings/ does not exist yet; set() must create it.
            user_dir = Path(d) / "ADAM"
            with _patch_user_dir(user_dir):
                self.assertTrue(uu.write_user_data("ADAM", {"x": 1}))
                self.assertTrue((user_dir / "UserSettings" / JSON_USER_SETTINGS).exists())

    def test_on_disk_format_is_a_dict(self):
        with tempfile.TemporaryDirectory() as d:
            user_dir = Path(d)
            with _patch_user_dir(user_dir):
                uu.write_user_data("ADAM", {"recents": ["a", "b"]})
            raw = json.loads(
                (user_dir / "UserSettings" / JSON_USER_SETTINGS).read_text(encoding="utf-8")
            )
            self.assertIsInstance(raw, dict)
            self.assertEqual(raw, {"recents": ["a", "b"]})


if __name__ == "__main__":
    unittest.main()
