"""Farm Shares read from the engine limits.config (read only): parse, warn, cache, router."""
from __future__ import annotations

import io
import unittest
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


if __name__ == "__main__":
    unittest.main()
