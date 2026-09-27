# 2026-09-27: in shot mode the Publisher exports the cameras only (TYPE LAYOUT,
# preset "camera") or the lights only (TYPE LIGHT, preset "light"), animated.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdLux

from features.folder_manager import tokens as tok
from features.usd_export import LightAsset, MeshData, SkeletonData, publish_light_asset
from features.usd_export.contract import CameraData, LightData, light_asset_from_dict
from features.usd_export.departments import contribution, restrict_light_asset


def _m(tx: float) -> tuple:
    return (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, tx, 0, 0, 1)


def _scene() -> LightAsset:
    cam = CameraData(name="shotCam", transform=_m(0), focal_length=35.0,
                     times=[1001.0, 1002.0, 1003.0], transforms=[_m(0), _m(1), _m(2)],
                     focal_lengths=[35.0, 40.0, 50.0], fps=25.0)
    still = CameraData(name="witness", transform=_m(5))
    key = LightData(name="key", transform=_m(0), light_type="spot", intensity=2.0,
                    times=[1001.0, 1002.0], transforms=[_m(0), _m(3)], intensities=[2.0, 4.0], fps=25.0)
    return LightAsset(
        asset="tmp", skeleton=SkeletonData([], [], []),
        meshes=[MeshData(name="ground", points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
        cameras=[cam, still], lights=[key])


class Restrict(unittest.TestCase):
    def test_layout_keeps_the_cameras_only(self) -> None:
        asset, warnings = restrict_light_asset(_scene(), contribution("SEQ001_SHOT010_LAYOUT_null"))
        self.assertEqual([c.name for c in asset.cameras], ["shotCam", "witness"])
        self.assertEqual((asset.meshes, asset.lights), ([], []))
        self.assertEqual(len(warnings), 2)

    def test_light_keeps_the_lights_only(self) -> None:
        asset, _ = restrict_light_asset(_scene(), contribution("SEQ001_SHOT010_LIGHT_null"))
        self.assertEqual(([l.name for l in asset.lights], asset.cameras), (["key"], []))

    def test_nothing_to_publish_is_an_error(self) -> None:
        empty = LightAsset(asset="tmp", skeleton=SkeletonData([], [], []))
        with self.assertRaises(ValueError):
            restrict_light_asset(empty, contribution("SEQ001_SHOT010_LAYOUT_null"))

    def test_animation_survives_the_json_envelope(self) -> None:
        import dataclasses
        back = light_asset_from_dict(dataclasses.asdict(_scene()))
        self.assertEqual(back.cameras[0].focal_lengths, [35.0, 40.0, 50.0])
        self.assertEqual(back.lights[0].intensities, [2.0, 4.0])
        self.assertEqual(back.cameras[1].times, [])


class Publish(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tok.save_tokens(self.project, tok.build_default_tokens())

    def _publish(self, task: str) -> dict:
        dest = self.project / "shot" / "SEQ001" / "SHOT010" / task.lower()
        return publish_light_asset(_scene(), self.project, fmt="usda", dest_dir=dest,
                                   base_name=f"SEQ001_SHOT010_{task}_null", user="adam")

    def test_cameras_are_animated_under_cameras(self) -> None:
        res = self._publish("LAYOUT")
        self.assertEqual(sorted(res["layers"]), ["cam", "root"])
        stage = Usd.Stage.Open(str(res["version_root"]))
        self.assertEqual(stage.GetRootLayer().timeCodesPerSecond, 25.0)
        cam = UsdGeom.Camera(stage.GetPrimAtPath("/cameras/shotCam"))
        self.assertTrue(cam)
        self.assertEqual(cam.GetFocalLengthAttr().Get(1002), 40.0)
        world = UsdGeom.Xformable(cam).ComputeLocalToWorldTransform(1003)
        self.assertEqual(world.ExtractTranslation()[0], 2.0)
        still = UsdGeom.Xformable(stage.GetPrimAtPath("/cameras/witness"))
        self.assertEqual(still.GetXformOpOrderAttr().Get(), ["xformOp:transform"])
        self.assertFalse(still.GetOrderedXformOps()[0].GetAttr().GetNumTimeSamples())
        self.assertFalse(stage.GetPrimAtPath("/lights"))

    def test_lights_are_animated_under_lights(self) -> None:
        res = self._publish("LIGHT")
        self.assertEqual(sorted(res["layers"]), ["light", "root"])
        stage = Usd.Stage.Open(str(res["version_root"]))
        light = UsdLux.SphereLight(stage.GetPrimAtPath("/lights/key"))
        self.assertTrue(light)
        self.assertEqual(light.GetIntensityAttr().Get(1002), 4.0)
        self.assertFalse(stage.GetPrimAtPath("/cameras"))
        layer = Sdf.Layer.FindOrOpen(str(res["layers"]["light"]))
        self.assertEqual((layer.startTimeCode, layer.endTimeCode), (1001.0, 1002.0))


if __name__ == "__main__":
    unittest.main()
