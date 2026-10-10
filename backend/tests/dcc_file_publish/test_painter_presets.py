# Studio Painter export presets (2026-09-26): shipped with FLUX, installed into Painter
# with the bridge, picked per project at its creation; the Publisher offers only those.

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dcc.substance_painter import presets
from core.project_setup import setup_path


class PainterPresets(unittest.TestCase):
    def test_the_studio_presets_are_shipped(self) -> None:
        self.assertIn("FLUX_BEAUTY_MAPS", presets.bundled_presets())
        self.assertIn("FLUX_UTIL_MAPS", presets.bundled_presets())

    def test_installing_the_bridge_installs_the_presets(self) -> None:
        from dcc.substance_painter import autostart
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {
                "FLUX_SP_PLUGINS_DIR": str(Path(d) / "startup"), "FLUX_SP_PRESETS_DIR": str(Path(d) / "presets")}):
            res = autostart.install()
            self.assertTrue(res["success"], res)
            self.assertTrue((Path(d) / "presets" / "FLUX_BEAUTY_MAPS.spexp").is_file())
            self.assertIn("preset", res["message"])
            # idempotent
            self.assertEqual(len(presets.install_presets()), len(presets.bundled_presets()))

    def test_a_project_keeps_its_presets(self) -> None:
        from features.folder_manager.project_init import create_project, set_painter_presets
        with tempfile.TemporaryDirectory() as d:
            p = create_project("INSECT", Path(d), painter_presets=["FLUX_BEAUTY_MAPS"])
            self.assertEqual(presets.project_presets(p), ["FLUX_BEAUTY_MAPS"])
            cfg = json.loads(setup_path(p, "project.json").read_text())
            from features.folder_manager.project_config import validate_project_config
            self.assertEqual(validate_project_config(cfg), [])
            set_painter_presets(p, ["FLUX_BEAUTY_MAPS", "FLUX_UTIL_MAPS"])
            self.assertEqual(len(presets.project_presets(p)), 2)
            # 2026-09-26: a new project starts with the BEAUTY preset ticked.
            q = create_project("OTHER", Path(d))
            self.assertEqual(presets.project_presets(q), ["FLUX_BEAUTY_MAPS"])

    def test_the_old_names_become_the_flux_ones(self) -> None:
        from features.folder_manager.project_init import create_project
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"FLUX_SP_PRESETS_DIR": str(Path(d) / "presets")}):
            p = create_project("OLD", Path(d), painter_presets=["LR_INSECT_BEAUTY_MAPS"])
            self.assertEqual(presets.project_presets(p), ["FLUX_BEAUTY_MAPS"])
            dest = Path(d) / "presets"
            dest.mkdir()
            src = presets._BUNDLED_DIR / "FLUX_BEAUTY_MAPS.spexp"
            (dest / "LR_INSECT_BEAUTY_MAPS.spexp").write_bytes(src.read_bytes())
            (dest / "LR_INSECT_UTIL_MAPS.spexp").write_bytes(b"edited by the user")
            presets.install_presets()
            self.assertFalse((dest / "LR_INSECT_BEAUTY_MAPS.spexp").exists())
            self.assertTrue((dest / "LR_INSECT_UTIL_MAPS.spexp").exists())  # not ours: kept


if __name__ == "__main__":
    unittest.main()
