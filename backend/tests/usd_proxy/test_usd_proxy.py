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


def _make_grid_usd(path: Path, n: int, mesh_path: str = "/Asset/Geo") -> None:
    """A single quad-grid mesh asset, n x n quads (2*n*n triangles)."""
    stage = Usd.Stage.CreateNew(str(path))
    root = UsdGeom.Xform.Define(stage, "/Asset")
    stage.SetDefaultPrim(root.GetPrim())
    mesh = UsdGeom.Mesh.Define(stage, mesh_path)
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

    def test_solaris_layout_proxy_goes_to_geo_proxy(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            _make_grid_usd(src, 30, "/Asset/geo/render/body")
            r = UP.generate_proxy(src, target_reduction=0.9)
            purposes = _mesh_purposes(Usd.Stage.Open(str(r.dst)))
            self.assertEqual(purposes["/Asset/geo/proxy/body"][0], UsdGeom.Tokens.proxy)
            self.assertNotIn("/Asset/geo/render/body_proxy", purposes)

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
            # Live bug 2026-09-18: the empty proxy file stayed and the asset used it.
            self.assertFalse(src.with_suffix(".proxy.usda").exists())

    def test_a_stub_proxy_never_replaces_its_publish(self):
        from features.publisher.usd_publish_hooks import usable_proxy

        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            _make_grid_usd(src, 4)
            stub = src.with_suffix(".proxy.usda")
            stub.write_text("#usda 1.0\n", encoding="utf-8")
            self.assertIsNone(usable_proxy(src))
            stub.unlink()
            UP.generate_proxy(src)
            self.assertEqual(usable_proxy(src), stub)


class SkinnedProxyTests(unittest.TestCase):
    """Live 2026-09-18: Houdini shows proxies in the viewport; an unskinned proxy kept
    the character rigid while its skeleton animated."""

    def _skinned_grid(self, path: Path, n: int = 12) -> None:
        from pxr import Gf, Sdf, UsdSkel

        _make_grid_usd(path, n, mesh_path="/Asset/geo/render/body")
        stage = Usd.Stage.Open(str(path))
        UsdSkel.Root.Define(stage, "/Asset")
        skel = UsdSkel.Skeleton.Define(stage, "/Asset/skel/Skeleton")
        skel.CreateJointsAttr(["Root", "Root/Top"])
        ident = Gf.Matrix4d(1)
        skel.CreateBindTransformsAttr([ident, ident])
        skel.CreateRestTransformsAttr([ident, ident])
        mesh = stage.GetPrimAtPath("/Asset/geo/render/body")
        pts = UsdGeom.Mesh(mesh).GetPointsAttr().Get()
        b = UsdSkel.BindingAPI.Apply(mesh)
        # bottom half on Root, top half on Top (one influence per point)
        b.CreateJointIndicesPrimvar(False, 1).Set([0 if p[1] < n / 2 else 1 for p in pts])
        b.CreateJointWeightsPrimvar(False, 1).Set([1.0] * len(pts))
        b.CreateSkeletonRel().SetTargets([Sdf.Path("/Asset/skel/Skeleton")])
        stage.GetRootLayer().Save()

    def test_the_proxy_keeps_the_skin_of_its_source(self):
        from pxr import UsdSkel

        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            self._skinned_grid(src)
            r = UP.generate_proxy(src, target_reduction=0.8, min_tris=10)
            self.assertEqual(r.status, "converted")
            stage = Usd.Stage.Open(str(r.dst))
            proxy = stage.GetPrimAtPath("/Asset/geo/proxy/body")
            self.assertTrue(proxy.HasAPI(UsdSkel.BindingAPI))
            b = UsdSkel.BindingAPI(proxy)
            n_pts = len(UsdGeom.Mesh(proxy).GetPointsAttr().Get())
            idx = list(b.GetJointIndicesPrimvar().Get())
            self.assertEqual(len(idx), n_pts)
            self.assertEqual(set(idx), {0, 1})
            self.assertEqual([str(t) for t in b.GetSkeletonRel().GetTargets()], ["/Asset/skel/Skeleton"])
            pts = UsdGeom.Mesh(proxy).GetPointsAttr().Get()
            for p, j in zip(pts, idx):        # weights follow position, not index order
                if p[1] <= 4.5:               # collapsed points near y=6 may go either way
                    self.assertEqual(j, 0, p)
                elif p[1] >= 7.0:
                    self.assertEqual(j, 1, p)

    def test_an_older_proxy_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "asset.usda"
            self._skinned_grid(src)
            r = UP.generate_proxy(src, target_reduction=0.8, min_tris=10)
            from pxr import Sdf
            layer = Sdf.Layer.FindOrOpen(str(r.dst))
            data = dict(layer.customLayerData)
            data["flux_proxy_tool"] = "flux-usd-proxy"          # pre-skin tool
            layer.customLayerData = data
            layer.Save()
            self.assertEqual(UP.generate_proxy(src).status, "converted")


def _make_groom_usd(path: Path, n_curves: int, *, skinned: bool = False) -> None:
    """/Asset/groom/hair: n_curves 4-point curves, per-vertex widths (+ a guide)."""
    from pxr import UsdSkel

    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.Xform.Define(stage, "/Asset")
    stage.SetDefaultPrim(stage.GetPrimAtPath("/Asset"))
    curves = UsdGeom.BasisCurves.Define(stage, "/Asset/groom/hair")
    pts = [(float(c), float(k), 0.0) for c in range(n_curves) for k in range(4)]
    curves.CreatePointsAttr(Vt.Vec3fArray(pts))
    curves.CreateCurveVertexCountsAttr(Vt.IntArray([4] * n_curves))
    curves.CreateTypeAttr(UsdGeom.Tokens.cubic)
    curves.CreateBasisAttr(UsdGeom.Tokens.catmullRom)
    curves.CreateWidthsAttr(Vt.FloatArray([0.01 * (i + 1) for i in range(len(pts))]))
    curves.SetWidthsInterpolation(UsdGeom.Tokens.vertex)
    guide = UsdGeom.BasisCurves.Define(stage, "/Asset/groom/guides")
    guide.CreatePurposeAttr(UsdGeom.Tokens.guide)
    guide.CreatePointsAttr(Vt.Vec3fArray(pts[:4]))
    guide.CreateCurveVertexCountsAttr(Vt.IntArray([4]))
    if skinned:
        UsdSkel.Skeleton.Define(stage, "/Asset/skel")
        b = UsdSkel.BindingAPI.Apply(curves.GetPrim())
        b.CreateSkeletonRel().SetTargets(["/Asset/skel"])
        b.CreateJointIndicesPrimvar(False, 1).Set(Vt.IntArray([i // 4 for i in range(len(pts))]))
        b.CreateJointWeightsPrimvar(False, 1).Set(Vt.FloatArray([1.0] * len(pts)))
    stage.GetRootLayer().Save()


class GroomProxyTests(unittest.TestCase):
    """ADR 0026: a render groom gets a thinned purpose=proxy sibling by default."""

    def test_keep_every(self):
        self.assertEqual(UP.curve_keep_every(0.9), 10)
        self.assertEqual(UP.curve_keep_every(0.5), 2)
        self.assertEqual(UP.curve_keep_every(0.0), 1)

    def test_thinned_curves_keep_whole_curves_and_widths(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "DINGO_GROOM_v001.usda"
            _make_groom_usd(src, 100)
            r = UP.generate_proxy(src, target_reduction=0.9)
            self.assertEqual(r.status, "converted")
            self.assertEqual((r.meshes, r.grooms, r.curves_in, r.curves_out), (0, 1, 100, 10))
            stage = Usd.Stage.Open(str(r.dst))
            render = UsdGeom.BasisCurves(stage.GetPrimAtPath("/Asset/groom/hair"))
            proxy = UsdGeom.BasisCurves(stage.GetPrimAtPath("/Asset/groom/hair_proxy"))
            self.assertEqual(render.GetPurposeAttr().Get(), UsdGeom.Tokens.render)
            self.assertEqual(proxy.GetPurposeAttr().Get(), UsdGeom.Tokens.proxy)
            self.assertEqual(list(proxy.GetCurveVertexCountsAttr().Get()), [4] * 10)
            self.assertEqual(len(proxy.GetPointsAttr().Get()), 40)
            self.assertEqual(proxy.GetBasisAttr().Get(), UsdGeom.Tokens.catmullRom)
            widths = proxy.GetWidthsAttr().Get()
            self.assertEqual(len(widths), 40)
            # Curve 10 (points 40..43) is the second kept one: its widths follow it.
            self.assertAlmostEqual(widths[4], 0.41, places=5)
            self.assertIsNotNone(proxy.GetExtentAttr().Get())
            # The guide curves are never proxied.
            self.assertFalse(stage.GetPrimAtPath("/Asset/groom/guides_proxy"))

    def test_skinned_groom_proxy_keeps_its_skin(self):
        from pxr import UsdSkel

        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "groom.usda"
            _make_groom_usd(src, 30, skinned=True)
            r = UP.generate_proxy(src, target_reduction=0.9)
            stage = Usd.Stage.Open(str(r.dst))
            b = UsdSkel.BindingAPI(stage.GetPrimAtPath("/Asset/groom/hair_proxy"))
            self.assertEqual(list(b.GetJointIndicesPrimvar().Get()), [0] * 4 + [10] * 4 + [20] * 4)
            self.assertEqual([str(t) for t in b.GetSkeletonRel().GetTargets()], ["/Asset/skel"])


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
