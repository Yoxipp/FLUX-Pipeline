# test_tx_only_publish.py - "Export .tx only": the .tx is published instead of the image.
#
# Proves convert_to_tx (real OpenImageIO conform into a temp folder, non-textures
# untouched, a failed conform keeps the source), the local-file helper _source_as_tx
# (target name renamed to .tx), and that two .tx-only publishes version v001 -> v002
# with no source image in the publish folder.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import OpenImageIO as oiio

from dcc.texture_publish import convert_to_tx
from features.publisher.publish_layout import publish_into_layout
from routers import publish


def _make_image(path: Path, res: int = 64) -> None:
    buf = oiio.ImageBuf(oiio.ImageSpec(res, res, 3, "uint8"))
    oiio.ImageBufAlgo.noise(buf, "uniform", 0.0, 1.0, False, 1)
    if not buf.write(str(path)):
        raise RuntimeError(oiio.geterror())


class ConvertToTxTests(unittest.TestCase):
    def test_texture_becomes_tx_other_files_pass_through(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "Body_BaseColor.1001.png"
            other = Path(d) / "notes.sbsar"
            _make_image(img)
            other.write_bytes(b"x")
            files, warnings = convert_to_tx([img, other])
            self.assertEqual(warnings, [])
            self.assertEqual(files[0].name, "Body_BaseColor.1001.tx")
            self.assertTrue(files[0].is_file())
            self.assertNotEqual(files[0].parent, img.parent)  # never beside the source
            self.assertEqual(files[1], other)

    def test_failed_conform_keeps_the_source(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "rock_Rough.png"
            _make_image(img)
            with mock.patch("flux_actions.runner.run_conform_texture_action",
                            side_effect=ValueError("boom")):
                files, warnings = convert_to_tx([img])
            self.assertEqual(files, [img])
            self.assertEqual(len(warnings), 1)


class SourceAsTxTests(unittest.TestCase):
    def test_target_name_gets_tx_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "rock_Normal.png"
            _make_image(img)
            src, target, done = publish._source_as_tx(img, "PROP_TEX_ROCK_null_NORM.png")
            self.assertTrue(done)
            self.assertEqual(src.suffix, ".tx")
            self.assertEqual(target, "PROP_TEX_ROCK_null_NORM.tx")
            # A target without extension is left as is (the .tx source gives it).
            self.assertEqual(publish._source_as_tx(img, "PROP_TEX_ROCK_null_NORM")[1],
                             "PROP_TEX_ROCK_null_NORM")

    def test_non_texture_is_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            scene = Path(d) / "scene.mb"
            scene.write_bytes(b"x")
            self.assertEqual(publish._source_as_tx(scene, None), (scene, None, False))


class TxOnlyVersioningTests(unittest.TestCase):
    def test_two_tx_publishes_are_v001_then_v002_without_images(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "src" / "rock_Normal.png"
            img.parent.mkdir()
            dest = Path(d) / "pub"
            for _ in range(2):
                _make_image(img)
                tx = convert_to_tx([img])[0][0]
                publish_into_layout(tx, dest, "PROP_TEX_ROCK_null_NORM", user="t")
            names = sorted(p.name for p in dest.iterdir() if p.is_file())
            self.assertIn("PROP_TEX_ROCK_null_NORM_v001.tx", names)
            self.assertIn("PROP_TEX_ROCK_null_NORM_v002.tx", names)
            self.assertFalse([n for n in names if n.endswith(".png")])


if __name__ == "__main__":
    unittest.main()
