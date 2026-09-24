# A4 (ADR 0020): the shot stage generated from the Production casting, the published
# shot departments and one animation per character.

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Sdf, Usd, UsdGeom, UsdSkel

from features.usd_assembler.component_auto import add_proposed
from features.folder_manager import tokens as tok
from features.usd_assembler import shot_stage as ss
from features.usd_export import AnimData, LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_REL = "assets/chara/DINGO"


def _rig(anim: AnimData | None = None) -> LightAsset:
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=["Root", "Root/Hip"], bind_transforms=[_ID] * 2,
                              rest_transforms=[_ID] * 2),
        meshes=[MeshData(name="body", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
        anim=anim,
    )


def _anim(times=(1001.0, 1002.0, 1003.0)) -> AnimData:
    n = len(times)
    rots = [[(0, 0, 0, 1)], [(0, 0.3826834, 0, 0.9238795)], [(0, 0.7071068, 0, 0.7071068)]]
    return AnimData(joints=["Root/Hip"], times=list(times), translations=[[(0, 0, 0)]] * n,
                    rotations=(rots * n)[:n], scales=[[(1, 1, 1)]] * n, fps=24.0)


def _production(links=None, shot_links=None, *, inherit=True, frame_range=None) -> dict:
    shot = {"id": "shot_1", "seq_id": "seq_1", "name": "SHOT010", "inherit_assets": inherit,
            "assets": shot_links or [], "tasks": []}
    if frame_range:
        shot["frame_start"], shot["frame_end"] = frame_range
    return {"version": 1,
            "sequences": [{"id": "seq_1", "name": "SEQ001", "assets": links or [], "tasks": []}],
            "shots": [shot],
            "assets": [{"id": "asset_dingo", "class": "CHAR", "name": "DINGO", "tasks": []}],
            "asset_groups": []}


class ShotStage(unittest.TestCase):
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
        tokens["SEQ"]["SEQ001"] = "shot/SEQ001"
        tokens["SHOT"]["SEQ001/SHOT010"] = "shot/SEQ001/SHOT010"
        tok.save_tokens(self.project, tokens)
        publish_light_asset(_rig(), self.project, fmt="usda",
                            dest_dir=self.project / _REL / "model" / "null",
                            base_name="CHAR_GEO_DINGO_null", user="adam")
        add_proposed(self.project, "DINGO", ["GEO"])     # components are created by hand (ADR 0023)

    def _publish_anim(self, character="DINGO", times=(1001.0, 1002.0, 1003.0)) -> dict:
        return publish_light_asset(
            _rig(_anim(times)), self.project, fmt="usda",
            dest_dir=self.project / "shot/SEQ001/SHOT010/anim" / character.lower(),
            base_name=f"SEQ001_SHOT010_ANIM_{character}", user="adam")

    def _write(self, production, **kw) -> dict:
        return ss.write_stage(self.project, "SEQ001", "SHOT010", production=production, **kw)

    def test_casting_becomes_one_prim_per_instance(self) -> None:
        prod = _production([{"id": "asset_dingo", "ref": "CHAR/DINGO", "count": 2}], frame_range=(1001, 1100))
        res = self._write(prod)
        self.assertEqual(res["version"], "v001")
        stage = Usd.Stage.Open(str(res["last"]))
        for n in ("01", "02"):
            prim = stage.GetPrimAtPath(f"/assets/CHAR/DINGO_{n}")
            self.assertTrue(prim, n)
            self.assertTrue(prim.IsA(UsdSkel.Root))         # typeless casting prim: SkelRoot comes through
            self.assertTrue(stage.GetPrimAtPath(f"/assets/CHAR/DINGO_{n}/geo/render/body"))
            # R1: contiguous model hierarchy, the casting instance is a real model.
            self.assertTrue(Usd.ModelAPI(prim).IsModel(), n)
        self.assertEqual(Usd.ModelAPI(stage.GetPrimAtPath("/assets")).GetKind(), "group")
        self.assertEqual(Usd.ModelAPI(stage.GetPrimAtPath("/assets/CHAR")).GetKind(), "group")
        self.assertEqual((stage.GetStartTimeCode(), stage.GetEndTimeCode()), (1001.0, 1100.0))
        self.assertEqual(stage.GetTimeCodesPerSecond(), 24.0)
        self.assertEqual(UsdGeom.GetStageMetersPerUnit(stage), 1.0)
        # Relative paths only (ADR 0010).
        casting = Sdf.Layer.FindOrOpen(str(res["entry"].parent / "SEQ001_SHOT010_casting.usda"))
        ref = casting.GetPrimAtPath("/assets/CHAR/DINGO_01").referenceList.prependedItems[0]
        self.assertFalse(os.path.isabs(ref.assetPath))

    def test_the_animation_lands_on_its_character(self) -> None:
        self._publish_anim()
        prod = _production([{"id": "asset_dingo", "ref": "CHAR/DINGO", "count": 2}], frame_range=(1001, 1003))
        res = self._write(prod)
        stage = Usd.Stage.Open(str(res["last"]))
        cache = UsdSkel.Cache()
        for n, animated in (("01", True), ("02", False)):
            root = UsdSkel.Root(stage.GetPrimAtPath(f"/assets/CHAR/DINGO_{n}"))
            cache.Populate(root, Usd.PrimDefaultPredicate)
            skel = UsdSkel.Skeleton(stage.GetPrimAtPath(f"/assets/CHAR/DINGO_{n}/skel/Skeleton"))
            query = cache.GetSkelQuery(skel)
            self.assertEqual(bool(query.GetAnimQuery()), animated, n)

    def test_an_animation_without_casting_adds_the_character(self) -> None:
        self._publish_anim("DINGO_02")
        prod = _production()
        res = self._write(prod)
        stage = Usd.Stage.Open(str(res["last"]))
        self.assertTrue(stage.GetPrimAtPath("/assets/CHAR/DINGO_02"))
        self.assertTrue(stage.GetPrimAtPath("/assets/CHAR/DINGO_01"))
        self.assertTrue(any("ajoute au casting" in w for w in res["warnings"]))
        link = prod["shots"][0]["assets"][0]
        self.assertEqual((link["id"], link["count"], link["origin"]), ("asset_dingo", 2, "auto"))
        # No frame range in Production: the animation's one, with a warning.
        self.assertEqual((stage.GetStartTimeCode(), stage.GetEndTimeCode()), (1001.0, 1003.0))

    def test_an_animation_longer_than_the_shot_is_reported(self) -> None:
        self._publish_anim()
        res = self._write(_production([{"id": "asset_dingo", "ref": "CHAR/DINGO"}], frame_range=(1001, 1002)))
        self.assertTrue(any("hors de la plage" in w for w in res["warnings"]), res["warnings"])

    def test_missing_departments_are_skipped_with_a_warning(self) -> None:
        res = self._write(_production([{"id": "asset_dingo", "ref": "CHAR/DINGO"}]))
        self.assertTrue(any("layout" in w for w in res["warnings"]))
        entry = Sdf.Layer.FindOrOpen(str(res["entry"]))
        # No department published: the shot light rig template (created with the stage) + the casting.
        self.assertEqual(list(entry.subLayerPaths),
                         ["../lighting/SEQ001_SHOT010_light.usda", "./SEQ001_SHOT010_casting.usda"])

    def test_the_old_template_root_is_retired_by_the_first_stage(self) -> None:
        from features.folder_manager.sequence_template import create_sequence_usd_template

        legacy = ss.stage_dir(self.project, "SEQ001", "SHOT010") / "SEQ001_SHOT010.usda"
        legacy.parent.mkdir(parents=True)
        layer = Sdf.Layer.CreateNew(str(legacy))
        layer.customLayerData = {"flux": {"role": "shot_root", "sequence": "SEQ001", "shot": "SHOT010"}}
        layer.Save()
        del layer
        create_sequence_usd_template(ss.seq_dir(self.project, "SEQ001"), "SEQ001")
        self._write(_production([{"id": "asset_dingo", "ref": "CHAR/DINGO"}]))
        self.assertFalse(legacy.exists())
        self.assertTrue(list((self.project / "_backup_flux").rglob("SEQ001_SHOT010.usda")))

    def test_nothing_changed_means_no_new_version(self) -> None:
        prod = _production([{"id": "asset_dingo", "ref": "CHAR/DINGO"}])
        self.assertEqual(self._write(prod)["version"], "v001")
        self.assertIsNone(self._write(prod)["version"])
        prod["sequences"][0]["assets"][0]["count"] = 2
        self.assertEqual(self._write(prod)["version"], "v002")

    def test_publishing_a_shot_animation_regenerates_the_stage(self) -> None:
        (self.project / "production.json").write_text(json.dumps(
            _production([{"id": "asset_dingo", "ref": "CHAR/DINGO"}])), encoding="utf-8")
        self._publish_anim()
        self.assertEqual(ss.stage_versions(self.project, "SEQ001", "SHOT010"), ["v001"])
        # The project is not in the workspace: its production.json is never rewritten.
        self.assertNotIn('"origin"', (self.project / "production.json").read_text(encoding="utf-8"))

    def test_frozen_stage_points_at_versions(self) -> None:
        self._publish_anim()
        prod = _production([{"id": "asset_dingo", "ref": "CHAR/DINGO"}])
        res = self._write(prod, frozen=True)
        anim = Sdf.Layer.FindOrOpen(str(res["entry"].parent / "SEQ001_SHOT010_animation.usda"))
        ref = anim.GetPrimAtPath("/assets/CHAR/DINGO_01").referenceList.prependedItems[0]
        self.assertIn("_v001/", ref.assetPath)
        casting = Sdf.Layer.FindOrOpen(str(res["entry"].parent / "SEQ001_SHOT010_casting.usda"))
        cref = casting.GetPrimAtPath("/assets/CHAR/DINGO_01").referenceList.prependedItems[0]
        self.assertNotIn("_LAST", cref.assetPath)

    def test_summary_for_the_usd_page(self) -> None:
        prod = _production([{"id": "asset_dingo", "ref": "CHAR/DINGO"}])
        self.assertEqual(ss.shot_summary(self.project, "SEQ001", "SHOT010", prod)["state"], "none")
        self._write(prod)
        summary = ss.shot_summary(self.project, "SEQ001", "SHOT010", prod)
        self.assertEqual(summary["state"], "up_to_date")
        self.assertEqual(summary["casting"][0]["prim"], "/assets/CHAR/DINGO_01")
        prod["sequences"][0]["assets"][0]["count"] = 3
        self.assertEqual(ss.shot_summary(self.project, "SEQ001", "SHOT010", prod)["state"], "outdated")

    def test_the_importer_library_offers_the_shot_as_a_sublayer(self) -> None:
        from features.importer.library_import import (
            importer_source_for_file, library_items, resolve_library_item,
        )

        self.assertNotIn("shot:SEQ001/SHOT010", [i["key"] for i in library_items(self.project)])
        res = self._write(_production([{"id": "asset_dingo", "ref": "CHAR/DINGO"}]))
        item = next(i for i in library_items(self.project) if i["key"] == "shot:SEQ001/SHOT010")
        self.assertEqual(item["versions"], ["LAST", "v001"])
        r = resolve_library_item(self.project, "shot:SEQ001/SHOT010", "LAST")
        self.assertEqual((r["ok"], r["kind"]), (True, "shot"))
        self.assertEqual(Path(r["path"]), res["last"])
        src = importer_source_for_file(self.project, res["last"])
        self.assertEqual((src["lib_item"], src["lib_version"]), ("shot:SEQ001/SHOT010", "LAST"))
        src = importer_source_for_file(self.project, res["entry"])
        self.assertEqual(src["lib_version"], "v001")

    def test_the_shot_light_rig_is_published_and_joins_the_stage(self) -> None:
        from features.usd_assembler.shot_light import list_stage_shots, publish_shot_light

        prod = _production([{"id": "asset_dingo", "ref": "CHAR/DINGO"}], frame_range=(1001, 1010))
        (self.project / "production.json").write_text(json.dumps(prod), encoding="utf-8")
        self._write(prod)
        shots = list_stage_shots(self.project)
        self.assertEqual([(s["seq"], s["shot"], s["range"]) for s in shots],
                         [("SEQ001", "SHOT010", [1001, 1010])])
        # What the FLUX Shot node exports: the layers after its Layer Break (lights only).
        src = Path(self._tmp.name) / "light.usda"
        layer = Sdf.Layer.CreateNew(str(src))
        Sdf.CreatePrimInLayer(layer, "/lights/key").specifier = Sdf.SpecifierDef
        layer.GetPrimAtPath("/lights/key").typeName = "DistantLight"
        layer.Save()
        res = publish_shot_light(src, self.project, "SEQ001", "SHOT010", user="adam")
        self.assertEqual((res["base"], res["version"]), ("SEQ001_SHOT010_LIGHT", "v001"))
        self.assertTrue(str(res["last"]).replace("\\", "/").endswith("lighting/SEQ001/null/SEQ001_SHOT010_LIGHT_LAST.usda"))
        self.assertEqual(res["stage"], "v002")              # the stage now sublayers the light rig
        stage = Usd.Stage.Open(str(ss.last_file(self.project, "SEQ001", "SHOT010")))
        self.assertTrue(stage.GetPrimAtPath("/lights/key"))
        entry = Sdf.Layer.FindOrOpen(str(ss.stage_dir(self.project, "SEQ001", "SHOT010")
                                         / "SEQ001_SHOT010_v002" / "SEQ001_SHOT010.usda"))
        self.assertIn("SEQ001_SHOT010_LIGHT_LAST.usda", entry.subLayerPaths[0])   # lighting = strongest

    def test_an_empty_light_export_is_refused(self) -> None:
        from features.usd_assembler.shot_light import publish_shot_light

        src = Path(self._tmp.name) / "empty.usda"
        Sdf.Layer.CreateNew(str(src)).Save()
        with self.assertRaises(ValueError):
            publish_shot_light(src, self.project, "SEQ001", "SHOT010")


if __name__ == "__main__":
    unittest.main()
