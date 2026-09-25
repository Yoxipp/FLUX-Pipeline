# ADR 0010: assembled roots reference published layers with paths relative to the
# written root (references, payloads, component sublayers), and the validator
# warns when an absolute or backslashed asset path slips through.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Sdf, Usd

from features.usd_assembler.resolve.base import ResolvedAsset
from features.usd_assembler.usd_assembler_core import assemble
from features.usd_assembler.validate.validator import AssemblyValidator


class _AbsResolver:
    """Resolve every asset to an absolute published path under *root*."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def resolve(self, asset: str, version: str = "latest", dept=None) -> ResolvedAsset:
        path = self._root / "assets" / asset / "usd" / f"{asset}_LAST.usda"
        return ResolvedAsset(path=path, default_prim=asset, version="v001")


_ASSEMBLY = {
    "target": {"kind": "assembly", "asset": "ENV_forest"},
    "components": [{"asset": "Tree_pine", "instance": "tree_a"}],
}
_COMPONENT = {"target": {"kind": "component", "asset": "CHAR_hero"}}


def _asset_paths(layer: "Sdf.Layer") -> list[str]:
    found: list[str] = list(layer.subLayerPaths)

    def _visit(path):
        spec = layer.GetPrimAtPath(path)
        if spec is None:
            return
        for item in list(spec.referenceList.GetAddedOrExplicitItems()) + list(
            spec.payloadList.GetAddedOrExplicitItems()
        ):
            found.append(item.assetPath)

    layer.Traverse(Sdf.Path.absoluteRootPath, _visit)
    return found


class PortablePaths(unittest.TestCase):
    def _assemble(self, recipe: dict, d: str):
        root = Path(d)
        return assemble(recipe, resolver=_AbsResolver(root), dest_dir=root / "sets" / "out")

    def test_reference_is_relative_to_root(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = self._assemble(_ASSEMBLY, d)
            paths = _asset_paths(Sdf.Layer.FindOrOpen(str(result.root)))
            self.assertEqual(paths, ["../../assets/Tree_pine/usd/Tree_pine_LAST.usda"])
            self.assertFalse(any("path" in i.msg for i in result.issues))

    def test_payload_is_relative_to_root(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = self._assemble(_COMPONENT, d)
            paths = _asset_paths(Sdf.Layer.FindOrOpen(str(result.root)))
            self.assertEqual(paths, ["../../assets/CHAR_hero/usd/CHAR_hero_LAST.usda"])

    def test_validator_warns_on_absolute_and_backslash(self) -> None:
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/ENV", "Xform")
        Usd.ModelAPI(prim).SetKind("assembly")
        stage.SetDefaultPrim(prim)
        stage.DefinePrim("/ENV/a", "Xform").GetReferences().AddReference("C:/proj/a.usd")
        stage.DefinePrim("/ENV/b", "Xform").GetReferences().AddReference("sub\\b.usd")
        stage.DefinePrim("/ENV/c", "Xform").GetReferences().AddReference("../c.usd")
        msgs = [i.msg for i in AssemblyValidator().check(stage) if i.level == "warn"]
        self.assertTrue(any("absolute" in m and "a.usd" in m for m in msgs))
        self.assertTrue(any("backslashes" in m for m in msgs))
        self.assertFalse(any("c.usd" in m for m in msgs))


if __name__ == "__main__":
    unittest.main()
