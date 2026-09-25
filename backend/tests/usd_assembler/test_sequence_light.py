# FLUX Lighting (2026-09-25): the sequence light rig is published as vNNN + LAST
# (never in place), the sequence root sublayers the LAST, and editing the published
# rig (overs on top of it) keeps its lights (flattened).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Sdf, Usd, UsdLux

from features.folder_manager import tokens as tok
from features.usd_assembler import shot_light as sl


def _lights(path: Path, *, over_of: Path | None = None, intensity: float = 3.0) -> Path:
    layer = Sdf.Layer.CreateNew(str(path))
    if over_of is None:
        stage = Usd.Stage.Open(layer)
        UsdLux.DistantLight.Define(stage, "/World/Lighting/key").CreateIntensityAttr(intensity)
        UsdLux.DomeLight.Define(stage, "/World/Lighting/dome")
    else:
        layer.subLayerPaths = [str(over_of).replace("\\", "/")]
        stage = Usd.Stage.Open(layer)
        stage.OverridePrim("/World/Lighting/key").GetAttribute("inputs:intensity").Set(intensity)
    layer.Save()
    return path


class SequenceLight(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["SEQ"]["SEQ001"] = "shot/SEQ001"
        tok.save_tokens(self.project, tokens)
        usd = self.project / "shot/SEQ001/usd"
        (usd / "lighting").mkdir(parents=True)
        root = Sdf.Layer.CreateNew(str(usd / "SEQ001.usda"))
        root.subLayerPaths = ["./lighting/SEQ001_light.usda"]      # starter rig of the template
        root.Save()
        self.root = usd / "SEQ001.usda"

    def test_publish_is_versioned_and_the_root_follows_last(self) -> None:
        res = sl.publish_sequence_light(_lights(Path(self._tmp.name) / "a.usda"), self.project, "SEQ001", user="adam")
        self.assertEqual((res["base"], res["version"]), ("SEQ001_LIGHT", "v001"))
        self.assertTrue(sl.seq_light_last(self.project, "SEQ001").is_file())
        root = Sdf.Layer.FindOrOpen(str(self.root))
        root.Reload()
        self.assertEqual(list(root.subLayerPaths), ["./lighting/SEQ001_LIGHT_LAST.usda"])
        seqs = sl.list_sequences(self.project)
        self.assertEqual((seqs[0]["seq"], seqs[0]["versions"]), ("SEQ001", ["v001"]))

    def test_editing_the_published_rig_keeps_its_lights(self) -> None:
        sl.publish_sequence_light(_lights(Path(self._tmp.name) / "a.usda"), self.project, "SEQ001")
        last = sl.seq_light_last(self.project, "SEQ001")
        res = sl.publish_sequence_light(_lights(Path(self._tmp.name) / "b.usda", over_of=last, intensity=7.0),
                                        self.project, "SEQ001")
        self.assertEqual(res["version"], "v002")
        stage = Usd.Stage.Open(str(res["root"]))
        self.assertTrue(stage.GetPrimAtPath("/World/Lighting/dome"))
        self.assertEqual(stage.GetPrimAtPath("/World/Lighting/key").GetAttribute("inputs:intensity").Get(), 7.0)
        published = Sdf.Layer.FindOrOpen(str(res["root"]))
        self.assertEqual(list(published.subLayerPaths), [])            # flat, standalone

    def test_nothing_to_publish_is_refused(self) -> None:
        empty = Path(self._tmp.name) / "empty.usda"
        Sdf.Layer.CreateNew(str(empty)).Save()
        with self.assertRaises(ValueError):
            sl.publish_sequence_light(empty, self.project, "SEQ001")


if __name__ == "__main__":
    unittest.main()
