# Per-project render team settings (render.json): defaults, validation, fallbacks.
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import paths
from features.render import team_settings as ts


class TeamSettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.file = Path(self._tmp.name) / "render.json"
        p = patch.object(paths, "get_project_render_path", lambda name: self.file)
        p.start()
        self.addCleanup(p.stop)

    def test_defaults_on_missing_file(self):
        self.assertEqual(ts.read_settings("proj"), ts.DEFAULTS)
        self.assertFalse(self.file.exists())

    def test_roundtrip(self):
        out = ts.write_settings("proj", {"priority": 50, "chunk_size": 10, "renderer": "renderman"})
        self.assertEqual(out["priority"], 50)
        again = ts.read_settings("proj")
        self.assertEqual(again, out)
        self.assertEqual(again["chunk_size"], 10)
        self.assertEqual(again["maxactive"], 0)
        self.assertEqual(json.loads(self.file.read_text("utf-8"))["schema_version"], 1)

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError) as cm:
            ts.write_settings("proj", {"bogus": 1})
        self.assertIn("bogus", str(cm.exception))

    def test_invalid_value_rejected_on_write(self):
        for bad in ({"priority": 0}, {"priority": 10001}, {"priority": True},
                    {"chunk_size": 0}, {"maxactive": -1}, {"renderer": "arnold"},
                    {"envkeys": "x"}, {"dry_run": "no"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                ts.write_settings("proj", bad)
        self.assertFalse(self.file.exists())

    def test_corrupted_value_falls_back_on_read(self):
        self.file.write_text(json.dumps({
            "priority": "high", "chunk_size": 8, "renderer": "x", "extra": 1,
            "schedule": {"start": "25:00", "end": "07:30"},
        }), encoding="utf-8")
        got = ts.read_settings("proj")
        self.assertEqual(got["priority"], 100)
        self.assertEqual(got["chunk_size"], 8)
        self.assertEqual(got["renderer"], "karma")
        self.assertNotIn("extra", got)
        self.assertEqual(got["schedule"]["start"], "18:00")
        self.assertEqual(got["schedule"]["end"], "07:30")

    def test_partial_schedule_patch_keeps_stored_keys(self):
        ts.write_settings("proj", {"schedule": {"start": "20:00", "end": "06:00"}})
        out = ts.write_settings("proj", {"schedule": {"start": "21:00"}})
        self.assertEqual(out["schedule"]["end"], "06:00")

    def test_overnight_schedule_valid(self):
        out = ts.write_settings("proj", {"schedule": {"start": "22:00", "end": "06:00"}})
        self.assertEqual(out["schedule"]["start"], "22:00")
        self.assertEqual(out["schedule"]["end"], "06:00")
        self.assertFalse(out["schedule"]["kill_at_end"])  # opt-in, off by default
        self.assertFalse(ts.DEFAULTS["schedule"]["enabled"])

    def test_bad_hhmm_rejected(self):
        for bad in ("24:00", "9:00", "18:60", "abc", 1800):
            with self.assertRaises(ValueError, msg=str(bad)):
                ts.write_settings("proj", {"schedule": {"start": bad}})

    def test_effective_tractor_project_default(self):
        self.assertEqual(ts.effective_settings("MyProj")["tractor_project"], "MyProj")
        ts.write_settings("MyProj", {"tractor_project": "team_a"})
        self.assertEqual(ts.effective_settings("MyProj")["tractor_project"], "team_a")
        self.assertEqual(ts.read_settings("MyProj")["tractor_project"], "team_a")

    def test_priority_warning(self):
        self.assertIsNone(ts.priority_warning({"priority": 100}))
        self.assertIsNone(ts.priority_warning({"priority": 50, "maxactive": 0}))
        msg = ts.priority_warning({"priority": 500})
        self.assertTrue(msg)
        self.assertNotIn("—", msg)

    def test_explicit_path_override(self):
        other = Path(self._tmp.name) / "other.json"
        ts.write_settings("proj", {"chunk_size": 3}, path=other)
        self.assertEqual(ts.read_settings("proj", path=other)["chunk_size"], 3)
        self.assertFalse(self.file.exists())


if __name__ == "__main__":
    unittest.main()
