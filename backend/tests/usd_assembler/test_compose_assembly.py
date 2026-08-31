# Compose an assembly (a kind=assembly prim referencing N published components as
# placed instances) and diff against a committed golden .usda (determinism check).

from __future__ import annotations

import unittest
from pathlib import Path

from features.usd_assembler.build.prim_builder import PrimBuilder
from features.usd_assembler.build.reference_builder import ReferenceBuilder
from features.usd_assembler.compose.composer import StageComposer
from features.usd_assembler.context import build_context
from features.usd_assembler.recipe import loader
from features.usd_assembler.registry import Registry
from features.usd_assembler.resolve.base import ResolvedAsset

_GOLDEN = Path(__file__).with_name("golden") / "ENV_forest.usda"

_RECIPE = {
    "target": {"kind": "assembly", "asset": "ENV_forest"},
    "components": [
        {
            "asset": "Tree_pine",
            "instance": "tree_a",
            "xform": {"translate": [0, 0, 0]},
            "variants": {"lod": "hi"},
        },
        {
            "asset": "Tree_pine",
            "instance": "tree_b",
            "xform": {"translate": [10, 0, -4], "scale": [1.2, 1.2, 1.2]},
        },
        {
            "asset": "Rock_granite",
            "instance": "rock_a",
            "xform": {"translate": [3, 0, 2], "rotate": [0, 45, 0]},
        },
    ],
    "options": {"format": "usda"},
}


class _FakeResolver:
    """Return per-asset relative geometry paths so golden output is machine-independent."""

    def resolve(self, asset: str, version: str = "latest", dept=None) -> ResolvedAsset:
        return ResolvedAsset(path=Path(f"{asset}.usd"), default_prim=asset, version="v001")


def _compose_stage():
    ctx = build_context(config={})
    ctx.resolver = _FakeResolver()
    registry = Registry()
    registry.register_builder(PrimBuilder())
    registry.register_builder(ReferenceBuilder())
    recipe = loader.load(_RECIPE)
    return StageComposer(ctx, registry).compose(recipe)


class ComposeAssembly(unittest.TestCase):
    def test_root_kind_and_default_prim(self) -> None:
        stage = _compose_stage()
        default = stage.GetDefaultPrim()
        self.assertEqual(default.GetName(), "ENV_forest")
        from pxr import Usd

        self.assertEqual(Usd.ModelAPI(default).GetKind(), "assembly")

    def test_instances_are_children(self) -> None:
        stage = _compose_stage()
        names = sorted(p.GetName() for p in stage.GetPrimAtPath("/ENV_forest").GetChildren())
        self.assertEqual(names, ["rock_a", "tree_a", "tree_b"])

    def test_instance_has_reference(self) -> None:
        stage = _compose_stage()
        prim = stage.GetPrimAtPath("/ENV_forest/tree_a")
        self.assertTrue(prim.HasAuthoredReferences())

    def test_instance_xform(self) -> None:
        from pxr import Gf, UsdGeom

        stage = _compose_stage()
        prim = stage.GetPrimAtPath("/ENV_forest/tree_b")
        ops = {op.GetOpName(): op for op in UsdGeom.Xformable(prim).GetOrderedXformOps()}
        self.assertEqual(ops["xformOp:translate"].Get(), Gf.Vec3d(10, 0, -4))
        self.assertEqual(ops["xformOp:scale"].Get(), Gf.Vec3f(1.2, 1.2, 1.2))

    def test_variant_selection(self) -> None:
        # The variantSet itself lives in the (unresolved-in-test) referenced
        # component, so assert the *authored* selection on the assembly layer
        # rather than the composed value.
        stage = _compose_stage()
        spec = stage.GetRootLayer().GetPrimAtPath("/ENV_forest/tree_a")
        self.assertEqual(dict(spec.variantSelections), {"lod": "hi"})

    def test_matches_golden(self) -> None:
        produced = _compose_stage().GetRootLayer().ExportToString()
        self.assertTrue(_GOLDEN.exists(), f"golden missing: {_GOLDEN}")
        self.assertEqual(produced, _GOLDEN.read_text(encoding="utf-8"))

    def test_determinism(self) -> None:
        self.assertEqual(
            _compose_stage().GetRootLayer().ExportToString(),
            _compose_stage().GetRootLayer().ExportToString(),
        )


if __name__ == "__main__":
    unittest.main()
