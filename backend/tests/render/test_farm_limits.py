"""Farm Shares of the engine limits.config: parse, warn, cache, and the locked environment edit."""
from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.render import farm_limits as fl

# Same shape as the school file (2026-10-23): '#' and '//' comment lines, a trailing comma.
SAMPLE = """{
    "Limits":
    {
        # Example:
        #   "prman":    {"SiteMax": 100, "OwnerMax": -1},  <-- note comma!
       "prman":
        {
        "SiteMax": -1,
        //"TaggedBlades": "Windows",
        "Shares": {
            "Andhakara": {"nominal": 0.25, "cap": 0.99},
            "default": {"nominal": 0.25, "cap": 0.1}
            }
        },
#       "Render":
#       {
#       "Shares": {"Old": {"nominal": 1}}
#       },
        "husk":
        {
        "OwnerMax": -1,
        "Shares": {
            "Andhakara": {"nominal": 0.25, "cap": 0.99},
            "Lum": {"nominal": 0.25, "cap": 0.99},
            "MortalKoil": {"nominal": 0.25, "cap": 0.99},
            "Hold": {"nominal": 0.25, "cap": 0.99},
            "default": {"nominal": 0.25, "cap": 0.1}
            }
        },
        "NoShares": {"SiteMax": 4},
    }
}
"""


class Parse(unittest.TestCase):
    def test_shares_per_tag(self):
        shares = fl.parse_shares(SAMPLE)
        self.assertEqual(sorted(shares), ["husk", "prman"])
        self.assertEqual(shares["husk"]["default"], {"nominal": 0.25, "cap": 0.1})
        self.assertEqual(fl.teams(shares), ["Andhakara", "Hold", "Lum", "MortalKoil"])

    def test_unreadable_is_empty(self):
        self.assertEqual(fl.parse_shares("not json"), {})
        self.assertEqual(fl.parse_shares('{"Limits": []}'), {})

    def test_config_url(self):
        self.assertEqual(fl.config_url("192.0.2.10"), "http://192.0.2.10/Tractor/config?file=limits.config")
        self.assertEqual(fl.config_url("tractor:5600"), "http://tractor:5600/Tractor/config?file=limits.config")
        for bad in ("", "  ", "a b", "x/../y", "h?file=x"):
            self.assertIsNone(fl.config_url(bad))


class Warning(unittest.TestCase):
    shares = fl.parse_shares(SAMPLE)

    def test_known_team_is_fine(self):
        self.assertIsNone(fl.team_warning("Lum", self.shares))

    def test_unknown_team_falls_in_default(self):
        w = fl.team_warning("Flux_Test", self.shares)
        self.assertIn("'default'", w)
        self.assertIn("10 %", w)
        self.assertIn("Andhakara, Hold, Lum, MortalKoil", w)
        self.assertNotIn("—", w)  # no em dash in UI texts

    def test_case_mismatch_names_the_right_one(self):
        self.assertIn("'MortalKoil'", fl.team_warning("mortalkoil", self.shares))

    def test_unknown_farm_never_warns(self):
        self.assertIsNone(fl.team_warning("X", None))
        self.assertIsNone(fl.team_warning("X", {"prman": {"A": {}}}))  # no Shares on husk: nothing to say


class Fetch(unittest.TestCase):
    def setUp(self):
        fl._cache.clear()
        self.addCleanup(fl._cache.clear)

    def test_cached_and_read_only(self):
        with mock.patch.object(fl.urllib.request, "urlopen", return_value=io.BytesIO(SAMPLE.encode())) as get:
            first = fl.fetch_shares("192.0.2.10")
            again = fl.fetch_shares("192.0.2.10")
        self.assertEqual(fl.teams(first), ["Andhakara", "Hold", "Lum", "MortalKoil"])
        self.assertIs(again, first)
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], "http://192.0.2.10/Tractor/config?file=limits.config")  # GET only

    def test_engine_down_is_unknown(self):
        with mock.patch.object(fl.urllib.request, "urlopen", side_effect=OSError("timed out")) as get:
            self.assertIsNone(fl.fetch_shares("192.0.2.10"))
            self.assertIsNone(fl.fetch_shares("192.0.2.10"))  # failure cached a minute
        get.assert_called_once()
        self.assertIsNone(fl.fetch_shares(""))


