# test_enabled_dccs.py - V8 U10: per-user enabled DCC list in USER/<user>/User.json.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import main
from utils import user_utils as uu

# Pin the JSON backend so a dev config flipped to sqlite does not fail these tests.
from tests.repository._backend import setUpModule, tearDownModule  # noqa: E402,F401

_KNOWN = {"maya", "houdini", "nuke"}


def _patch_user_dir(user_dir: Path):
    return mock.patch("core.repository_factory.get_user_dir", return_value=user_dir)


class EnabledDccsUtilsTests(unittest.TestCase):
    def test_absent_means_none(self):
        with tempfile.TemporaryDirectory() as d, _patch_user_dir(Path(d)):
            self.assertIsNone(uu.get_enabled_dccs("ADAM"))

    def test_set_filters_unknown_and_dedups(self):
        with tempfile.TemporaryDirectory() as d, _patch_user_dir(Path(d)):
            stored = uu.set_enabled_dccs("ADAM", ["nuke", "maya", "maya", "blender"], _KNOWN)
            self.assertEqual(stored, ["maya", "nuke"])
            self.assertEqual(uu.get_enabled_dccs("ADAM"), ["maya", "nuke"])

    def test_empty_list_is_kept(self):
        with tempfile.TemporaryDirectory() as d, _patch_user_dir(Path(d)):
            self.assertEqual(uu.set_enabled_dccs("ADAM", [], _KNOWN), [])
            self.assertEqual(uu.get_enabled_dccs("ADAM"), [])

    def test_none_resets_and_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as d, _patch_user_dir(Path(d)):
            uu.write_user_data("ADAM", {"production": {"favorites": ["HERO"]}})
            uu.set_enabled_dccs("ADAM", ["maya"], _KNOWN)
            self.assertIsNone(uu.set_enabled_dccs("ADAM", None, _KNOWN))
            self.assertEqual(uu.read_user_data("ADAM"), {"production": {"favorites": ["HERO"]}})

    def test_garbage_value_reads_as_none(self):
        with tempfile.TemporaryDirectory() as d, _patch_user_dir(Path(d)):
            uu.write_user_data("ADAM", {"enabled_dccs": "maya"})
            self.assertIsNone(uu.get_enabled_dccs("ADAM"))


class EnabledDccsRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_roundtrip_via_api(self):
        with tempfile.TemporaryDirectory() as d, _patch_user_dir(Path(d)), \
                mock.patch("core.config.get_current_user", return_value="ADAM"):
            r = self.client.get("/settings/enabled-dccs")
            self.assertEqual(r.status_code, 200)
            self.assertIsNone(r.json()["enabled"])
            self.assertIn("maya", r.json()["known"])

            r = self.client.put("/settings/enabled-dccs", json={"enabled": ["houdini", "nope"]})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["enabled"], ["houdini"])
            self.assertEqual(self.client.get("/settings/enabled-dccs").json()["enabled"], ["houdini"])

            r = self.client.put("/settings/enabled-dccs", json={"enabled": None})
            self.assertIsNone(r.json()["enabled"])

    def test_put_without_user_is_400(self):
        with mock.patch("core.config.get_current_user", return_value=None):
            r = self.client.put("/settings/enabled-dccs", json={"enabled": []})
            self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
