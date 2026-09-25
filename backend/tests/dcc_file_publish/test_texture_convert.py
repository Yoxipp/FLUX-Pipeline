# Per-map format / bit depth / size of exported texture maps (2026-09-25).

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from dcc import texture_convert as tc


def _image(path: Path, w: int = 64, h: int = 32, ch: int = 4, fmt: str = "float") -> Path:
    import OpenImageIO as oiio

    spec = oiio.ImageSpec(w, h, ch, fmt)
    buf = oiio.ImageBuf(spec)
    oiio.ImageBufAlgo.fill(buf, [0.5] * ch)
    buf.write(str(path))
    return path


class Depths(unittest.TestCase):
    def test_a_format_only_offers_the_depths_it_holds(self) -> None:
        self.assertNotIn("32f", tc.allowed_depths("png"))
        self.assertEqual(tc.allowed_depths("jpg"), ("8",))
        self.assertEqual(tc.pick_depth("png", "32f"), "16")
        self.assertEqual(tc.pick_depth("exr", "8"), "16f")
        self.assertEqual(tc.pick_depth("exr", None, "32f"), "32f")
        self.assertEqual(tc.pick_depth("tif", "16"), "16")

    def test_painter_config_keeps_depths_the_format_holds(self) -> None:
        from dcc.substance_painter import substance_export as se
        cfg = se.build_export_config("/tmp/o", "P", "png", "32f", maps=["a", "b"],
                                     map_params={"a": {"format": "exr", "bit_depth": "32f"}, "b": {"size": 1024}})
        self.assertEqual(cfg["exportParameters"][0]["parameters"]["bitDepth"], "16")
        per = {e["filter"]["outputMaps"][0]: e["parameters"] for e in cfg["exportParameters"][1:]}
        self.assertEqual(per["a"], {"fileFormat": "exr", "bitDepth": "32f"})
        self.assertEqual(per["b"], {"sizeLog2": 10})


class Convert(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)

    def test_float_map_to_16_bit_png_and_resized(self) -> None:
        import OpenImageIO as oiio
        src = _image(self.d / "B_COL.1001.exr")
        res = tc.convert_map(src, self.d / "out" / "B_COL.1001.png", depth="32f", size=32)
        spec = oiio.ImageBuf(str(res["path"])).spec()
        self.assertEqual((spec.width, spec.height), (32, 16))
        self.assertEqual(res["depth"], "16")
        self.assertIn("impossible", res["note"])

    def test_jpg_drops_alpha(self) -> None:
        import OpenImageIO as oiio
        src = _image(self.d / "SSS.1001.tif", fmt="uint8")
        res = tc.convert_map(src, self.d / "SSS.1001.jpg")
        self.assertEqual(oiio.ImageBuf(str(res["path"])).spec().nchannels, 3)

    def test_each_channel_gets_its_settings_and_keeps_its_tiles(self) -> None:
        files = [_image(self.d / f"DISP.{t}.exr") for t in (1001, 1002)] + [_image(self.d / "B_COL.1001.tif", fmt="uint8")]
        out, warns = tc.convert_maps(files, self.d / "conv", {"DISP": {"format": "exr", "bit_depth": "32f"}},
                                     "png", key_of=lambda f: f.name.split(".")[0])
        self.assertEqual(sorted(p.name for p in out), ["B_COL.1001.png", "DISP.1001.exr", "DISP.1002.exr"])
        self.assertEqual(warns, [])

    def test_a_map_already_in_its_format_is_kept_as_is(self) -> None:
        """2026-09-26: Mari publish too slow - no re-encode when nothing changes."""
        src = _image(self.d / "BCOL.1001.tif", fmt="uint8")
        self.assertFalse(tc.needs_convert(src, "tif", None, None))
        self.assertFalse(tc.needs_convert(src, "tif", "8", 64))
        self.assertTrue(tc.needs_convert(src, "tif", "16", None))
        self.assertTrue(tc.needs_convert(src, "tif", None, 32))
        self.assertTrue(tc.needs_convert(src, "png", None, None))
        with unittest.mock.patch.object(tc, "convert_map", side_effect=AssertionError("re-encoded")):
            out, warns = tc.convert_maps([src], self.d / "conv", {}, "tif", key_of=lambda f: "BCOL")
        self.assertEqual([p.name for p in out], ["BCOL.1001.tif"])
        self.assertEqual(warns, [])


if __name__ == "__main__":
    unittest.main()
