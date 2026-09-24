# extentsHint on product entries (USD strategy R2): a component / assembly shows a
# correct bound while its payload is unloaded.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Sdf, Usd, UsdGeom

from features.folder_manager import tokens as tok
from features.usd_assembler import assembly_v2 as av
from features.usd_assembler.component_auto import add_proposed
from features.usd_assembler.extents import compute_extents_hint
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def _asset() -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=["Root"], bind_transforms=[_ID], rest_transforms=[_ID]),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (2, 0, 0), (2, 3, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
    )


def _hint(entry: Path):
    layer = Sdf.Layer.FindOrOpen(str(entry))
    spec = layer.GetPrimAtPath(layer.defaultPrim)
    attr = spec.attributes.get("extentsHint")
    return None if attr is None else attr.default


class ExtentsHint(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "0"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["UTAH"] = "assets/chara/UTAH"
        tok.save_tokens(self.project, tokens)
        publish_light_asset(_asset(), self.project, fmt="usda",
                            dest_dir=self.project / "assets/chara/UTAH/model/null",
                            base_name="CHAR_GEO_UTAH_null")
        add_proposed(self.project, "UTAH", ["GEO"])
        self.component = self.project / "assets/chara/UTAH/usd/UTAH_LAST.usda"

    def _entry(self, last: Path) -> Path:
        layer = Sdf.Layer.FindOrOpen(str(last))
        return (last.parent / layer.subLayerPaths[0]).resolve()

    def test_component_entry_carries_the_geometry_bound(self) -> None:
        hint = _hint(self._entry(self.component))
        self.assertIsNotNone(hint)
        # default purpose: the mesh spans (0,0,0) .. (2,3,0)
        self.assertEqual(tuple(hint[0]), (0.0, 0.0, 0.0))
        self.assertEqual(tuple(hint[1]), (2.0, 3.0, 0.0))

    def test_unloaded_component_uses_the_hint(self) -> None:
        stage = Usd.Stage.Open(str(self.component), Usd.Stage.LoadNone)
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_], useExtentsHint=True)
        rng = cache.ComputeWorldBound(stage.GetDefaultPrim()).ComputeAlignedRange()
        self.assertEqual(tuple(rng.GetMax()), (2.0, 3.0, 0.0))

    def test_assembly_bound_comes_from_component_hints(self) -> None:
        av.create_assembly(self.project, "TOWN")
        av.edit_assembly(self.project, "TOWN", [{"op": "add", "component": "UTAH"}])
        last = av.assembly_dir(self.project, "TOWN") / "TOWN_LAST.usda"
        hint = _hint(self._entry(last))
        self.assertIsNotNone(hint)
        self.assertEqual(tuple(hint[1]), (2.0, 3.0, 0.0))

    def test_empty_or_missing_layer_gives_no_hint(self) -> None:
        self.assertIsNone(compute_extents_hint(self.project / "nope.usda"))
        empty = self.project / "empty.usda"
        layer = Sdf.Layer.CreateNew(str(empty))
        Sdf.PrimSpec(layer, "X", Sdf.SpecifierDef, "Xform")
        layer.defaultPrim = "X"
        layer.Save()
        self.assertIsNone(compute_extents_hint(empty))


if __name__ == "__main__":
    unittest.main()
