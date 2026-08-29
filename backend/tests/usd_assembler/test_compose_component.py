# Compose a single published asset into a component USD stage (payload + variant
# sets) and diff against a committed golden .usda (determinism check).

from __future__ import annotations

import unittest
from pathlib import Path

from features.usd_assembler.build.payload_builder import PayloadBuilder
from features.usd_assembler.build.variantset_builder import VariantSetBuilder
from features.usd_assembler.compose.composer import StageComposer
from features.usd_assembler.context import build_context
from features.usd_assembler.recipe import loader
from features.usd_assembler.registry import Registry
from features.usd_assembler.resolve.base import ResolvedAsset

_GOLDEN = Path(__file__).with_name("golden") / "CHAR_hero.usda"

_RECIPE = {
    "target": {"kind": "component", "asset": "CHAR_hero"},
    "options": {"format": "usda"},
}


class _FakeResolver:
    """Return a stable, relative geometry path so golden output is machine-independent."""

    def resolve(self, asset: str, version: str = "latest", dept=None) -> ResolvedAsset:
        return ResolvedAsset(path=Path("geometry.usd"), default_prim="geo", version="v001")


def _compose_stage():
    ctx = build_context(config={})
    ctx.resolver = _FakeResolver()
    registry = Registry()
    registry.register_builder(PayloadBuilder())
    registry.register_builder(VariantSetBuilder())
    recipe = loader.load(_RECIPE)
    return StageComposer(ctx, registry).compose(recipe)


class ComposeComponent(unittest.TestCase):
    def test_default_prim_and_kind(self) -> None:
        stage = _compose_stage()
        default = stage.GetDefaultPrim()
        self.assertEqual(default.GetName(), "CHAR_hero")
        from pxr import Usd

        self.assertEqual(Usd.ModelAPI(default).GetKind(), "component")

    def test_has_payload(self) -> None:
        stage = _compose_stage()
        prim = stage.GetPrimAtPath("/CHAR_hero")
        self.assertTrue(prim.HasPayload())

    def test_variant_sets(self) -> None:
        stage = _compose_stage()
        prim = stage.GetPrimAtPath("/CHAR_hero")
        vsets = prim.GetVariantSets()
        self.assertEqual(sorted(vsets.GetNames()), ["lod", "look", "purpose"])
        self.assertEqual(sorted(prim.GetVariantSet("lod").GetVariantNames()), ["hi", "lo", "mid"])
        self.assertEqual(prim.GetVariantSet("lod").GetVariantSelection(), "hi")

    def test_matches_golden(self) -> None:
        stage = _compose_stage()
        produced = stage.GetRootLayer().ExportToString()
        self.assertTrue(_GOLDEN.exists(), f"golden missing: {_GOLDEN}")
        self.assertEqual(produced, _GOLDEN.read_text(encoding="utf-8"))

    def test_determinism(self) -> None:
        self.assertEqual(
            _compose_stage().GetRootLayer().ExportToString(),
            _compose_stage().GetRootLayer().ExportToString(),
        )


if __name__ == "__main__":
    unittest.main()
