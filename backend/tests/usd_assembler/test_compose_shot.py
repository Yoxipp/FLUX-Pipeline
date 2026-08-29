# Compose a shot scaffold: a group root over a strong→weak department sublayer
# stack, with the assembly + component placement authored into the weakest
# (layout) layer and the other departments left as empty stubs for the DCCs.
# Diffs the root and layout layers against committed goldens (determinism).

from __future__ import annotations

import unittest
from pathlib import Path

from features.usd_assembler.build.prim_builder import PrimBuilder
from features.usd_assembler.build.reference_builder import ReferenceBuilder
from features.usd_assembler.build.sublayer_builder import SublayerBuilder
from features.usd_assembler.compose.composer import StageComposer
from features.usd_assembler.context import build_context
from features.usd_assembler.recipe import loader
from features.usd_assembler.registry import Registry
from features.usd_assembler.resolve.base import ResolvedAsset

_GOLDEN = Path(__file__).with_name("golden")

_RECIPE = {
    "target": {"kind": "shot", "sequence": "SEQ010", "shot": "SH020"},
    "assembly": {"asset": "ENV_forest"},
    "departments": ["layout", "anim", "fx", "lighting"],
    "components": [
        {"asset": "CHAR_hero", "instance": "hero_01", "xform": {"translate": [2, 0, 5]}}
    ],
    "options": {"format": "usda"},
}


class _FakeResolver:
    """Return per-asset relative paths so golden output is machine-independent."""

    def resolve(self, asset: str, version: str = "latest", dept=None) -> ResolvedAsset:
        return ResolvedAsset(path=Path(f"{asset}.usda"), default_prim=asset, version="v001")


def _compose():
    ctx = build_context(config={})
    ctx.resolver = _FakeResolver()
    registry = Registry()
    registry.register_builder(PrimBuilder())
    registry.register_builder(ReferenceBuilder())
    registry.register_builder(SublayerBuilder())
    composer = StageComposer(ctx, registry)
    stage = composer.compose(loader.load(_RECIPE))
    return composer, stage


class ComposeShot(unittest.TestCase):
    def test_root_is_group(self) -> None:
        _, stage = _compose()
        default = stage.GetDefaultPrim()
        self.assertEqual(default.GetName(), "SEQ010_SH020")
        from pxr import Usd

        self.assertEqual(Usd.ModelAPI(default).GetKind(), "group")

    def test_sublayer_stack_strong_to_weak(self) -> None:
        _, stage = _compose()
        self.assertEqual(
            list(stage.GetRootLayer().subLayerPaths),
            [
                "./SEQ010_SH020_lighting.usda",
                "./SEQ010_SH020_fx.usda",
                "./SEQ010_SH020_anim.usda",
                "./SEQ010_SH020_layout.usda",
            ],
        )

    def test_placement_in_layout_layer(self) -> None:
        composer, _ = _compose()
        layout = composer.department_layers()["layout"][1]
        self.assertIsNotNone(layout.GetPrimAtPath("/SEQ010_SH020/ENV_forest"))
        self.assertIsNotNone(layout.GetPrimAtPath("/SEQ010_SH020/hero_01"))

    def test_other_departments_are_empty_stubs(self) -> None:
        composer, _ = _compose()
        layers = composer.department_layers()
        for dept in ("anim", "fx", "lighting"):
            layer = layers[dept][1]
            self.assertEqual(len(layer.rootPrims), 0)

    def test_matches_golden_root(self) -> None:
        _, stage = _compose()
        produced = stage.GetRootLayer().ExportToString()
        golden = _GOLDEN / "SEQ010_SH020.usda"
        self.assertTrue(golden.exists(), f"golden missing: {golden}")
        self.assertEqual(produced, golden.read_text(encoding="utf-8"))

    def test_matches_golden_layout(self) -> None:
        composer, _ = _compose()
        produced = composer.department_layers()["layout"][1].ExportToString()
        golden = _GOLDEN / "SEQ010_SH020_layout.usda"
        self.assertTrue(golden.exists(), f"golden missing: {golden}")
        self.assertEqual(produced, golden.read_text(encoding="utf-8"))

    def test_determinism(self) -> None:
        _, s1 = _compose()
        _, s2 = _compose()
        self.assertEqual(
            s1.GetRootLayer().ExportToString(),
            s2.GetRootLayer().ExportToString(),
        )


if __name__ == "__main__":
    unittest.main()
