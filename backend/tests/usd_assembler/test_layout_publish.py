# USD_ASSEMBLER_V2 section 10 point 3: publish an assembly layout from DCC placements.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom

from features.folder_manager import tokens as tok
from features.usd_assembler import assembly_v2 as av
from features.usd_assembler import layout_publish as lpub
from features.usd_assembler.component_auto import refresh_component
from features.usd_assembler.library import build_library
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def _translate(x: float, y: float = 0.0, z: float = 0.0) -> list[float]:
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]


def _asset() -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=["Root"], bind_transforms=[_ID], rest_transforms=[_ID]),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
    )


class LayoutPublish(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["UTAH"] = "assets/chara/UTAH"
        tok.save_tokens(self.project, tokens)
        publish_light_asset(_asset(), self.project, fmt="usd",
                            dest_dir=self.project / "assets/chara/UTAH/model/null",
                            base_name="CHAR_GEO_UTAH_null")
        refresh_component(self.project, "UTAH")
        av.create_assembly(self.project, "TOWN")
        av.edit_assembly(self.project, "TOWN", [{"op": "add", "component": "UTAH", "count": 2}])   # v002

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _stage(self, entry: Path) -> Usd.Stage:
        return Usd.Stage.Open(str(entry))

    def _translation(self, stage: Usd.Stage, prim: str) -> Gf.Vec3d:
        return UsdGeom.Xformable(stage.GetPrimAtPath(prim)).GetLocalTransformation().ExtractTranslation()

    def test_publish_writes_layout_version_last_and_new_assembly_version(self) -> None:
        res = lpub.publish_layout(self.project, "TOWN", {
            "|TOWN|CHAR|UTAH_01": _translate(5), "CHAR/UTAH_02": _translate(0, 0, -3),
        }, user="adam", source="maya")
        self.assertEqual((res["layout_version"], res["version"]), ("v001", "v003"))
        parent = av.assembly_dir(self.project, "TOWN")
        self.assertEqual(res["layout"], parent / "layout" / "TOWN_layout_v001.usda")
        self.assertEqual(res["layout_last"], parent / "TOWN_layout_LAST.usda")
        self.assertEqual(res["warnings"], [])

        layer = Sdf.Layer.FindOrOpen(str(res["layout"]))
        spec = layer.GetPrimAtPath("/TOWN/CHAR/UTAH_01")
        self.assertEqual(spec.specifier, Sdf.SpecifierOver)
        self.assertEqual(sorted(spec.attributes.keys()), ["xformOp:transform", "xformOpOrder"])
        self.assertFalse(any(s.specifier == Sdf.SpecifierDef for s in [layer.GetPrimAtPath("/TOWN"),
                                                                       layer.GetPrimAtPath("/TOWN/CHAR")]))

        stage = self._stage(parent / "TOWN_LAST.usda")
        self.assertEqual(self._translation(stage, "/TOWN/CHAR/UTAH_01"), Gf.Vec3d(5, 0, 0))
        self.assertEqual(self._translation(stage, "/TOWN/CHAR/UTAH_02"), Gf.Vec3d(0, 0, -3))
        self.assertTrue(stage.GetPrimAtPath("/TOWN/CHAR/UTAH_01").IsInstance())

        town = next(a for a in build_library(self.project)["assemblies"] if a["name"] == "TOWN")
        self.assertEqual((town["layout_version"], Path(town["layout"]).name), ("v001", "TOWN_layout_LAST.usda"))

    def test_assembly_versions_freeze_their_layout(self) -> None:
        lpub.publish_layout(self.project, "TOWN", {"UTAH_01": _translate(1), "UTAH_02": _translate(2)})   # v003
        lpub.publish_layout(self.project, "TOWN", {"UTAH_01": _translate(7), "UTAH_02": _translate(2)})   # v004
        parent = av.assembly_dir(self.project, "TOWN")
        v3 = self._stage(parent / "TOWN_v003" / "TOWN.usda")
        self.assertEqual(self._translation(v3, "/TOWN/CHAR/UTAH_01"), Gf.Vec3d(1, 0, 0))
        payload = Sdf.Layer.FindOrOpen(str(parent / "TOWN_v004" / "TOWN_payload.usda"))
        self.assertEqual(list(payload.subLayerPaths), ["../layout/TOWN_layout_v002.usda", "./TOWN_contents.usda"])
        # A later contents edit keeps the newest layout vNNN, not the LAST pointer.
        av.edit_assembly(self.project, "TOWN", [{"op": "duplicate", "name": "UTAH_01"}])
        payload = Sdf.Layer.FindOrOpen(str(parent / "TOWN_v005" / "TOWN_payload.usda"))
        self.assertEqual(list(payload.subLayerPaths)[0], "../layout/TOWN_layout_v002.usda")
        self.assertEqual(self._translation(self._stage(parent / "TOWN_LAST.usda"), "/TOWN/CHAR/UTAH_01"),
                         Gf.Vec3d(7, 0, 0))

    def test_unknown_missing_and_errors(self) -> None:
        res = lpub.publish_layout(self.project, "TOWN", {"UTAH_01": _translate(1), "CHAR/GHOST_01": _ID})
        self.assertEqual(len(res["warnings"]), 2)
        self.assertIn("GHOST_01", res["warnings"][0])
        self.assertIn("UTAH_02", res["warnings"][1])
        with self.assertRaises(ValueError):
            lpub.publish_layout(self.project, "TOWN", {"GHOST_01": _ID})
        with self.assertRaises(ValueError):
            lpub.publish_layout(self.project, "TOWN", {"UTAH_01": [1, 2, 3]})
        with self.assertRaises(ValueError):
            lpub.publish_layout(self.project, "NOPE", {"UTAH_01": _ID})
        # The failed matrix did not leave a reserved layout version behind.
        self.assertEqual(sorted(p.name for p in (av.assembly_dir(self.project, "TOWN") / "layout").iterdir()),
                         ["TOWN_layout_v001.usda"])


if __name__ == "__main__":
    unittest.main()
