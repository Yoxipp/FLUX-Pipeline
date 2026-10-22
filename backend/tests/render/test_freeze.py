# Farm freeze: LAST -> vNNN, dependency audit, render output folder (ADR 0009 / 0017).
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.publisher import last_pointer as lp
from features.render import freeze

_LEAF = '#usda 1.0\n(\n    defaultPrim = "A"\n)\ndef Xform "A" {}\n'


def _layer(sublayers):
    subs = ", ".join(f"@{s}@" for s in sublayers)
    return f'#usda 1.0\n(\n    subLayers = [{subs}]\n)\n'


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        version = self.root / "asset_v001.usda"
        version.write_text(_LEAF, encoding="utf-8")
        self.last = lp.write_last(self.root, "asset", ".usda", version, 1, lp.MODE_LAYER, user="t")
        self.version = version

    def tearDown(self):
        self._tmp.cleanup()

    def test_resolve_last(self):
        self.assertEqual(freeze.resolve_last(self.last).resolve(), self.version.resolve())
        self.assertEqual(freeze.resolve_last(self.version), self.version)

    def test_freeze_usd_picks_version(self):
        out = freeze.freeze_usd(self.last)
        self.assertTrue(out["frozen"])
        self.assertEqual(Path(out["usd"]).resolve(), self.version.resolve())
        self.assertEqual(out["warnings"], [])

    def test_no_freeze_keeps_last(self):
        out = freeze.freeze_usd(self.last, freeze=False)
        self.assertFalse(out["frozen"])

    def test_deep_last_and_missing_are_reported(self):
        shot = self.root / "shot_v001.usda"
        shot.write_text(_layer(["./asset_LAST.usda", "./missing.usda"]), encoding="utf-8")
        out = freeze.freeze_usd(shot)
        self.assertTrue(any("asset_LAST" in p for p in out["audit"]["last_pointers"]))
        self.assertTrue(any("missing" in p for p in out["audit"]["unresolved"]))
        self.assertEqual(len(out["warnings"]), 2)

    def test_freeze_shot_uses_frozen_stage(self):
        entry = self.root / "SQ01_SH010_v002" / "SQ01_SH010.usda"
        entry.parent.mkdir()
        entry.write_text(_layer(["../asset_v001.usda"]), encoding="utf-8")
        with mock.patch("features.usd_assembler.shot_stage.write_stage",
                        return_value={"entry": entry, "version": "v002", "warnings": []}) as ws:
            out = freeze.freeze_shot(self.root, "SQ01", "SH010", user="t")
        self.assertTrue(ws.call_args.kwargs["frozen"])
        self.assertEqual(out["version"], "v002")
        self.assertEqual(out["warnings"], [])

    def test_next_render_dir(self):
        self.assertEqual(freeze.next_render_dir(self.root).name, "v001")
        (self.root / "render" / "v001").mkdir(parents=True)
        (self.root / "render" / "v004").mkdir()
        self.assertEqual(freeze.next_render_dir(self.root).name, "v005")


if __name__ == "__main__":
    unittest.main()
