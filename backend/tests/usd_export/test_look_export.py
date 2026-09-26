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
from features.usd_export.look_export import assign_info, author_look_layer, publish_look_asset


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


def _variant_export(folder: Path) -> Path:
    """Solaris-like export (ADR 0035): Material Library with three materials, the beak
    assigned before the variant block, the body assigned per variant (red / blue)."""
    folder.mkdir(parents=True, exist_ok=True)
    src = folder / "export.usda"
    stage = Usd.Stage.CreateNew(str(src))
    UsdGeom.Xform.Define(stage, "/Root")
    for name in ("body", "beak"):
        mesh = UsdGeom.Mesh.Define(stage, f"/Root/{name}")
        mesh.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
        mesh.CreateFaceVertexCountsAttr([3])
        mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
    mats = {}
    for name in ("red", "blue", "horn"):
        mats[name] = UsdShade.Material.Define(stage, f"/materials/{name}")
        shader = UsdShade.Shader.Define(stage, f"/materials/{name}/surface")
        shader.CreateIdAttr("UsdPreviewSurface")
        mats[name].CreateSurfaceOutput().ConnectToSource(
            shader.CreateOutput("surface", Sdf.ValueTypeNames.Token))
    beak = stage.GetPrimAtPath("/Root/beak")
    UsdShade.MaterialBindingAPI.Apply(beak)
    UsdShade.MaterialBindingAPI(beak).Bind(mats["horn"])
    # A variant set that changes no binding is not an assignment.
    lod = stage.GetPrimAtPath("/Root").GetVariantSets().AddVariantSet("lod")
    for v in ("hi", "lo"):
        lod.AddVariant(v)
    lod.SetVariantSelection("hi")
    vset = stage.GetPrimAtPath("/Root").GetVariantSets().AddVariantSet("material_variants")
    for v in ("red", "blue"):
        vset.AddVariant(v)
        vset.SetVariantSelection(v)
        with vset.GetVariantEditContext():
            body = stage.GetPrimAtPath("/Root/body")
            UsdShade.MaterialBindingAPI.Apply(body)
            UsdShade.MaterialBindingAPI(body).Bind(mats[v])
    vset.SetVariantSelection("blue")
    stage.GetRootLayer().Save()
    return src


def _bound(stage: Usd.Stage, path: str) -> str:
    mat, _ = UsdShade.MaterialBindingAPI(stage.GetPrimAtPath(path)).ComputeBoundMaterial()
    return str(mat.GetPath()) if mat else ""


