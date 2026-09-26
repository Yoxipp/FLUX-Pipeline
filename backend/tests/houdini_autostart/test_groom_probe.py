# test_groom_probe.py - the groom probe flags prim paths a reference left behind (2026-09-26).

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from pxr import Sdf, Usd, UsdGeom

from dcc.houdini import groom_probe


class GroomProbe(unittest.TestCase):
    def test_text_paths_and_relationships_are_checked(self):
        stage = Usd.Stage.CreateInMemory()
        guides = UsdGeom.BasisCurves.Define(stage, "/UTAH/groom/body/guides")
        proc = stage.DefinePrim("/UTAH/groom/body/hair", "Xform")
        proc.CreateAttribute("houdini:procedural:guides", Sdf.ValueTypeNames.String).Set("/groom_procedural_BODY/guides")
        proc.CreateRelationship("skin").AddTarget(guides.GetPath())
        fh = io.StringIO()
        with redirect_stdout(io.StringIO()):
            groom_probe._describe(fh, stage, proc)
        text = fh.getvalue()
        self.assertIn("/groom_procedural_BODY/guides INTROUVABLE", text)
        self.assertIn("rel skin -> /UTAH/groom/body/guides OK", text)
        self.assertTrue(groom_probe._is_groom(proc))


if __name__ == "__main__":
    unittest.main()
