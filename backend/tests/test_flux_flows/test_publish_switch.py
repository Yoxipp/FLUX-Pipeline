# P8 step 2 (2026-10-29, ADR 0070): the publish v1 / v2 choice of a project, read from
# project.json at each call; absent, unknown or unreadable = v1; Photoshop always v1.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.folder_manager import project_config as pc
from flux_flows import switch


class PublishSwitch(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "PROJ"
        self.project.mkdir()
        pc.ensure_project_config(self.project)
        self._p = mock.patch("core.paths.get_project_path", side_effect=lambda name: self.root / name)
        self._p.start()

    def tearDown(self) -> None:
        self._p.stop()
        self._tmp.cleanup()

    def _set(self, value) -> None:
        path = pc.project_config_path(self.project)
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["publish_engine"] = value
        path.write_text(json.dumps(cfg), encoding="utf-8")

    def test_absent_is_v1(self) -> None:
        self.assertNotIn("publish_engine", pc.read_project_config(self.project))
        self.assertEqual(switch.publish_engine("PROJ"), "v1")
        self.assertFalse(switch.flows_publish_enabled("PROJ", "maya"))

    def test_v2_is_read_at_each_call(self) -> None:
        self._set("v2")
        self.assertEqual(switch.publish_engine("PROJ"), "v2")
        for soft in switch.FLOW_SOFTS:
            self.assertTrue(switch.flows_publish_enabled("PROJ", soft), soft)
        self._set("v1")
        self.assertFalse(switch.flows_publish_enabled("PROJ", "houdini"))

    def test_photoshop_stays_v1(self) -> None:
        self._set("v2")
        self.assertFalse(switch.flows_publish_enabled("PROJ", "photoshop"))

    def test_unknown_value_missing_project_or_broken_file_is_v1(self) -> None:
        self._set("v3")
        self.assertEqual(switch.publish_engine("PROJ"), "v1")
        self.assertEqual(switch.publish_engine(""), "v1")
        self.assertEqual(switch.publish_engine("NOPE"), "v1")
        pc.project_config_path(self.project).write_text("{broken", encoding="utf-8")
        self.assertEqual(switch.publish_engine("PROJ"), "v1")

    def test_schema_accepts_v1_v2_only(self) -> None:
        cfg = pc.read_project_config(self.project)
        self.assertEqual(pc.validate_project_config({**cfg, "publish_engine": "v2"}), [])
        self.assertTrue(pc.validate_project_config({**cfg, "publish_engine": "v3"}))
        self.assertTrue(pc.write_project_settings(self.project, {"publish_engine": "v2"}))
        self.assertEqual(switch.publish_engine("PROJ"), "v2")
        with self.assertRaises(ValueError):
            pc.write_project_settings(self.project, {"publish_engine": "flows"})

    def test_new_project_config_does_not_write_the_key(self) -> None:
        self.assertNotIn("publish_engine", pc.default_project_config())


if __name__ == "__main__":
    unittest.main()
