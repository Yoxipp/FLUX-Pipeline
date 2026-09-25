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
            "exporter": flux_exporter_hda._build_code("x.hda", "Sop"),
            "exporter_lop": flux_exporter_hda._build_code("x.hda", "Lop"),
            "exporter_obj": flux_exporter_hda._build_code("x.hda", "Object"),
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


class ExporterHda(unittest.TestCase):
    """2026-09-25: "FLUX offline" with the bridge green (the backend served none of
    the exporter routes), and the node always landed in /obj."""

    def test_the_exporter_builds_in_sop_lop_and_obj(self) -> None:
        compile(flux_exporter_hda.BOOTSTRAP, "bootstrap", "exec")
        compile(flux_exporter_hda.MODULE_FUNCTIONS, "module", "exec")
        for context, category in (("Sop", "sopNodeTypeCategory"), ("Lop", "lopNodeTypeCategory"),
                                  ("Object", "objNodeTypeCategory")):
            with self.subTest(context):
                code = flux_exporter_hda._build_code("x.hda", context)
                compile(code, "build", "exec")
                self.assertIn(category, code)
                self.assertIn("_NAME = 'flux_exporter'", code)
        self.assertIn('"source_obj"', flux_exporter_hda._build_code("x.hda", "Object"))
        self.assertNotIn('"source_obj"', flux_exporter_hda._build_code("x.hda", "Lop"))

    def test_the_backend_serves_every_route_the_exporter_calls(self) -> None:
        from routers.dcc import router
        paths = {r.path for r in router.routes}
        for route in ("/houdini/exporter/module", "/houdini/exporter/tokens", "/houdini/exporter/export"):
            self.assertIn(route, paths)
        for route in ("/dcc/houdini/exporter/module", "/dcc/houdini/exporter/tokens",
                      "/dcc/houdini/exporter/export"):
            self.assertIn(route, flux_exporter_hda.BOOTSTRAP + flux_exporter_hda.MODULE_FUNCTIONS)

    def test_publish_runs_off_the_main_thread(self) -> None:
        # FLUX cooks through the Houdini bridge on the main thread: a blocking callback
        # would make both sides wait on each other.
        self.assertIn("threading.Thread(target=_work", flux_exporter_hda.MODULE_FUNCTIONS)


if __name__ == "__main__":
    unittest.main()
