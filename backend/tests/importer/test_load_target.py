# V4 (ADR 0019 points 5 and 7): "Ouvrir dans..." proposes what the pipeline loads.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Sdf

from features.folder_manager import tokens as tok
from features.importer.load_target import delete_legacy_file, is_legacy_file, legacy_files, load_targets
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_REL = "assets/chara/DINGO"


def _geo() -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=["Root"], bind_transforms=[_ID], rest_transforms=[_ID]),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
    )


class LoadTargets(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "0"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["DINGO"] = _REL
        tok.save_tokens(self.project, tokens)
        self.pub = publish_light_asset(_geo(), self.project, fmt="usda",
                                       dest_dir=self.project / _REL / "model" / "null",
                                       base_name="CHAR_GEO_DINGO_null", user="adam")
        self.asset_last = self.project / _REL / "usd" / "DINGO_LAST.usda"

    def test_a_department_layer_proposes_the_asset_first(self) -> None:
        r = load_targets(self.project, self.pub["root"])
        self.assertEqual(r["what"], "layer")
        self.assertEqual([t["primary"] for t in r["targets"]], [True, False])
        self.assertEqual(r["targets"][0]["rel_path"], f"{_REL}/usd/DINGO_LAST.usda")
        self.assertEqual(r["targets"][1]["label"], "Couche seule")

    def test_a_layer_version_proposes_the_asset_version_that_uses_it(self) -> None:
        r = load_targets(self.project, self.pub["version_root"])
        self.assertIn("v001", r["targets"][0]["label"])
        self.assertTrue(r["targets"][0]["rel_path"].endswith("DINGO_v001/DINGO.usda"))

    def test_the_asset_itself_opens_as_is(self) -> None:
        r = load_targets(self.project, self.asset_last)
        self.assertEqual((r["what"], len(r["targets"])), ("asset", 1))

    def test_an_old_constructor_file_is_never_proposed(self) -> None:
        old = self.project / "usd" / "assembly" / "CHAR_GEO_DINGO_null.usda"
        old.parent.mkdir(parents=True)
        layer = Sdf.Layer.CreateNew(str(old))
        prim = Sdf.PrimSpec(layer, "CHAR_GEO_DINGO_null", Sdf.SpecifierDef, "Xform")
        prim.kind = "component"
        layer.defaultPrim = prim.name
        layer.Save()
        (old.with_suffix(".proxy.usda")).write_text("#usda 1.0\n", encoding="utf-8")
        self.assertTrue(is_legacy_file(self.project, old))
        r = load_targets(self.project, old)
        self.assertTrue(r["legacy"])
        self.assertEqual([t["what"] for t in r["targets"]], ["asset"])    # the asset, never the file
        self.assertIn("Ancien", r["message"])
        self.assertEqual(len(legacy_files(self.project)), 2)
        backup = delete_legacy_file(self.project, old)
        self.assertFalse(old.exists())
        self.assertFalse(old.with_suffix(".proxy.usda").exists())
        self.assertTrue(backup.is_file())
        self.assertIn("_backup_flux", str(backup))

    def test_a_decor_of_usd_assembly_is_not_old(self) -> None:
        decor = self.project / "usd" / "assembly" / "TOWN.usda"
        decor.parent.mkdir(parents=True)
        layer = Sdf.Layer.CreateNew(str(decor))
        prim = Sdf.PrimSpec(layer, "TOWN", Sdf.SpecifierDef, "Xform")
        prim.kind = "assembly"
        layer.defaultPrim = "TOWN"
        layer.Save()
        self.assertFalse(is_legacy_file(self.project, decor))
        with self.assertRaises(ValueError):
            delete_legacy_file(self.project, decor)


if __name__ == "__main__":
    unittest.main()
