# test_conform_publish_wiring.py - the opt-in .tx conform hooked after a publish.
#
# Proves the post-publish hook (_maybe_conform_texture): off by default, runs on
# a real texture when the flag is on, ignores non-textures, and never lets a
# conform failure break the publish.

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import OpenImageIO as oiio

from routers import publish
from features.publisher.texture_conform import is_texture_source


def _make_image(path: Path, res: int = 96, fmt: str = "half") -> None:
    spec = oiio.ImageSpec(res, res, 3, fmt)
    buf = oiio.ImageBuf(spec)
    oiio.ImageBufAlgo.noise(buf, "uniform", 0.0, 1.0, False, 1)
    if not buf.write(str(path)):
        raise RuntimeError(oiio.geterror())


def _run_maybe_conform(dest: Path):
    async def go():
        loop = asyncio.get_event_loop()
        return await publish._maybe_conform_texture(dest, loop)
    return asyncio.run(go())


class IsTextureSourceTests(unittest.TestCase):
    def test_textures_yes_others_no(self):
        for name in ("rock.exr", "rock.png", "rock.tif", "rock.JPG"):
            self.assertTrue(is_texture_source(Path(name)), name)
        for name in ("scene.mb", "cache.abc", "layer.usd", "already.tx"):
            self.assertFalse(is_texture_source(Path(name)), name)


class MaybeConformTextureTests(unittest.TestCase):
    def test_disabled_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "rock_Normal.exr"
            _make_image(src)
            with mock.patch.dict("os.environ", {"FLUX_CONFORM_TX": "0"}, clear=True):
                self.assertIsNone(_run_maybe_conform(src))
            # No .tx written when conform is explicitly disabled.
            self.assertFalse((Path(d) / "rock_Normal.tx").exists())

    def test_on_conforms_a_real_texture(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "rock_Normal.exr"
            _make_image(src)
            with mock.patch.dict("os.environ", {"FLUX_CONFORM_TX": "1"}, clear=False):
                tx_paths = _run_maybe_conform(src)
            self.assertIsNotNone(tx_paths)
            self.assertEqual(len(tx_paths), 1)
            self.assertTrue(Path(tx_paths[0]).exists())
            self.assertTrue((Path(d) / "rock_Normal.tx").exists())

    def test_on_but_non_texture_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            scene = Path(d) / "CHAR_RIG_HERO_null_LAST.mb"
            scene.write_bytes(b"not an image")
            with mock.patch.dict("os.environ", {"FLUX_CONFORM_TX": "1"}, clear=False):
                self.assertIsNone(_run_maybe_conform(scene))

    def test_conform_failure_never_breaks_publish(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "rock_Normal.exr"
            _make_image(src)
            with mock.patch.dict("os.environ", {"FLUX_CONFORM_TX": "1"}, clear=False), \
                    mock.patch(
                        "flux_actions.runner.run_conform_texture_action",
                        side_effect=RuntimeError("boom"),
                    ):
                # Must swallow the error and return None, not raise.
                self.assertIsNone(_run_maybe_conform(src))


if __name__ == "__main__":
    unittest.main()
