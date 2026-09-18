# 2026-09-18: /stage gets the same FLUX Import HDA as /obj, placed on /assets/NAME.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pxr import Kind, Usd, UsdGeom

from dcc.houdini.hda import flux_importer_hda, flux_importer_lop_hda
from features.importer.library_import import probe_file


class ImporterLop(unittest.TestCase):
    def test_the_generated_build_script_is_valid_python(self) -> None:
        code = flux_importer_lop_hda._build_code("C:/tmp/flux_importer_lop.hda",
                                                 flux_importer_hda.PYTHON_MODULE)
        compile(code, "build_lop", "exec")
        self.assertIn('max_num_inputs=1', code)
        self.assertIn('chs("../prim_path")', code)

    def test_the_served_module_reloads_a_lop_importer(self) -> None:
        compile(flux_importer_hda._MODULE_FUNCTIONS, "module", "exec")
        self.assertIn("def _apply_lop", flux_importer_hda._MODULE_FUNCTIONS)
        self.assertIn('parm("reload")', flux_importer_hda._MODULE_FUNCTIONS)

    def test_probe_gives_the_asset_prim_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DINGO_LAST.usda"
            stage = Usd.Stage.CreateNew(str(path))
            root = UsdGeom.Xform.Define(stage, "/DINGO").GetPrim()
            Usd.ModelAPI(root).SetKind(Kind.Tokens.component)
            stage.SetDefaultPrim(root)
            stage.GetRootLayer().Save()
            self.assertEqual(probe_file(str(path))["prim_path"], "/assets/DINGO")


if __name__ == "__main__":
    unittest.main()
