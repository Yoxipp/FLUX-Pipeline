# test_proxy_publish_wiring.py - the opt-in USD proxy hook after a publish.
#
# Proves _maybe_generate_proxy: off by default, runs on a real USD asset when the
# flag is on, ignores non-USD, and never lets a proxy failure break the publish.

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Usd, UsdGeom, Vt

from routers import publish
from features.publisher.usd_proxy import is_usd_asset


def _make_grid_usd(path: Path, n: int) -> None:
    stage = Usd.Stage.CreateNew(str(path))
    root = UsdGeom.Xform.Define(stage, "/Asset")
    stage.SetDefaultPrim(root.GetPrim())
    mesh = UsdGeom.Mesh.Define(stage, "/Asset/Geo")
    pts = [(float(c), float(r), 0.0) for r in range(n + 1) for c in range(n + 1)]
    counts, idx = [], []
    for r in range(n):
        for c in range(n):
            a = r * (n + 1) + c
            counts.append(4)
            idx += [a, a + 1, a + n + 2, a + n + 1]
    mesh.CreatePointsAttr(Vt.Vec3fArray(pts))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray(counts))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(idx))
    stage.GetRootLayer().Save()


def _run(dest: Path):
    async def go():
        return await publish._maybe_generate_proxy(dest, asyncio.get_event_loop())
    return asyncio.run(go())


class IsUsdAssetTests(unittest.TestCase):
    def test_usd_yes_others_no(self):
        for name in ("a.usd", "a.usda", "a.usdc", "A.USD"):
            self.assertTrue(is_usd_asset(Path(name)), name)
        for name in ("a.mb", "a.exr", "a.abc", "a.tx"):
            self.assertFalse(is_usd_asset(Path(name)), name)


class MaybeGenerateProxyTests(unittest.TestCase):
    def test_off_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            _make_grid_usd(src, 40)
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertIsNone(_run(src))
            self.assertFalse((Path(d) / "asset.proxy.usda").exists())

    def test_on_generates_proxy(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            _make_grid_usd(src, 50)
            with mock.patch.dict("os.environ", {"FLUX_PROXY_USD": "1"}, clear=False):
                proxy_path = _run(src)
            self.assertIsNotNone(proxy_path)
            self.assertTrue(Path(proxy_path).exists())

    def test_on_but_non_usd_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            scene = Path(d) / "scene.mb"
            scene.write_bytes(b"not usd")
            with mock.patch.dict("os.environ", {"FLUX_PROXY_USD": "1"}, clear=False):
                self.assertIsNone(_run(scene))

    def test_failure_never_breaks_publish(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            _make_grid_usd(src, 20)
            with mock.patch.dict("os.environ", {"FLUX_PROXY_USD": "1"}, clear=False), \
                    mock.patch(
                        "flux_actions.runner.run_generate_proxy_action",
                        side_effect=RuntimeError("boom"),
                    ):
                self.assertIsNone(_run(src))


if __name__ == "__main__":
    unittest.main()
