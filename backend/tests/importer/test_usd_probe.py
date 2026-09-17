# test_usd_probe.py — facts that drive the context import of a USD file in Houdini.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from pxr import Kind, Sdf, Usd, UsdGeom, UsdSkel
except ImportError:  # pragma: no cover
    Usd = None

from features.importer.usd_probe import probe_usd, reference_prim_path


@unittest.skipIf(Usd is None, "pxr not available")
class ProbeUsd(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="flux_probe_"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _stage(self, name, build):
        path = self.dir / name
        st = Usd.Stage.CreateNew(str(path))
        build(st)
        st.GetRootLayer().Save()
        return path

    def test_component_with_skeleton_referenced_through_entry(self):
        def dept(st):
            root = UsdSkel.Root.Define(st, "/CHAR_GEO_X_null").GetPrim()
            UsdGeom.Mesh.Define(st, "/CHAR_GEO_X_null/body")
            UsdSkel.Skeleton.Define(st, "/CHAR_GEO_X_null/Skeleton")
            st.SetDefaultPrim(root)
        geo = self._stage("geo.usda", dept)

        def entry(st):
            prim = st.DefinePrim("/X")
            Usd.ModelAPI(prim).SetKind(Kind.Tokens.component)
            prim.GetPayloads().AddPayload(str(geo), "/CHAR_GEO_X_null")
            st.SetDefaultPrim(prim)
        info = probe_usd(self._stage("X.usda", entry))
        self.assertTrue(info["ok"])
        self.assertEqual((info["default_prim"], info["kind"]), ("X", "component"))
        self.assertTrue(info["has_skel"] and info["has_mesh"])
        self.assertFalse(info["has_anim"])
        self.assertEqual(reference_prim_path(info), "/assets/X")

    def test_anim_layer_and_assembly_paths(self):
        def anim(st):
            root = UsdSkel.Root.Define(st, "/A").GetPrim()
            UsdSkel.Skeleton.Define(st, "/A/Skeleton")
            UsdSkel.Animation.Define(st, "/A/Anim")
            st.SetDefaultPrim(root)
        info = probe_usd(self._stage("anim.usda", anim))
        self.assertTrue(info["has_anim"] and info["has_skel"])
        self.assertFalse(info["has_mesh"])

        self.assertEqual(reference_prim_path({"default_prim": "SET", "kind": "assembly"}), "/sets/SET")
        self.assertEqual(reference_prim_path({"default_prim": "cam", "kind": ""}), "/cam")

    def test_skeleton_outside_skelroot_is_not_a_character(self):
        # Old hand-built component: department layers sublayered, so the Skeleton sits
        # under its own root beside the SkelRoot (KineFX import fails on it).
        def old_component(st):
            root = UsdSkel.Root.Define(st, "/CHAR_GEO_X_null").GetPrim()
            UsdGeom.Mesh.Define(st, "/CHAR_GEO_X_null/body")
            UsdSkel.Skeleton.Define(st, "/CHAR_RIG_X_null/Skeleton")
            st.SetDefaultPrim(root)
        info = probe_usd(self._stage("old.usda", old_component))
        self.assertTrue(info["ok"] and info["has_mesh"] and info["skel_outside_root"])
        self.assertFalse(info["has_skel"])

    def test_unreadable_file_is_not_ok(self):
        bad = self.dir / "bad.usda"
        bad.write_text("nope", encoding="utf-8")
        self.assertFalse(probe_usd(bad)["ok"])


if __name__ == "__main__":
    unittest.main()
