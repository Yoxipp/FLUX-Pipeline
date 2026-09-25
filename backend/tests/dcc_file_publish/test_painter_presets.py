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


class PainterPresets(unittest.TestCase):
    def test_the_studio_presets_are_shipped(self) -> None:
        self.assertIn("LR_INSECT_BEAUTY_MAPS", presets.bundled_presets())
        self.assertIn("LR_INSECT_UTIL_MAPS", presets.bundled_presets())

    def test_installing_the_bridge_installs_the_presets(self) -> None:
        from dcc.substance_painter import autostart
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {
                "FLUX_SP_PLUGINS_DIR": str(Path(d) / "startup"), "FLUX_SP_PRESETS_DIR": str(Path(d) / "presets")}):
            res = autostart.install()
            self.assertTrue(res["success"], res)
            self.assertTrue((Path(d) / "presets" / "LR_INSECT_BEAUTY_MAPS.spexp").is_file())
            self.assertIn("preset", res["message"])
            # idempotent
            self.assertEqual(len(presets.install_presets()), len(presets.bundled_presets()))

    def test_a_project_keeps_its_presets(self) -> None:
        from features.folder_manager.project_init import create_project, set_painter_presets
        with tempfile.TemporaryDirectory() as d:
            p = create_project("INSECT", Path(d), painter_presets=["LR_INSECT_BEAUTY_MAPS"])
            self.assertEqual(presets.project_presets(p), ["LR_INSECT_BEAUTY_MAPS"])
            cfg = json.loads((p / "project.json").read_text())
            from features.folder_manager.project_config import validate_project_config
            self.assertEqual(validate_project_config(cfg), [])
            set_painter_presets(p, ["LR_INSECT_BEAUTY_MAPS", "LR_INSECT_UTIL_MAPS"])
            self.assertEqual(len(presets.project_presets(p)), 2)
            q = create_project("OTHER", Path(d))
            self.assertEqual(presets.project_presets(q), [])


if __name__ == "__main__":
    unittest.main()
