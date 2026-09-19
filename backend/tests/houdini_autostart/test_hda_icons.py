# Live 2026-09-19: the FLUX HDAs showed no logo. Houdini 22 does not draw a PNG stored
# in an IconImage section (hou.qt.Icon fails on it); an IconSVG section is drawn.

from __future__ import annotations

import unittest
from pathlib import Path

from dcc.houdini.hda import (
    flux_anim_hda, flux_crowd_hda, flux_exporter_hda, flux_importer_hda, flux_importer_lop_hda,
    flux_lighting_hda, flux_shot_switch_hda,
)

_SVG = Path(flux_importer_hda.__file__).parents[3] / "resources" / "shelves" / "houdini" / "flux_hda.svg"


class HdaIcons(unittest.TestCase):
    def test_the_logo_is_a_scalable_svg(self) -> None:
        text = _SVG.read_text(encoding="utf-8")
        self.assertIn("viewBox=", text)
        self.assertIn("<path", text)

    def test_every_builder_embeds_the_svg_icon(self) -> None:
        pm = flux_importer_hda.PYTHON_MODULE
        codes = {
            "importer": flux_importer_hda._build_code("x.hda", pm),
            "importer_lop": flux_importer_lop_hda._build_code("x.hda", pm),
            "anim": flux_anim_hda._build_code("x.hda"),
            "exporter": flux_exporter_hda._build_code("x.hda", flux_exporter_hda.PYTHON_MODULE),
            "lighting": flux_lighting_hda._build_code("x.hda"),
            "shot": flux_shot_switch_hda._build_code("x.hda"),
            "crowd": flux_crowd_hda._build_code("x.hda"),
        }
        for name, code in codes.items():
            with self.subTest(name):
                self.assertIn('"IconSVG"', code)
                self.assertIn("opdef:.?IconSVG", code)
                self.assertIn("flux_hda.svg", code)
                self.assertNotIn("IconImage", code)


class CrowdHda(unittest.TestCase):
    def test_the_crowd_node_is_valid_python_and_has_the_geometry_menu(self) -> None:
        code = flux_crowd_hda._build_code("x.hda")
        compile(code, "build", "exec")
        compile(flux_crowd_hda.MODULE_FUNCTIONS, "module", "exec")
        compile(flux_crowd_hda.BOOTSTRAP, "bootstrap", "exec")
        for token in ('"geo_display"', '"points_sop"', "StringToggle", "/crowd/**/geo/proxy"):
            self.assertIn(token, code)
        for fn in ("def generate", "def publish", "def menu_assets", "def menu_clips"):
            self.assertIn(fn, flux_crowd_hda.MODULE_FUNCTIONS)


if __name__ == "__main__":
    unittest.main()
