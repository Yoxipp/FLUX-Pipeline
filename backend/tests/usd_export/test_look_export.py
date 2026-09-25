# A1b (ADR 0019): the look department layer written from a DCC material export.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Sdf, Usd, UsdGeom, UsdShade

from features.usd_assembler.component_auto import add_proposed
from features.folder_manager import tokens as tok
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset
from features.usd_export.look_export import author_look_layer, publish_look_asset


def _source_export(folder: Path, *, with_tx: bool = True) -> Path:
    """A throwaway DCC export: one mesh bound to one material with a texture.

    Mimics mayaUSDExport / a Houdini USD ROP: arbitrary prim paths, textures next to
    the scene, materials under /Looks.
    """
    tex_dir = folder / "tex"
    tex_dir.mkdir(parents=True, exist_ok=True)
    (tex_dir / "diffuse.png").write_bytes(b"png")
    if with_tx:
        (tex_dir / "diffuse.tx").write_bytes(b"tx")

    src = folder / "export.usda"
    stage = Usd.Stage.CreateNew(str(src))
    UsdGeom.Xform.Define(stage, "/Root")
    mesh = UsdGeom.Mesh.Define(stage, "/Root/body")
    mesh.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    mesh.CreateFaceVertexCountsAttr([3])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2])

    material = UsdShade.Material.Define(stage, "/Looks/skin")
    shader = UsdShade.Shader.Define(stage, "/Looks/skin/surface")
    shader.CreateIdAttr("UsdPreviewSurface")
    tex = UsdShade.Shader.Define(stage, "/Looks/skin/tex")
    tex.CreateIdAttr("UsdUVTexture")
    tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath("tex/diffuse.png"))
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        tex.CreateOutput("rgb", Sdf.ValueTypeNames.Float3))
    material.CreateSurfaceOutput().ConnectToSource(
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token))
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim())
    UsdShade.MaterialBindingAPI(mesh.GetPrim()).Bind(material)
    stage.GetRootLayer().Save()
    return src


class LookLayer(unittest.TestCase):
    def test_materials_land_under_mtl_and_bind_the_flux_mesh_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _source_export(root / "src")
            dest = root / "CHAR_SHADING_DAVID_null_v001"
            res = author_look_layer(src, dest, "CHAR_SHADING_DAVID_null", root_name="DAVID")

            self.assertTrue(res["look"].is_file())
            self.assertTrue(res["root"].is_file())
            self.assertEqual(res["materials"], 1)
            self.assertEqual(res["bindings"], 1)

            stage = Usd.Stage.Open(str(res["root"]))
            self.assertEqual(stage.GetDefaultPrim().GetName(), "DAVID")
            mat = stage.GetPrimAtPath("/DAVID/mtl/skin")
            self.assertTrue(mat and mat.IsA(UsdShade.Material))
            # The binding lands on the prim path the model layer authors (ADR 0019).
            mesh = stage.GetPrimAtPath("/DAVID/geo/render/body")
            self.assertTrue(mesh)
            bound, _ = UsdShade.MaterialBindingAPI(mesh).ComputeBoundMaterial()
            self.assertEqual(bound.GetPath(), Sdf.Path("/DAVID/mtl/skin"))

    def test_no_geometry_is_defined_in_a_look_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _source_export(root / "src")
            dest = root / "v001"
            res = author_look_layer(src, dest, "CHAR_SHADING_DAVID_null", root_name="DAVID")
            layer = Sdf.Layer.FindOrOpen(str(res["look"]))
            defined = [str(s.path) for s in _specs(layer)
                       if s.specifier == Sdf.SpecifierDef and s.typeName == "Mesh"]
            self.assertEqual(defined, [])
            # The asset root belongs to the model layer: the look only overrides it.
            self.assertEqual(layer.GetPrimAtPath("/DAVID").specifier, Sdf.SpecifierOver)

    def test_texture_points_at_the_conformed_tx_relative_to_the_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _source_export(root / "src", with_tx=True)
            dest = root / "v001"
            res = author_look_layer(src, dest, "CHAR_SHADING_DAVID_null", root_name="DAVID")
            self.assertEqual(res["textures"], 1)
            path = _texture_path(res["look"])
            self.assertTrue(path.endswith(".tx"), path)
            self.assertFalse(Path(path).is_absolute(), path)
            self.assertTrue((dest / path).resolve().is_file())

    def test_texture_falls_back_to_the_source_image_without_a_tx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _source_export(root / "src", with_tx=False)
            dest = root / "v001"
            res = author_look_layer(src, dest, "CHAR_SHADING_DAVID_null", root_name="DAVID")
            self.assertTrue(_texture_path(res["look"]).endswith(".png"))

    def test_an_export_without_material_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "empty.usda"
            stage = Usd.Stage.CreateNew(str(src))
            UsdGeom.Mesh.Define(stage, "/Root/body")
            stage.GetRootLayer().Save()
            with self.assertRaises(ValueError):
                author_look_layer(src, root / "v001", "CHAR_SHADING_DAVID_null", root_name="DAVID")


