# USD contract check of a published version (USD strategy R3): warn only, never blocks.

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Sdf, UsdGeom

from features.folder_manager import tokens as tok
from features.folder_manager.project_config import ensure_project_config
from features.publisher.usd_publish_hooks import after_usd_publish
from features.usd_assembler.validate.publish_check import check_published_usd
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def _asset() -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=["Root"], bind_transforms=[_ID], rest_transforms=[_ID]),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
    )


class PublishCheck(unittest.TestCase):
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
        ensure_project_config(self.project)          # fps 24, 1.0 m, Y up
        self.folder = self.project / "assets/chara/UTAH/model/null"
        self.folder.mkdir(parents=True)

    def _layer(self, name: str, build) -> Path:
        path = self.folder / name
        layer = Sdf.Layer.CreateNew(str(path))
        build(layer)
        layer.Save()
        return path

    def test_the_light_export_passes_clean(self) -> None:
        res = publish_light_asset(_asset(), self.project, fmt="usda",
                                  dest_dir=self.folder, base_name="CHAR_GEO_UTAH_null")
        self.assertEqual(check_published_usd(res["version_root"], "CHAR_GEO_UTAH_null"), [])

    def test_non_portable_paths_are_reported(self) -> None:
        def build(layer):
            layer.defaultPrim = "UTAH"
            root = Sdf.PrimSpec(layer, "UTAH", Sdf.SpecifierDef, "Xform")
            root.referenceList.prependedItems = [Sdf.Reference("C:/proj/other.usda")]
            layer.subLayerPaths.append("..\\weak.usda")
            tex = Sdf.AttributeSpec(root, "inputs:file", Sdf.ValueTypeNames.Asset)
            tex.default = Sdf.AssetPath("$FLUX/tex/wood.tx")

        path = self._layer("CHAR_GEO_UTAH_null.usda", build)
        msgs = " | ".join(i.msg for i in check_published_usd(path, "CHAR_GEO_UTAH_null"))
        self.assertIn("chemin absolu", msgs)
        self.assertIn("antislash", msgs)
        self.assertIn("variable non resolue", msgs)       # asset attribute (texture)

    def test_asset_layer_root_must_be_the_name(self) -> None:
        def build(layer):
            Sdf.PrimSpec(layer, "CHAR_GEO_UTAH_null", Sdf.SpecifierDef, "Xform")
            layer.defaultPrim = "CHAR_GEO_UTAH_null"

        path = self._layer("CHAR_GEO_UTAH_null.usda", build)
        issues = check_published_usd(path, "CHAR_GEO_UTAH_null")
        self.assertTrue(any("au lieu de UTAH" in i.msg for i in issues))
        self.assertTrue(all(i.level == "warn" for i in issues))

    def test_look_layer_must_not_define_geometry_and_meshes_need_extent(self) -> None:
        def build(layer):
            layer.defaultPrim = "UTAH"
            root = Sdf.PrimSpec(layer, "UTAH", Sdf.SpecifierDef, "Xform")
            geo = Sdf.PrimSpec(root, "geo", Sdf.SpecifierDef, "Scope")
            Sdf.PrimSpec(geo, "body", Sdf.SpecifierDef, "Mesh")

        path = self._layer("CHAR_SHADING_UTAH_null.usda", build)
        msgs = " | ".join(i.msg for i in check_published_usd(path, "CHAR_SHADING_UTAH_null"))
        self.assertIn("couche look qui definit de la geometrie", msgs)
        self.assertIn("mesh sans extent", msgs)

    def test_units_and_fps_differing_from_the_project(self) -> None:
        def build(layer):
            layer.defaultPrim = "UTAH"
            Sdf.PrimSpec(layer, "UTAH", Sdf.SpecifierDef, "Xform")
            layer.pseudoRoot.SetInfo(UsdGeom.Tokens.metersPerUnit, 0.01)
            layer.startTimeCode, layer.endTimeCode = 1.0, 10.0
            layer.timeCodesPerSecond = 25.0

        path = self._layer("CHAR_GEO_UTAH_null.usda", build)
        msgs = " | ".join(i.msg for i in check_published_usd(path, "CHAR_GEO_UTAH_null"))
        self.assertIn("metersPerUnit 0.01 different du projet (1)", msgs)
        self.assertIn("fps 25 different du projet (24)", msgs)

    def test_hook_returns_issues_and_logs_them(self) -> None:
        def build(layer):
            Sdf.PrimSpec(layer, "WRONG", Sdf.SpecifierDef, "Xform")
            layer.defaultPrim = "WRONG"

        version = self.folder / "CHAR_GEO_UTAH_null_v001.usda"
        layer = Sdf.Layer.CreateNew(str(version))
        build(layer)
        layer.Save()
        out = after_usd_publish(self.folder, "CHAR_GEO_UTAH_null", ".usda", version)
        self.assertTrue(out["issues"])
        logs = json.loads((self.folder / "modif_logs.json").read_text(encoding="utf-8"))
        text = json.dumps(logs, ensure_ascii=False)
        self.assertIn("controle USD", text)
        self.assertIn("v001", text)

    def test_unreadable_file_never_raises(self) -> None:
        bad = self.folder / "broken.usda"
        bad.write_text("not usd at all", encoding="utf-8")
        issues = check_published_usd(bad, "CHAR_GEO_UTAH_null")
        self.assertEqual([i.level for i in issues], ["warn"])


if __name__ == "__main__":
    unittest.main()
