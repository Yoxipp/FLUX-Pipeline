# Two meshes with the same leaf name: model layer and look layer name them the same
# way, so each binding lands on its own mesh (V9-01, was "last binding wins").

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdShade

from features.usd_assembler.structure.naming import sanitize_token
from features.usd_export.contract import mesh_prim_names
from features.usd_export.look_export import author_look_layer


def _names(items):
    return mesh_prim_names(items, sanitize_token)


class NamingRule(unittest.TestCase):
    def test_unique_leaf_names_are_kept(self) -> None:
        self.assertEqual(_names([("body", "|a|body"), ("eyes", "|a|eyes")]), ["body", "eyes"])

    def test_same_leaf_takes_the_shortest_unique_path_tail(self) -> None:
        self.assertEqual(_names([("body", "|charA|geo|body"), ("body", "|charB|geo|body"),
                                 ("eyes", "|charA|eyes")]),
                         ["charA_geo_body", "charB_geo_body", "eyes"])
        self.assertEqual(_names([("body", "/grpA/body"), ("body", "/grpB/body")]),
                         ["grpA_body", "grpB_body"])

    def test_maya_and_usd_paths_give_the_same_names(self) -> None:
        maya = _names([("body", "|ns:grpA|ns:body"), ("body", "|grpB|body")])
        usd = _names([("body", "/grpA/body"), ("body", "/grpB/body")])
        self.assertEqual(maya, usd)

    def test_without_path_a_suffix_is_added_instead_of_overwriting(self) -> None:
        self.assertEqual(_names([("body", ""), ("body", "")]), ["body", "body_2"])


class LookBindsEachMesh(unittest.TestCase):
    def test_two_meshes_named_body_keep_their_own_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "export.usda"
            stage = Usd.Stage.CreateNew(str(src))
            for grp, mat_name in (("grpA", "red"), ("grpB", "blue")):
                mesh = UsdGeom.Mesh.Define(stage, f"/{grp}/body")
                mesh.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
                mat = UsdShade.Material.Define(stage, f"/Looks/{mat_name}")
                shader = UsdShade.Shader.Define(stage, f"/Looks/{mat_name}/surface")
                shader.CreateIdAttr("UsdPreviewSurface")
                mat.CreateSurfaceOutput().ConnectToSource(
                    shader.CreateOutput("surface", Sdf.ValueTypeNames.Token))
                UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim())
                UsdShade.MaterialBindingAPI(mesh.GetPrim()).Bind(mat)
            stage.GetRootLayer().Save()

            res = author_look_layer(src, root / "v001", "CHAR_SHADING_DAVID_null", root_name="DAVID")
            self.assertEqual(res["bindings"], 2)
            look = Usd.Stage.Open(str(res["root"]))
            for grp, mat_name in (("grpA", "red"), ("grpB", "blue")):
                prim = look.GetPrimAtPath(f"/DAVID/geo/render/{grp}_body")
                rel = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
                self.assertEqual(rel.GetTargets(), [Sdf.Path(f"/DAVID/mtl/{mat_name}")])


if __name__ == "__main__":
    unittest.main()