TEAMS = {"Andhakara": {"nominal": 0.2, "cap": 0.99}, "Annee4": {"nominal": 0.1, "cap": 0.3},
         "default": {"nominal": 0.1, "cap": 0.1}}


class EditShares(unittest.TestCase):
    """Environment screen. Never the real engine: temp folders and a mocked engine only."""

    def test_unlock(self):
        fl.check_unlock("Understand")
        self.assertFalse(hasattr(fl, "ENV_PASSWORD"))  # no shared password any more: the project role decides
        for phrase in ("understand", "", "Understand "):
            with self.assertRaises(fl.LimitsError):
                fl.check_unlock(phrase)

    def test_check_teams(self):
        for bad in ({}, {"A": {"nominal": 0.2, "cap": 0.5}},  # no default
                    {"a b": {"nominal": 0.1, "cap": 0.1}, "default": {"nominal": 0.1, "cap": 0.1}},
                    {"default": {"nominal": 1.5, "cap": 0.1}}, {"default": {"nominal": 0.1, "cap": 0}}):
            with self.assertRaises(fl.LimitsError):
                fl.check_teams(bad)

    def test_apply_keeps_comments_and_rules(self):
        new = fl.apply_shares(SAMPLE, TEAMS)
        self.assertEqual(fl.parse_shares(new), {"prman": TEAMS, "husk": TEAMS})
        self.assertIn('#       "Shares": {"Old": {"nominal": 1}}', new)  # commented block untouched
        self.assertIn('//"TaggedBlades": "Windows",', new)
        self.assertIn('"NoShares": {"SiteMax": 4},', new)
        self.assertEqual(fl._rules_without_shares(new), fl._rules_without_shares(SAMPLE))
        self.assertLess(new.index('"Annee4"'), new.index('"default"', new.index('"Annee4"')))  # default last

    def test_apply_needs_a_shares_block(self):
        with self.assertRaises(fl.LimitsError):
            fl.apply_shares('{"Limits": {"prman": {"SiteMax": 1}}}', TEAMS)

    def _folder(self, text=SAMPLE):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "limits.config").write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        return folder

    def test_write_backs_up_then_replaces(self):
        folder = self._folder()
        with mock.patch.object(fl, "engine_text", return_value=SAMPLE):
            out = fl.write_shares(str(folder), "eng", TEAMS, "Understand")
        self.assertEqual(out["shares"]["husk"], TEAMS)
        written = (folder / "limits.config").read_bytes().decode("utf-8")
        self.assertEqual(fl.parse_shares(written)["husk"], TEAMS)
        self.assertIn("\r\n", written)  # line endings kept
        backup = Path(out["backup"])
        self.assertTrue(backup.is_file())
        self.assertTrue(fl.same_text(backup.read_bytes().decode("utf-8"), SAMPLE))
        self.assertEqual(sorted(p.name for p in folder.iterdir() if p.name.startswith(".")), [])  # no temp left

    def test_write_refused_on_wrong_folder_or_engine_down(self):
        folder = self._folder()
        before = (folder / "limits.config").read_bytes()
        for served in (None, SAMPLE.replace("0.1}", "0.2}")):
            with mock.patch.object(fl, "engine_text", return_value=served), self.assertRaises(fl.LimitsError):
                fl.write_shares(str(folder), "eng", TEAMS, "Understand")
        with mock.patch.object(fl, "engine_text", return_value=SAMPLE), self.assertRaises(fl.LimitsError):
            fl.write_shares(str(folder), "eng", TEAMS, "wrong")
        with self.assertRaises(fl.LimitsError):
            fl.write_shares("", "eng", TEAMS, "Understand")
        self.assertEqual((folder / "limits.config").read_bytes(), before)
        self.assertEqual([p.name for p in folder.iterdir()], ["limits.config"])  # no backup either


if __name__ == "__main__":
    unittest.main()
