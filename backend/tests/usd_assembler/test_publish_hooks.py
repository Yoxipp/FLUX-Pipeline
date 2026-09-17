# ADR 0019: after a USD publish, the proxy layer is written beside the immutable
# version and the asset (component) references it, so proxies stop being orphans.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pxr import Usd, UsdGeom, Vt

from features.folder_manager import tokens as tok
from features.publisher.publish_core import publish_file
from features.publisher.usd_publish_hooks import proxy_sibling

_NAME_REL = "assets/chara/UTAH"


def _grid(stage: Usd.Stage, path: str, n: int = 24) -> None:
    mesh = UsdGeom.Mesh.Define(stage, path)
    points = [(float(c), float(r), 0.0) for r in range(n + 1) for c in range(n + 1)]
    counts, indices = [], []
    for r in range(n):
        for c in range(n):
            a = r * (n + 1) + c
            counts.append(4)
            indices += [a, a + 1, a + n + 2, a + n + 1]
    mesh.CreatePointsAttr(Vt.Vec3fArray(points))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray(counts))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray(indices))


class ProxyReachesTheAsset(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"]["UTAH"] = _NAME_REL
        tok.save_tokens(self.project, tokens)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _publish_geo(self) -> Path:
        src = self.root / "CHAR_GEO_UTAH_null.usda"
        stage = Usd.Stage.CreateNew(str(src))
        stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/UTAH").GetPrim())
        _grid(stage, "/UTAH/geo/render/body")
        stage.GetRootLayer().Save()
        publish_file(src, self.project, "test", "adam", "PROJ")
        return self.project / _NAME_REL / "model" / "null"

    def _faces(self, stage: Usd.Stage, path: str) -> int:
        counts = UsdGeom.Mesh(stage.GetPrimAtPath(path)).GetFaceVertexCountsAttr().Get()
        return len(counts or [])

    def test_proxy_is_written_beside_the_version_and_used_by_the_asset(self) -> None:
        with mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "1", "FLUX_PROXY_REDUCTION": "0.9"}):
            folder = self._publish_geo()
        version = folder / "CHAR_GEO_UTAH_null_v001.usda"
        self.assertTrue(version.is_file())
        self.assertTrue(proxy_sibling(version).is_file())        # not on LAST, on the version

        stage = Usd.Stage.Open(str(self.project / _NAME_REL / "usd" / "UTAH_LAST.usda"))
        render, proxy = "/UTAH/geo/render/body", "/UTAH/geo/proxy/body"
        self.assertEqual(str(UsdGeom.Imageable(stage.GetPrimAtPath(render)).GetPurposeAttr().Get()), "render")
        self.assertEqual(str(UsdGeom.Imageable(stage.GetPrimAtPath(proxy)).GetPurposeAttr().Get()), "proxy")
        self.assertLess(self._faces(stage, proxy), self._faces(stage, render))

    def test_without_the_flag_the_asset_references_the_publish_itself(self) -> None:
        with mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "0"}):
            folder = self._publish_geo()
        self.assertFalse(proxy_sibling(folder / "CHAR_GEO_UTAH_null_v001.usda").exists())
        stage = Usd.Stage.Open(str(self.project / _NAME_REL / "usd" / "UTAH_LAST.usda"))
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/render/body").IsValid())
        self.assertFalse(stage.GetPrimAtPath("/UTAH/geo/proxy/body").IsValid())


if __name__ == "__main__":
    unittest.main()