class LookPublish(unittest.TestCase):
    """The look publish lands in the token tree and feeds the asset (component)."""

    _ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    _REL = "assets/chara/DAVID"

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "1"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["DAVID"] = self._REL
        tok.save_tokens(self.project, tokens)

    def _publish_geo(self) -> None:
        asset = LightAsset(
            asset="tmp",
            skeleton=SkeletonData(joints=["Root"], bind_transforms=[self._ID],
                                  rest_transforms=[self._ID]),
            meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                             face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
        )
        publish_light_asset(asset, self.project, fmt="usda",
                            dest_dir=self.project / self._REL / "model" / "null",
                            base_name="CHAR_GEO_DAVID_null", user="adam")
        add_proposed(self.project, "DAVID", ["GEO", "SHADING"])   # created by hand (ADR 0023)

    def test_look_publish_feeds_the_component_between_model_and_rig(self) -> None:
        self._publish_geo()
        src = _source_export(Path(self._tmp.name) / "src")
        dest = self.project / self._REL / "shading" / "null"
        res = publish_look_asset(src, self.project, fmt="usda", dest_dir=dest,
                                 base_name="CHAR_SHADING_DAVID_null", user="adam")

        self.assertEqual(res["version"], "v001")
        self.assertTrue((dest / "CHAR_SHADING_DAVID_null_v001"
                         / "CHAR_SHADING_DAVID_null_look.usda").is_file())
        self.assertTrue((dest / "CHAR_SHADING_DAVID_null_LAST.usda").is_file())
        self.assertIsNone(res["component"])          # a new publish is proposed, never added
        res["component"] = add_proposed(self.project, "DAVID")["version"]
        # A look carries no render mesh: no proxy file may be written beside it.
        self.assertEqual(list((dest / "CHAR_SHADING_DAVID_null_v001").glob("*.proxy.usda")), [])

        usd_dir = self.project / self._REL / "usd"
        payload = Sdf.Layer.FindOrOpen(str(usd_dir / f"DAVID_{res['component']}"
                                           / "DAVID_payload.usda"))
        self.assertEqual(list(payload.subLayerPaths), ["./DAVID_look.usda", "./DAVID_model.usda"])

        stage = Usd.Stage.Open(str(usd_dir / "DAVID_LAST.usda"))
        mesh = stage.GetPrimAtPath("/DAVID/geo/render/body")
        self.assertTrue(mesh.IsValid())
        bound, _ = UsdShade.MaterialBindingAPI(mesh).ComputeBoundMaterial()
        self.assertEqual(bound.GetPath(), Sdf.Path("/DAVID/mtl/skin"))

    def test_a_non_look_base_is_refused(self) -> None:
        src = _source_export(Path(self._tmp.name) / "src2")
        with self.assertRaises(ValueError):
            publish_look_asset(src, self.project, fmt="usda",
                               dest_dir=self.project / self._REL / "model" / "null",
                               base_name="CHAR_GEO_DAVID_null")


def _specs(layer: Sdf.Layer):
    out = []

    def walk(spec):
        out.append(spec)
        for child in spec.nameChildren:
            walk(child)

    for prim in layer.rootPrims:
        walk(prim)
    return out


def _texture_path(look: Path) -> str:
    stage = Usd.Stage.Open(str(look))
    shader = UsdShade.Shader(stage.GetPrimAtPath("/DAVID/mtl/skin/tex"))
    return shader.GetInput("file").Get().path


if __name__ == "__main__":
    unittest.main()
