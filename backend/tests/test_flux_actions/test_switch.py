# test_switch.py — the FLUX_LEGACY_PUBLISH escape hatch (engine is the default).

from __future__ import annotations

import unittest
from unittest import mock

from flux_actions.switch import (
    conform_tx_colorconvert,
    conform_tx_enabled,
    engine_publish_enabled,
    portable_paths_enabled,
    proxy_usd_enabled,
    proxy_usd_reduction,
)


class EnginePublishSwitchTests(unittest.TestCase):
    def _with_env(self, value):
        return mock.patch.dict("os.environ", {"FLUX_LEGACY_PUBLISH": value}, clear=False)

    def test_unset_is_engine_everywhere(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(engine_publish_enabled("houdini"))
            self.assertTrue(engine_publish_enabled("maya"))
            self.assertTrue(engine_publish_enabled("local"))

    def test_empty_is_engine_everywhere(self):
        with self._with_env(""):
            self.assertTrue(engine_publish_enabled("houdini"))

    def test_single_dcc_only_falls_back_to_legacy(self):
        with self._with_env("houdini"):
            self.assertFalse(engine_publish_enabled("houdini"))
            self.assertTrue(engine_publish_enabled("maya"))

    def test_comma_list(self):
        with self._with_env("maya,houdini"):
            self.assertFalse(engine_publish_enabled("maya"))
            self.assertFalse(engine_publish_enabled("houdini"))
            self.assertTrue(engine_publish_enabled("local"))

    def test_all_is_legacy_everywhere(self):
        with self._with_env("all"):
            self.assertFalse(engine_publish_enabled("houdini"))
            self.assertFalse(engine_publish_enabled("maya"))
            self.assertFalse(engine_publish_enabled("local"))

    def test_case_and_whitespace_insensitive(self):
        with self._with_env("  Houdini , MAYA "):
            self.assertFalse(engine_publish_enabled("houdini"))
            self.assertFalse(engine_publish_enabled("MAYA"))
            self.assertTrue(engine_publish_enabled("local"))


class ConformTxSwitchTests(unittest.TestCase):
    """Texture conform is opt-in; colorconvert defaults on when conform is on."""

    def test_conform_off_by_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(conform_tx_enabled())

    def test_conform_on_with_truthy_values(self):
        for value in ("1", "true", "on", "YES"):
            with mock.patch.dict("os.environ", {"FLUX_CONFORM_TX": value}, clear=False):
                self.assertTrue(conform_tx_enabled(), value)

    def test_conform_off_with_falsey_values(self):
        for value in ("0", "false", "off", ""):
            with mock.patch.dict("os.environ", {"FLUX_CONFORM_TX": value}, clear=False):
                self.assertFalse(conform_tx_enabled(), value)

    def test_colorconvert_defaults_on(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(conform_tx_colorconvert())

    def test_colorconvert_can_be_disabled(self):
        for value in ("0", "off", "no", "false"):
            with mock.patch.dict(
                "os.environ", {"FLUX_CONFORM_TX_COLORCONVERT": value}, clear=False
            ):
                self.assertFalse(conform_tx_colorconvert(), value)


class ProxyUsdSwitchTests(unittest.TestCase):
    """USD proxy is opt-in; reduction defaults to 0.9 and validates its range."""

    def test_proxy_off_by_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(proxy_usd_enabled())

    def test_proxy_on_with_truthy(self):
        with mock.patch.dict("os.environ", {"FLUX_PROXY_USD": "on"}, clear=False):
            self.assertTrue(proxy_usd_enabled())

    def test_reduction_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(proxy_usd_reduction(), 0.9)

    def test_reduction_override(self):
        with mock.patch.dict("os.environ", {"FLUX_PROXY_REDUCTION": "0.75"}, clear=False):
            self.assertEqual(proxy_usd_reduction(), 0.75)

    def test_reduction_out_of_range_falls_back(self):
        for bad in ("1.5", "0", "-0.2", "abc", ""):
            with mock.patch.dict("os.environ", {"FLUX_PROXY_REDUCTION": bad}, clear=False):
                self.assertEqual(proxy_usd_reduction(), 0.9, bad)


class PortablePathsSwitchTests(unittest.TestCase):
    """$FLUX token paths at the Houdini boundary are opt-in (F2)."""

    def test_off_by_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(portable_paths_enabled())

    def test_on_with_truthy_values(self):
        for value in ("1", "true", "on", "YES"):
            with mock.patch.dict("os.environ", {"FLUX_PORTABLE_PATHS": value}, clear=False):
                self.assertTrue(portable_paths_enabled(), value)

    def test_off_with_falsey_values(self):
        for value in ("0", "false", "off", ""):
            with mock.patch.dict("os.environ", {"FLUX_PORTABLE_PATHS": value}, clear=False):
                self.assertFalse(portable_paths_enabled(), value)


if __name__ == "__main__":
    unittest.main()
