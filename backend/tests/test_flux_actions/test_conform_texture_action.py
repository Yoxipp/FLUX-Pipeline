# test_conform_texture_action.py - the texture conform action / feature core.
#
# Headless, no Houdini. Pixel work uses OpenImageIO on tiny synthetic images
# (fast), so conversion, mip/tile, skip-if-unchanged and colorspace branching
# are all proven for real. Only the failure path mocks make_texture.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import OpenImageIO as oiio

from flux_core import ActionQuery, Status
from flux_actions import commands as _commands  # noqa: F401  (populate registry)
from flux_actions.runner import CONFORM_TEXTURE_ACTION, run_conform_texture_action
from features.publisher import texture_conform as TC


def _make_image(path: Path, res: int = 128, fmt: str = "uint8") -> None:
    """Write a small NON-constant image (noise), so make_texture keeps mips."""
    spec = oiio.ImageSpec(res, res, 3, fmt)
    buf = oiio.ImageBuf(spec)
    oiio.ImageBufAlgo.noise(buf, "uniform", 0.0, 1.0, False, 1)
    if not buf.write(str(path)):
        raise RuntimeError(oiio.geterror())


def _mips_and_tiles(tx: Path):
    inp = oiio.ImageInput.open(str(tx))
    spec = inp.spec()
    tile = (spec.tile_width, spec.tile_height)
    mips = 0
    while inp.seek_subimage(0, mips):
        mips += 1
    desc = spec.getattribute("ImageDescription")
    inp.close()
    return mips, tile, desc


class ConformActionLoadTests(unittest.TestCase):
    """The bundled conform_texture.yml is valid and wires one step."""

    def test_action_loads_one_step(self):
        query = ActionQuery.from_file(CONFORM_TEXTURE_ACTION, context={})
        step_names = [s.name for s in query.buffer.ordered_steps()]
        self.assertEqual(step_names, ["conform"])
        cmd = query.buffer.steps["conform"].commands["conform"]
        self.assertEqual(cmd.command, "conform_texture")


class ClassifyRoleTests(unittest.TestCase):
    """Role is read from the filename; unknown names stay data (never gamma-shift)."""

    def test_color_data_and_unknown(self):
        self.assertEqual(TC.classify_role(Path("T_rock_BaseColor.1001.exr")), "color")
        self.assertEqual(TC.classify_role(Path("hero_albedo.png")), "color")
        self.assertEqual(TC.classify_role(Path("rock_Normal.exr")), "data")
        self.assertEqual(TC.classify_role(Path("skin_Roughness.tif")), "data")
        self.assertEqual(TC.classify_role(Path("caiman_wholebody.exr")), "data")


class ExpandInputsTests(unittest.TestCase):
    """A UDIM pattern, a folder, and a single file each expand correctly."""

    def test_udim_folder_and_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for udim in (1001, 1002):
                (root / f"rock.{udim}.exr").write_bytes(b"x")
            (root / "note.txt").write_bytes(b"x")

            udim = TC.expand_inputs(str(root / "rock.<UDIM>.exr"))
            self.assertEqual([p.name for p in udim],
                             ["rock.1001.exr", "rock.1002.exr"])

            folder = TC.expand_inputs(str(root))
            self.assertEqual([p.name for p in folder],  # note.txt is not an image
                             ["rock.1001.exr", "rock.1002.exr"])

            one = TC.expand_inputs(str(root / "rock.1001.exr"))
            self.assertEqual([p.name for p in one], ["rock.1001.exr"])


