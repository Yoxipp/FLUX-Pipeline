# FLUX Anim served module: FLUX offline keeps the loaded file, no ghost target prim,
# a missing version falls back to LAST, an empty LAST takes the newest vNNN.

from __future__ import annotations

import unittest

from dcc.houdini.hda import flux_anim_hda
from tests.houdini_autostart.test_importer_component import _Node

ITEM = {"seq": "SEQ001", "shot": "SHOT010", "task": "ANIM", "character": "DINGO", "name": "DINGO",
        "last": "", "versions": {"v001": "/p/DINGO_v001.usd", "v002": "/p/DINGO_v002.usd"}}


class AnimModule(unittest.TestCase):
    def setUp(self) -> None:
        self.ns: dict = {}
        exec(flux_anim_hda.MODULE_FUNCTIONS, self.ns)
        self.answer = {"ok": True, "items": [ITEM]}
        self.ns["_get"] = lambda path, **kw: self.answer
        self.ns["_reload"] = lambda node: None
        self.ns["_input_stage"] = lambda node: None
        self.ns["_asset_prims"] = lambda stage: ["/assets/CHAR/DINGO_01"]
        self.node = _Node(project="PROJ", seq="SEQ001", shot="SHOT010", task="ANIM", character="DINGO",
                          version="v009", resolved_path="/p/old.usd", target_auto=1,
                          target_prim="/assets/CHAR/DINGO_01", status_msg="")

    def test_offline_keeps_the_current_file(self) -> None:
        self.answer = {"ok": False, "error": "refused", "_offline": True}
        self.ns["resolve_path"](self.node, check=False)
        self.assertEqual(self.node.evalParm("resolved_path"), "/p/old.usd")
        self.assertIn("FLUX injoignable", self.node.evalParm("status_msg"))

    def test_unknown_version_falls_back_to_the_newest(self) -> None:
        self.ns["resolve_path"](self.node, check=False)
        self.assertEqual(self.node.evalParm("version"), "LAST")
        self.assertEqual(self.node.evalParm("resolved_path"), "/p/DINGO_v002.usd")

    def test_no_character_in_the_input_never_makes_a_ghost_prim(self) -> None:
        self.ns["_asset_prims"] = lambda stage: ["/assets/CHAR/BOB_01"]
        self.ns["resolve_path"](self.node, check=False)
        self.assertEqual(self.node.evalParm("target_prim"), "/assets/CHAR/DINGO_01")   # unchanged
        self.assertIn("aucun perso DINGO", self.node.evalParm("status_msg"))

    def test_errors_are_not_cached(self) -> None:
        self.answer = {"ok": False, "_offline": True}
        self.assertEqual(self.ns["_items"](self.node), [])
        self.answer = {"ok": True, "items": [ITEM]}
        self.assertEqual(len(self.ns["_items"](self.node)), 1)


if __name__ == "__main__":
    unittest.main()
