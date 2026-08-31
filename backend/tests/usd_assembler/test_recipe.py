# Unit tests for the recipe model + loader (pure python, no pxr).

from __future__ import annotations

import unittest

from features.usd_assembler.recipe import loader
from features.usd_assembler.recipe.loader import RecipeError
from features.usd_assembler.recipe.model import RefSpec, VariantSpec


_SHOT_RECIPE = {
    "target": {"kind": "shot", "sequence": "SEQ010", "shot": "SH020"},
    "assembly": {"asset": "ENV_forest", "version": "latest"},
    "departments": ["layout", "anim", "fx", "lighting"],
    "components": [
        {
            "asset": "CHAR_hero",
            "instance": "hero_01",
            "variants": {"lod": "hi", "look": "damaged"},
        }
    ],
    "options": {"format": "usda", "load": "payloads-on-demand"},
}


class LoadValidRecipe(unittest.TestCase):
    def test_target_and_options_preserved(self) -> None:
        recipe = loader.load(_SHOT_RECIPE)
        self.assertEqual(recipe.target_kind, "shot")
        self.assertEqual(recipe.options["format"], "usda")

    def test_layer_order_is_deterministic(self) -> None:
        # Shot: group root prim, then departments (weak→strong) as sublayers so
        # they exist before placements, then the assembly + components referenced
        # into the layout layer (assembly before components).
        recipe = loader.load(_SHOT_RECIPE)
        kinds = [(l.kind, l.name) for l in recipe.layers]
        self.assertEqual(
            kinds,
            [
                ("prim", "SEQ010_SH020"),
                ("sublayer", "layout"),
                ("sublayer", "anim"),
                ("sublayer", "fx"),
                ("sublayer", "lighting"),
                ("reference", "ENV_forest"),
                ("reference", "hero_01"),
            ],
        )

    def test_variants_sorted_by_set_name(self) -> None:
        recipe = loader.load(_SHOT_RECIPE)
        comp = recipe.layers[-1].params["ref"]
        self.assertIsInstance(comp, RefSpec)
        self.assertEqual(
            comp.variants,
            (VariantSpec("lod", "hi"), VariantSpec("look", "damaged")),
        )

    def test_determinism_same_input_same_output(self) -> None:
        self.assertEqual(loader.load(_SHOT_RECIPE), loader.load(_SHOT_RECIPE))

    def test_component_defaults_version_latest(self) -> None:
        recipe = loader.load({"target": {"kind": "component"}, "components": [{"asset": "PROP_x"}]})
        self.assertEqual(recipe.layers[0].params["ref"].version, "latest")


class RejectInvalidRecipe(unittest.TestCase):
    def test_missing_target(self) -> None:
        with self.assertRaises(RecipeError):
            loader.load({"assembly": {"asset": "A"}})

    def test_bad_target_kind(self) -> None:
        with self.assertRaises(RecipeError):
            loader.load({"target": {"kind": "planet"}})

    def test_unknown_top_level_key(self) -> None:
        with self.assertRaises(RecipeError):
            loader.load({"target": {"kind": "shot"}, "bogus": 1})

    def test_bad_version_pattern(self) -> None:
        with self.assertRaises(RecipeError):
            loader.load({"target": {"kind": "assembly"}, "assembly": {"asset": "A", "version": "newest"}})

    def test_not_a_dict(self) -> None:
        with self.assertRaises(RecipeError):
            loader.load([1, 2, 3])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