class ResolveColorspaceTests(unittest.TestCase):
    """Conversion happens only for a color map in an integer container."""

    def _two_real_spaces(self):
        cfg = oiio.ColorConfig()
        names = list(cfg.getColorSpaceNames())
        if len(names) < 2:
            self.skipTest("OIIO color config has too few spaces")
        return names[0], names[1]

    def test_color_integer_converts(self):
        a, b = self._two_real_spaces()
        self.assertEqual(TC._resolve_colorspaces("color", True, a, b), (a, b))

    def test_data_or_float_never_converts(self):
        a, b = self._two_real_spaces()
        self.assertEqual(TC._resolve_colorspaces("data", True, a, b), (None, None))
        self.assertEqual(TC._resolve_colorspaces("color", False, a, b), (None, None))

    def test_unresolved_space_is_left_raw(self):
        self.assertEqual(
            TC._resolve_colorspaces("color", True, "no_such_space", "nope"),
            (None, None),
        )

    def test_role_resolves_to_concrete_space(self):
        cfg = oiio.ColorConfig()
        names = set(cfg.getColorSpaceNames())
        try:
            concrete = cfg.getColorSpaceNameByRole("scene_linear")
        except Exception:
            concrete = None
        if not concrete or concrete not in names:
            self.skipTest("no scene_linear role in this OIIO config")
        self.assertEqual(TC._resolve_space(cfg, names, "scene_linear"), concrete)


class ConformOneTests(unittest.TestCase):
    """Real tiny conforms: mip/tile, provenance stamp, and the skip key."""

    def test_data_map_is_raw_and_tiled_mipped(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "rock_Normal.exr"
            _make_image(src, 128, "half")
            r = TC.conform_one(src, out_dir=Path(d) / "out")
            self.assertEqual(r.status, "converted")
            self.assertEqual(r.role, "data")
            self.assertEqual(r.colorspace, "raw")
            mips, tile, desc = _mips_and_tiles(r.dst)
            self.assertGreater(mips, 1)
            self.assertEqual(tile, (64, 64))
            self.assertIn("src_sha1=", desc)
            self.assertIn("role=data", desc)

    def test_color_int_map_is_marked_color(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "hero_BaseColor.png"
            _make_image(src, 128, "uint8")
            r = TC.conform_one(src, out_dir=Path(d) / "out")
            self.assertEqual(r.status, "converted")
            self.assertEqual(r.role, "color")
            _, _, desc = _mips_and_tiles(r.dst)
            self.assertIn("role=color", desc)

    def test_no_colorconvert_forces_raw(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "hero_BaseColor.png"
            _make_image(src, 64, "uint8")
            r = TC.conform_one(src, out_dir=Path(d) / "out", colorconvert=False)
            self.assertEqual(r.colorspace, "raw")


class SkipIfUnchangedTests(unittest.TestCase):
    """Second run skips; touching mtime still skips; a byte change reconverts."""

    def test_skip_touch_and_reconvert(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "rock_Normal.exr"
            out = Path(d) / "out"
            _make_image(src, 96, "half")

            self.assertEqual(TC.conform_one(src, out_dir=out).status, "converted")
            self.assertEqual(TC.conform_one(src, out_dir=out).status, "skipped")

            os.utime(src, None)  # mtime only; content hash unchanged
            self.assertEqual(TC.conform_one(src, out_dir=out).status, "skipped")

            with open(src, "ab") as fh:
                fh.write(b"\x00")  # real byte change
            self.assertEqual(TC.conform_one(src, out_dir=out).status, "converted")


class ConformCommandTests(unittest.TestCase):
    """The action engine runs the command and reports the .tx paths."""

    def test_runner_conforms_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "rock_Normal.exr"
            out = Path(d) / "out"
            _make_image(src, 96, "half")

            result = run_conform_texture_action(src, out_dir=out)
            self.assertIsNotNone(result)
            self.assertEqual(result["converted"], 1)
            self.assertEqual(len(result["tx_paths"]), 1)
            self.assertTrue(Path(result["tx_paths"][0]).exists())

    def test_failed_tile_makes_the_action_fail(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "rock_Normal.exr"
            _make_image(src, 64, "half")
            # make_texture reports failure: the command must raise -> no result.
            with mock.patch.object(
                oiio.ImageBufAlgo, "make_texture", return_value=False
            ):
                result = run_conform_texture_action(src, out_dir=Path(d) / "out")
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
