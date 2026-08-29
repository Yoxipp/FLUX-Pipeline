# Unit tests for structure/ conventions (naming, kinds, layout). No pxr.

from __future__ import annotations

import unittest

from features.usd_assembler.structure.kinds import KindPolicy
from features.usd_assembler.structure.layout import DEFAULT_DEPARTMENTS, LayerNaming
from features.usd_assembler.structure.naming import PrimNamer, sanitize_token


class Naming(unittest.TestCase):
    def setUp(self) -> None:
        self.namer = PrimNamer()

    def test_legal_identity_preserved(self) -> None:
        self.assertEqual(sanitize_token("CHAR_hero"), "CHAR_hero")

    def test_invalid_chars_replaced(self) -> None:
        self.assertEqual(sanitize_token("env-forest.01"), "env_forest_01")

    def test_leading_digit_prefixed(self) -> None:
        self.assertEqual(sanitize_token("01_hero"), "_01_hero")

    def test_empty_rejected(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_token("")

    def test_prim_path_root_and_nested(self) -> None:
        self.assertEqual(self.namer.prim_path("CHAR_hero"), "/CHAR_hero")
        self.assertEqual(
            self.namer.prim_path("hero", parent="/ENV_forest"), "/ENV_forest/hero"
        )


class Kinds(unittest.TestCase):
    def test_default_map(self) -> None:
        policy = KindPolicy()
        self.assertEqual(policy.kind_for("component"), "component")
        self.assertEqual(policy.kind_for("assembly"), "assembly")
        self.assertEqual(policy.kind_for("shot"), "group")

    def test_config_override(self) -> None:
        policy = KindPolicy({"shot": "assembly"})
        self.assertEqual(policy.kind_for("shot"), "assembly")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(KeyError):
            KindPolicy().kind_for("planet")


class Layout(unittest.TestCase):
    def test_default_department_order(self) -> None:
        self.assertEqual(LayerNaming().department_order(), DEFAULT_DEPARTMENTS)

    def test_config_department_order(self) -> None:
        naming = LayerNaming({"departments": ["layout", "lighting"]})
        self.assertEqual(naming.department_order(), ("layout", "lighting"))

    def test_filename_plain_and_dept(self) -> None:
        naming = LayerNaming()
        self.assertEqual(naming.filename("CHAR_hero"), "CHAR_hero.usda")
        self.assertEqual(
            naming.filename("SEQ010_SH020", "layout"), "SEQ010_SH020_layout.usda"
        )

    def test_format_from_config(self) -> None:
        self.assertEqual(LayerNaming({"format": "usdc"}).filename("A"), "A.usdc")

    def test_geometry_filename(self) -> None:
        self.assertEqual(LayerNaming().geometry_filename(), "geometry.usd")

    def test_bad_format_rejected(self) -> None:
        with self.assertRaises(ValueError):
            LayerNaming({"format": "abc"})


if __name__ == "__main__":
    unittest.main()
