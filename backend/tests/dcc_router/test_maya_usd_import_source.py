# test_maya_usd_import_source.py — USD handed to Maya 2024's mayaUsd on import.
#
# Maya 2024 fails with "Error reading file" on accented paths (OneDrive) and on
# recent crates, even for an ASCII .usda whose sublayers are fine. The router must
# flatten every USD (except .usdz) into a self-contained ASCII .usda in the work dir.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from pxr import Sdf, Usd, UsdGeom
except ImportError:  # pragma: no cover - pxr is a backend dependency
    Usd = None

from routers import dcc as dcc_router


@unittest.skipIf(Usd is None, "pxr not available")
class MayaUsdImportSource(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="flux_maya_usd_"))
        self.project = self.root / "Ecole supérieure des métiers"
        (self.project / "model").mkdir(parents=True)
        self.work = self.root / "work"
        self.work.mkdir()

        crate = self.project / "model" / "geo_model.usd"
        stage = Usd.Stage.CreateNew(str(crate))
        UsdGeom.Mesh.Define(stage, "/geo/cube")
        stage.GetRootLayer().Save()

        self.entry = self.project / "entry.usda"
        layer = Sdf.Layer.CreateNew(str(self.entry))
        layer.subLayerPaths.append("./model/geo_model.usd")
        layer.Save()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_ascii_entry_with_sublayers_is_flattened_into_work_dir(self):
        out = Path(dcc_router._maya_usd_source(self.entry, str(self.work)))
        self.assertEqual(out.parent, self.work)
        self.assertEqual(out.suffix, ".usda")
        self.assertTrue(out.read_text(encoding="utf-8").startswith("#usda"))
        flat = Usd.Stage.Open(str(out))
        self.assertTrue(flat.GetPrimAtPath("/geo/cube").IsValid())
        self.assertEqual(list(flat.GetRootLayer().subLayerPaths), [])

    def test_crate_is_flattened_to_ascii(self):
        out = Path(dcc_router._maya_usd_source(self.project / "model" / "geo_model.usd", str(self.work)))
        self.assertEqual(out.parent, self.work)
        self.assertTrue(out.read_text(encoding="utf-8").startswith("#usda"))

    def test_usdz_is_returned_unchanged(self):
        usdz = self.project / "pkg.usdz"
        usdz.write_bytes(b"PK")
        out = dcc_router._maya_usd_source(usdz, str(self.work))
        self.assertEqual(out, str(usdz).replace("\\", "/"))

    def test_unreadable_file_falls_back_to_source(self):
        bad = self.project / "bad.usda"
        bad.write_text("not usd", encoding="utf-8")
        out = dcc_router._maya_usd_source(bad, str(self.work))
        self.assertEqual(out, str(bad).replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
