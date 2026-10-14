# N8 "Parametres avances": project.json settings (validated) and the publish switches of
# the machine (decision D1: saved in the prefs, applied to the env read by switch.py).

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.settings import advanced as adv
from flux_actions import switch
from core.project_setup import setup_path

_ENVS = [env for env, _ in adv.SWITCHES.values()]


class Switches(unittest.TestCase):
    def setUp(self) -> None:
        self.prefs: dict = {}
        for target, fn in (("get", lambda k, d=None: self.prefs.get(k, d)),
                           ("set", lambda k, v: self.prefs.__setitem__(k, v))):
            p = mock.patch.object(adv.config, target, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for name in _ENVS:
            os.environ.pop(name, None)
        launch = mock.patch.dict(adv._launch_env, {}, clear=True)
        launch.start()
        self.addCleanup(launch.stop)

    def test_a_saved_switch_drives_the_publish_code_at_once(self) -> None:
        adv.save_switches({"proxy_usd": False, "conform_tx": True, "proxy_reduction": 0.75})
        self.assertFalse(switch.proxy_usd_enabled())
        self.assertTrue(switch.conform_tx_enabled())
        self.assertEqual(switch.proxy_usd_reduction(), 0.75)
        state = adv.read_switches()
        self.assertEqual((state["proxy_usd"]["value"], state["proxy_usd"]["source"]), (False, "page"))
        self.assertEqual(self.prefs["advanced_switches"]["conform_tx"], True)

    def test_going_back_to_the_default(self) -> None:
        adv.save_switches({"conform_tx": True})
        adv.save_switches({"conform_tx": None})
        self.assertNotIn("FLUX_CONFORM_TX", os.environ)
        self.assertEqual(adv.read_switches()["conform_tx"]["source"], "defaut")

    def test_saved_values_are_applied_at_start_unless_set_at_launch(self) -> None:
        self.prefs["advanced_switches"] = {"proxy_usd": False, "portable_paths": False}
        os.environ["FLUX_PORTABLE_PATHS"] = "1"          # the dev .bat set it
        self.assertEqual(adv.apply_saved_switches(), ["proxy_usd"])
        self.assertEqual(os.environ["FLUX_PROXY_USD"], "0")
        self.assertTrue(switch.portable_paths_enabled())
        self.assertEqual(adv.read_switches()["portable_paths"]["source"], "lancement")

    def test_bad_values_are_refused(self) -> None:
        for values in ({"proxy_usd": "yes"}, {"proxy_reduction": 1.5}, {"proxy_reduction": True}, {"nope": 1}):
            with self.assertRaises(ValueError, msg=values):
                adv.save_switches(values)
        self.assertEqual(self.prefs, {})


class ProjectSettings(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()

    def _file(self) -> dict:
        return json.loads(setup_path(self.project, "project.json").read_text(encoding="utf-8"))

    def test_read_gives_the_editable_part(self) -> None:
        res = adv.read_project_settings(self.project)
        self.assertTrue(res["project_id"])
        self.assertEqual(res["values"]["usd"], {"meters_per_unit": 1.0, "up_axis": "Y"})
        self.assertEqual(res["values"]["storage"]["last_link_threshold_gb"], 2.0)
        self.assertIn("link", res["last_modes"])

    def test_write_merges_and_keeps_the_identity(self) -> None:
        pid = adv.read_project_settings(self.project)["project_id"]
        adv.write_project_settings(self.project, {"fps": 25, "usd": {"up_axis": "Z"},
                                                  "storage": {"last_mode": {".abc": "link"}}})
        data = self._file()
        self.assertEqual((data["fps"], data["usd"]["up_axis"], data["usd"]["meters_per_unit"]), (25, "Z", 1.0))
        self.assertEqual(data["storage"]["last_mode"], {".abc": "link"})
        self.assertEqual(data["project_id"], pid)

    def test_invalid_values_leave_the_file_untouched(self) -> None:
        adv.read_project_settings(self.project)
        before = self._file()
        for patch in ({"fps": -1}, {"usd": {"up_axis": "X"}}, {"storage": {"last_mode": {".abc": "move"}}},
                      {"storage": {"last_link_threshold_gb": 0}}, {"project_id": "x"}, {"env": {"A": 1}}):
            with self.assertRaises(ValueError, msg=patch):
                adv.write_project_settings(self.project, patch)
        self.assertEqual(self._file(), before)


if __name__ == "__main__":
    unittest.main()