class AssignVariants(unittest.TestCase):
    """ADR 0035: one Solaris export -> shaders layer + assign layer with a variantSet."""

    def test_export_is_split_into_shaders_and_assign_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            res = author_look_layer(_variant_export(root / "src"), root / "v001",
                                    "CHAR_SHADING_DAVID_null", root_name="DAVID")
            self.assertEqual((res["assign_variants"], res["assign_default"]), (["blue", "red"], "blue"))
            self.assertEqual(res["materials"], 3)

            # Shaders layer: every material, no binding, no variant.
            mtl = Sdf.Layer.FindOrOpen(str(res["mtl"]))
            self.assertEqual(sorted(mtl.GetPrimAtPath("/DAVID/mtl").nameChildren.keys()),
                             ["blue", "horn", "red"])
            self.assertIsNone(mtl.GetPrimAtPath("/DAVID/geo"))
            # Assign layer: only the assign variantSet, the beak outside it.
            assign = Sdf.Layer.FindOrOpen(str(res["assign"]))
            self.assertEqual(list(assign.GetPrimAtPath("/DAVID").variantSets.keys()), ["assign"])
            self.assertIsNotNone(assign.GetPrimAtPath("/DAVID/geo/render/beak"))
            self.assertIsNone(assign.GetPrimAtPath("/DAVID/geo/render/body"))

            stage = Usd.Stage.Open(str(res["root"]))
            UsdGeom.Mesh.Define(stage, "/DAVID/geo/render/body")      # the model layer's job
            UsdGeom.Mesh.Define(stage, "/DAVID/geo/render/beak")
            self.assertEqual(_bound(stage, "/DAVID/geo/render/body"), "/DAVID/mtl/blue")
            stage.GetPrimAtPath("/DAVID").GetVariantSet("assign").SetVariantSelection("red")
            self.assertEqual(_bound(stage, "/DAVID/geo/render/body"), "/DAVID/mtl/red")
            self.assertEqual(_bound(stage, "/DAVID/geo/render/beak"), "/DAVID/mtl/horn")
            self.assertEqual(assign_info(res["root"]), {"variants": ["blue", "red"], "default": "blue"})

    def test_one_flattened_export_per_variant(self) -> None:
        """Houdini writes each assign variant as its own flattened stage (the
        references of the scene composed by Houdini): same shaders + assign result."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _variant_export(root / "src")
            files = {}
            for v in ("red", "blue"):
                stage = Usd.Stage.Open(str(src))
                stage.GetPrimAtPath("/Root").GetVariantSet("material_variants").SetVariantSelection(v)
                out = root / "src" / f"export__{v}.usda"
                stage.Flatten().Export(str(out))
                files[v] = out
            res = author_look_layer(files["red"], root / "v001", "CHAR_SHADING_DAVID_null",
                                    root_name="DAVID", variant_sources=files, variant_default="blue")
            self.assertEqual((res["assign_variants"], res["assign_default"]), (["red", "blue"], "blue"))
            stage = Usd.Stage.Open(str(res["root"]))
            UsdGeom.Mesh.Define(stage, "/DAVID/geo/render/body")
            UsdGeom.Mesh.Define(stage, "/DAVID/geo/render/beak")
            self.assertEqual(_bound(stage, "/DAVID/geo/render/body"), "/DAVID/mtl/blue")
            stage.GetPrimAtPath("/DAVID").GetVariantSet("assign").SetVariantSelection("red")
            self.assertEqual(_bound(stage, "/DAVID/geo/render/body"), "/DAVID/mtl/red")
            self.assertEqual(_bound(stage, "/DAVID/geo/render/beak"), "/DAVID/mtl/horn")

    def test_no_material_error_says_what_the_export_holds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "empty.usda"
            stage = Usd.Stage.CreateNew(str(src))
            UsdGeom.Mesh.Define(stage, "/Root/body")
            stage.GetRootLayer().Save()
            with self.assertRaisesRegex(ValueError, "racines : Root.*Mesh"):
                author_look_layer(src, Path(tmp) / "v001", "CHAR_SHADING_DAVID_null", root_name="DAVID")

    def test_layer_break_export_binds_the_asset_paths(self) -> None:
        """2026-09-26 (UTAH): Layer Break before the look, so no geometry in the
        export: only "over" prims at /Utah/geo/render/... with the Assign Material
        bindings, per variant (mtl: Hunter / Victim)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {}
            for v, mat in (("Hunter", "red"), ("Victim", "blue")):
                stage = Usd.Stage.CreateInMemory()
                for name in ("red", "blue", "horn"):
                    m = UsdShade.Material.Define(stage, f"/materials/{name}")
                    UsdShade.Shader.Define(stage, f"/materials/{name}/surface").CreateIdAttr("UsdPreviewSurface")
                for rel, target in (("geo/render/body", mat), ("geo/render/beak", "horn"),
                                    ("geo/render/feathers", mat)):
                    over = stage.OverridePrim(f"/Utah/{rel}")
                    UsdShade.MaterialBindingAPI.Apply(over)
                    UsdShade.MaterialBindingAPI(over).Bind(
                        UsdShade.Material(stage.GetPrimAtPath(f"/materials/{target}")))
                out = root / f"export__{v}.usda"
                stage.GetRootLayer().Export(str(out))
                files[v] = out
            res = author_look_layer(files["Hunter"], root / "v001", "CHAR_SHADING_UTAH_null",
                                    root_name="UTAH", variant_sources=files, variant_default="Hunter")
            self.assertGreater(res["bindings"], 0)
            stage = Usd.Stage.Open(str(res["root"]))
            for rel in ("geo/render/body", "geo/render/beak", "geo/render/feathers"):
                UsdGeom.Mesh.Define(stage, f"/UTAH/{rel}")
            self.assertEqual(_bound(stage, "/UTAH/geo/render/body"), "/UTAH/mtl/red")
            self.assertEqual(_bound(stage, "/UTAH/geo/render/feathers"), "/UTAH/mtl/red")
            stage.GetPrimAtPath("/UTAH").GetVariantSet("assign").SetVariantSelection("Victim")
            self.assertEqual(_bound(stage, "/UTAH/geo/render/body"), "/UTAH/mtl/blue")
            self.assertEqual(_bound(stage, "/UTAH/geo/render/beak"), "/UTAH/mtl/horn")

    def test_referenced_variant_sets_are_not_assignments(self) -> None:
        """A component brought by FLUX Import carries its own variant sets: never read
        as the look's assignments (the classic single look layer is written)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comp = root / "comp.usda"
            cst = Usd.Stage.CreateNew(str(comp))
            UsdGeom.Mesh.Define(cst, "/C/body")
            vset = cst.DefinePrim("/C").GetVariantSets().AddVariantSet("look")
            for v in ("a", "b"):
                mat = UsdShade.Material.Define(cst, f"/C/mtl/{v}")
                vset.AddVariant(v)
                vset.SetVariantSelection(v)
                with vset.GetVariantEditContext():
                    body = cst.GetPrimAtPath("/C/body")
                    UsdShade.MaterialBindingAPI.Apply(body)
                    UsdShade.MaterialBindingAPI(body).Bind(mat)
            cst.GetRootLayer().Save()
            src = root / "src" / "export.usda"
            src.parent.mkdir()
            stage = Usd.Stage.CreateNew(str(src))
            stage.DefinePrim("/Root").GetReferences().AddReference(str(comp), "/C")
            stage.GetRootLayer().Save()
            res = author_look_layer(src, root / "v001", "CHAR_SHADING_DAVID_null", root_name="DAVID")
            self.assertNotIn("assign_variants", res)
            self.assertEqual(assign_info(res["root"]), {})


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

    def test_assign_variants_reach_the_component_and_the_importer(self) -> None:
        """ADR 0035: one publish, variantSet "assign" selectable on the asset, one
        FLUX Import row per variant (the one just checked wins)."""
        from features.usd_assembler import component_auto as ca

        self._publish_geo()
        dest = self.project / self._REL / "shading" / "null"
        res = publish_look_asset(_variant_export(Path(self._tmp.name) / "src"), self.project,
                                 fmt="usda", dest_dir=dest, base_name="CHAR_SHADING_DAVID_null")
        self.assertEqual(res["assign_variants"], ["blue", "red"])
        version = add_proposed(self.project, "DAVID")["version"]
        entry = self.project / self._REL / "usd" / f"DAVID_{version}" / "DAVID.usda"
        self.assertEqual(ca.entry_variant_sets(entry)["assign"], ["blue", "red"])

        stage = Usd.Stage.Open(str(self.project / self._REL / "usd" / "DAVID_LAST.usda"))
        self.assertEqual(_bound(stage, "/DAVID/geo/render/body"), "/DAVID/mtl/blue")
        stage.GetPrimAtPath("/DAVID").GetVariantSet("assign").SetVariantSelection("red")
        self.assertEqual(_bound(stage, "/DAVID/geo/render/body"), "/DAVID/mtl/red")

        got = ca.component_files(self.project, "DAVID")
        rows = {f["id"]: f for f in got["files"] if f.get("assign_of")}
        look = next(iter(rows.values()))["assign_of"]
        blue, red = f"{look}@assign:blue", f"{look}@assign:red"
        self.assertEqual(sorted(rows), [blue, red])
        self.assertEqual((got["active"][blue], got["active"][red]), (True, False))   # default
        self.assertEqual({rows[blue]["variant_set"], rows[red]["variant"]}, {"assign", "red"})
        before = dict(got["active"])
        got = ca.component_files(self.project, "DAVID", active={**before, red: True},
                                 previous=before)
        self.assertEqual((got["active"][blue], got["active"][red]), (False, True))

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
