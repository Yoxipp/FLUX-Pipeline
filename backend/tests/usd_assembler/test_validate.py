# Unit tests for AssemblyValidator: defaultPrim / kind / dangling-instance checks.

from __future__ import annotations

import unittest

from pxr import Usd

from features.usd_assembler.io import stage_factory
from features.usd_assembler.validate.validator import AssemblyValidator, ERROR, WARN


def _good_component():
    stage = stage_factory.in_memory()
    prim = stage.DefinePrim("/CHAR_hero", "Xform")
    Usd.ModelAPI(prim).SetKind("component")
    prim.GetPayloads().AddPayload("geometry.usd")
    stage.SetDefaultPrim(prim)
    return stage


class ValidateAssembly(unittest.TestCase):
    def test_good_stage_has_no_errors(self) -> None:
        issues = AssemblyValidator().check(_good_component())
        self.assertFalse(AssemblyValidator.has_errors(issues))

    def test_missing_default_prim_is_error(self) -> None:
        stage = stage_factory.in_memory()
        stage.DefinePrim("/CHAR_hero", "Xform")  # never set as defaultPrim
        issues = AssemblyValidator().check(stage)
        self.assertTrue(AssemblyValidator.has_errors(issues))
        self.assertEqual(issues[0].level, ERROR)

    def test_missing_kind_is_error(self) -> None:
        stage = stage_factory.in_memory()
        prim = stage.DefinePrim("/CHAR_hero", "Xform")  # no kind
        stage.SetDefaultPrim(prim)
        issues = AssemblyValidator().check(stage)
        self.assertTrue(any(i.level == ERROR and "kind" in i.msg for i in issues))

    def test_dangling_instance_is_warning(self) -> None:
        stage = stage_factory.in_memory()
        root = stage.DefinePrim("/ENV_forest", "Xform")
        Usd.ModelAPI(root).SetKind("assembly")
        stage.SetDefaultPrim(root)
        stage.DefinePrim("/ENV_forest/tree_a", "Xform")  # instance with no ref
        issues = AssemblyValidator().check(stage)
        self.assertFalse(AssemblyValidator.has_errors(issues))
        self.assertTrue(any(i.level == WARN and i.prim == "/ENV_forest/tree_a" for i in issues))


if __name__ == "__main__":
    unittest.main()
