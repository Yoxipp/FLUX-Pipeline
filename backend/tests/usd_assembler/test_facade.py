# Integration tests for the assemble() façade: recipe -> validated stage -> files
# on disk (root + department sublayers), reopenable as a consistent stage.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Usd

from features.usd_assembler.resolve.base import ResolvedAsset
from features.usd_assembler.usd_assembler_core import AssemblyError, assemble


class _FakeResolver:
    """Resolve any asset to a stable relative path (machine-independent output)."""

    def resolve(self, asset: str, version: str = "latest", dept=None) -> ResolvedAsset:
        return ResolvedAsset(path=Path(f"{asset}.usda"), default_prim=asset, version="v001")


_COMPONENT = {"target": {"kind": "component", "asset": "CHAR_hero"}}

_SHOT = {
    "target": {"kind": "shot", "sequence": "SEQ010", "shot": "SH020"},
    "assembly": {"asset": "ENV_forest"},
    "departments": ["layout", "anim", "fx", "lighting"],
    "components": [{"asset": "CHAR_hero", "instance": "hero_01"}],
}


class AssembleFacade(unittest.TestCase):
    def test_component_writes_one_layer(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = assemble(_COMPONENT, resolver=_FakeResolver(), dest_dir=d)
            self.assertEqual(len(result.layers), 1)
            self.assertTrue(result.root.exists())
            self.assertEqual(result.root.name, "CHAR_hero.usda")

    def test_shot_writes_root_plus_departments(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = assemble(_SHOT, resolver=_FakeResolver(), dest_dir=d)
            names = sorted(p.name for p in result.layers)
            self.assertEqual(
                names,
                [
                    "SEQ010_SH020.usda",
                    "SEQ010_SH020_anim.usda",
                    "SEQ010_SH020_fx.usda",
                    "SEQ010_SH020_layout.usda",
                    "SEQ010_SH020_lighting.usda",
                ],
            )
            for path in result.layers:
                self.assertTrue(path.exists(), f"missing on disk: {path}")

    def test_written_shot_reopens_consistently(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = assemble(_SHOT, resolver=_FakeResolver(), dest_dir=d)
            # Reopen from disk (payloads unloaded) — sublayers resolve side by side.
            stage = Usd.Stage.Open(str(result.root), load=Usd.Stage.LoadNone)
            self.assertEqual(stage.GetDefaultPrim().GetName(), "SEQ010_SH020")
            # The layout placement composes into the reopened stage.
            self.assertTrue(stage.GetPrimAtPath("/SEQ010_SH020/hero_01").IsValid())

    def test_strict_raises_on_validation_error(self) -> None:
        # A 'sequence' target is not composed yet -> empty stage -> no defaultPrim,
        # which is a validation error that a strict run must surface (not write).
        empty = {"target": {"kind": "sequence", "name": "SEQ010"}}
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(AssemblyError):
                assemble(empty, resolver=_FakeResolver(), dest_dir=d, strict=True)

    def test_non_strict_returns_issues_without_raising(self) -> None:
        empty = {"target": {"kind": "sequence", "name": "SEQ010"}}
        with tempfile.TemporaryDirectory() as d:
            result = assemble(empty, resolver=_FakeResolver(), dest_dir=d, strict=False)
            self.assertTrue(any(i.level == "error" for i in result.issues))


if __name__ == "__main__":
    unittest.main()
