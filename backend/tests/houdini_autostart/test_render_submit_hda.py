# FLUX Render Submit HDA (Tractor farm, ADR 0015): build code, module and route, without Houdini.
from __future__ import annotations

import unittest

from dcc.houdini.hda import flux_render_submit_hda as hda


class RenderSubmitHdaTests(unittest.TestCase):
    def test_code_compiles(self) -> None:
        compile(hda._build_code("x.hda"), "build", "exec")
        compile(hda.MODULE_FUNCTIONS, "module", "exec")
        compile(hda.BOOTSTRAP, "bootstrap", "exec")

    def test_parms_and_icon(self) -> None:
        code = hda._build_code("x.hda")
        for token in ('"shot_node"', '"source"', '"renderer"', '"freeze"', '"btn_submit"',
                      '"status_msg"', "min_num_inputs=1", '"IconSVG"'):
            self.assertIn(token, code)
        self.assertNotIn("IconImage", code)

    def test_module_calls_backend_route_only(self) -> None:
        mod = hda.MODULE_FUNCTIONS
        for fn in ("def submit", "def sync_shot", "def _write_input_stage", '"/render/submit"'):
            self.assertIn(fn, mod)
        self.assertNotIn("tractor", mod.lower().replace("tractor de flux", ""))

    def test_route_and_shelf_build(self) -> None:
        from features.shelf_manager import shelf_core
        from routers.dcc import router

        self.assertIn("/houdini/flux_render_submit/module", {r.path for r in router.routes})
        self.assertIn("flux_render_submit", {b[3] for b in shelf_core._HDA_BUILDS})


if __name__ == "__main__":
    unittest.main()
