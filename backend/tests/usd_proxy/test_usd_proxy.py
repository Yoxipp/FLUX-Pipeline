# test_usd_proxy.py - USD purpose=proxy generation (pxr + fast-simplification).
#
# Headless, no Houdini. Builds tiny USD grid assets and proves triangulation,
# decimation, the authored proxy layer (render over + proxy sibling), skip, and
# the command / runner wiring.
#
# pxr is involved, so prefer running via tests/run_tests.py (usd-core can abort
# at interpreter teardown with exit 3; that runner judges on a sentinel).

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom, Vt

from flux_core import ActionQuery
from flux_actions import commands as _commands  # noqa: F401  (populate registry)
from flux_actions.runner import GENERATE_PROXY_ACTION, run_generate_proxy_action
from features.publisher import usd_proxy as UP


def _make_grid_usd(path: Path, n: int) -> None:
    """A single quad-grid mesh asset, n x n quads (2*n*n triangles)."""
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


def _mesh_purposes(stage: Usd.Stage):
    out = {}
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            purpose = UsdGeom.Imageable(prim).GetPurposeAttr().Get()
            counts = UsdGeom.Mesh(prim).GetFaceVertexCountsAttr().Get()
            out[prim.GetPath().pathString] = (purpose, len(counts) if counts else 0)
    return out


class TriangulateTests(unittest.TestCase):
    def test_quads_and_ngon(self):
        # Two quads sharing nothing: 4 triangles.
        counts = np.array([4, 4], dtype=np.int64)
        indices = np.array([0, 1, 2, 3, 4, 5, 6, 7], dtype=np.int64)
        self.assertEqual(UP.triangulate(counts, indices).shape, (4, 3))
        # A pentagon -> 3 triangles.
        counts = np.array([5], dtype=np.int64)
        indices = np.array([0, 1, 2, 3, 4], dtype=np.int64)
        self.assertEqual(UP.triangulate(counts, indices).shape, (3, 3))

    def test_degenerate_face_skipped(self):
        counts = np.array([2], dtype=np.int64)  # not a real face
        indices = np.array([0, 1], dtype=np.int64)
        self.assertEqual(UP.triangulate(counts, indices).shape, (0, 3))


class DecimateTests(unittest.TestCase):
    def test_reduces_triangle_count(self):
        _make_reduce_check(self)


def _make_reduce_check(case):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "asset.usda"
        _make_grid_usd(src, 40)  # 3200 tris
        stage = Usd.Stage.Open(str(src))
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath("/Asset/Geo"))
        pts = np.asarray(mesh.GetPointsAttr().Get(), dtype=np.float32)
        counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get(), dtype=np.int64)
        idx = np.asarray(mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int64)
        tris = UP.triangulate(counts, idx)
        _, new_faces = UP.decimate(pts, tris, 0.9)
        case.assertLess(new_faces.shape[0], tris.shape[0])
        case.assertGreater(new_faces.shape[0], 0)


class GenerateProxyTests(unittest.TestCase):
    def test_authors_render_over_and_proxy_sibling(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            _make_grid_usd(src, 60)  # 7200 tris
            r = UP.generate_proxy(src, target_reduction=0.9)
            self.assertEqual(r.status, "converted")
            self.assertEqual(r.meshes, 1)
            self.assertLess(r.tris_out, r.tris_in)

            stage = Usd.Stage.Open(str(r.dst))
            purposes = _mesh_purposes(stage)
            self.assertEqual(purposes["/Asset/Geo"][0], UsdGeom.Tokens.render)
            self.assertIn("/Asset/Geo_proxy", purposes)
            self.assertEqual(purposes["/Asset/Geo_proxy"][0], UsdGeom.Tokens.proxy)
            # The proxy has fewer faces than the source render mesh.
            self.assertLess(purposes["/Asset/Geo_proxy"][1], purposes["/Asset/Geo"][1])

    def test_skip_and_force(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            _make_grid_usd(src, 30)
            self.assertEqual(UP.generate_proxy(src).status, "converted")
            self.assertEqual(UP.generate_proxy(src).status, "skipped")
            self.assertEqual(UP.generate_proxy(src, force=True).status, "converted")

    def test_small_mesh_kept_under_min_tris(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            _make_grid_usd(src, 4)  # 32 tris
            r = UP.generate_proxy(src, min_tris=200)
            # Below the threshold: proxy keeps every triangle.
            self.assertEqual(r.tris_out, r.tris_in)

    def test_no_render_mesh_fails(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "empty.usda"
            stage = Usd.Stage.CreateNew(str(src))
            UsdGeom.Xform.Define(stage, "/Asset")
            stage.GetRootLayer().Save()
            r = UP.generate_proxy(src)
            self.assertEqual(r.status, "failed")


class ProxyCommandTests(unittest.TestCase):
    def test_action_loads_one_step(self):
        query = ActionQuery.from_file(GENERATE_PROXY_ACTION, context={})
        self.assertEqual([s.name for s in query.buffer.ordered_steps()], ["proxy"])

    def test_runner_generates_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            _make_grid_usd(src, 50)
            result = run_generate_proxy_action(src, target_reduction=0.9)
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "converted")
            self.assertTrue(Path(result["proxy_path"]).exists())
            self.assertLess(result["tris_out"], result["tris_in"])


if __name__ == "__main__":
    unittest.main()
