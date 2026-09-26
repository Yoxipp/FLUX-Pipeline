# FLUX Anim v2 served module (2026-09-26): one row per character, FLUX offline
# keeps the loaded layer, no ghost target prim, a missing version falls back to LAST,
# a clip takes a free instance of its asset, errors are never cached.

from __future__ import annotations

import unittest

from dcc.houdini.hda import flux_anim_hda
from tests.houdini_autostart.test_importer_component import _Node

SHOT = {"kind": "shot", "key": "SEQ001_SHOT010_ANIM_DINGO", "seq": "SEQ001", "shot": "SHOT010",
        "task": "ANIM", "character": "DINGO", "name": "DINGO", "last": "",
        "versions": {"v001": "/p/DINGO_v001.usd", "v002": "/p/DINGO_v002.usd"}}
CLIP = {"kind": "clip", "key": "CHAR_ANIM_DINGO_walk", "name": "DINGO", "character": "DINGO",
        "clip": "walk", "last": "/p/walk_LAST.usd", "versions": {}}


class AnimModule(unittest.TestCase):
    def setUp(self) -> None:
        self.ns: dict = {}
        exec(flux_anim_hda.MODULE_FUNCTIONS, self.ns)
        self.answer = {"ok": True, "items": [SHOT, CLIP]}
        self.posted: list[dict] = []

        def post(path, payload, **kw):
            self.posted.append(payload)
            return {"ok": True, "layer": "/hip/flux_anim/anim_2.usda", "range": None,
                    "rows": [{"target": r["target"], "info": {"joints": 3}, "noise": False, "error": ""}
                             for r in payload["rows"]]}
        self.ns["_get"] = lambda path, **kw: self.answer
        self.ns["_post"] = post
        self.ns["_reload"] = lambda node: None
        self.ns["_input_stage"] = lambda node: None
        self.ns["_layer_out"] = lambda node: "/hip/flux_anim/anim_2.usda"
        self.ns["_asset_prims"] = lambda stage: ["/assets/CHAR/DINGO_01", "/assets/CHAR/DINGO_02"]
        self.node = _Node(project="PROJ", seq="SEQ001", shot="SHOT010", anims=1,
                          anim_on1=1, anim_key1=SHOT["key"], anim_version1="v009", target_auto1=1,
                          target_prim1="", layer_path="/hip/flux_anim/anim_1.usda", status_msg="",
                          noise_amp=0.0, auto_range=0)

    def test_offline_keeps_the_current_layer(self) -> None:
        self.answer = {"ok": False, "error": "refused", "_offline": True}
        self.ns["resolve_path"](self.node, check=False)
        self.assertEqual(self.node.evalParm("layer_path"), "/hip/flux_anim/anim_1.usda")
        self.assertIn("FLUX injoignable", self.node.evalParm("status_msg"))
        self.assertEqual(self.posted, [])

    def test_unknown_version_falls_back_to_last_and_the_target_is_found(self) -> None:
        self.ns["resolve_path"](self.node, check=False)
        self.assertEqual(self.node.evalParm("anim_version1"), "LAST")
        self.assertEqual(self.posted[0]["rows"], [{"key": SHOT["key"], "version": "LAST",
                                                   "target": "/assets/CHAR/DINGO_01"}])
        self.assertEqual(self.node.evalParm("layer_path"), "/hip/flux_anim/anim_2.usda")
        self.assertIn("1 anim(s)", self.node.evalParm("status_msg"))

    def test_no_character_in_the_input_never_makes_a_ghost_prim(self) -> None:
        self.ns["_asset_prims"] = lambda stage: ["/assets/CHAR/BOB_01"]
        self.ns["resolve_path"](self.node, check=False)
        self.assertEqual(self.posted[0]["rows"], [])
        self.assertIn("aucun perso DINGO", self.node.evalParm("anim_info1"))

    def test_a_clip_takes_a_free_instance_of_its_asset(self) -> None:
        self.node.parm("anims").set(2)
        for name, value in (("anim_on2", 1), ("anim_key2", CLIP["key"]), ("anim_version2", "LAST"),
                            ("target_auto2", 1)):
            self.node.parm(name).set(value)
        self.ns["resolve_path"](self.node, check=False)
        targets = [r["target"] for r in self.posted[0]["rows"]]
        self.assertEqual(targets, ["/assets/CHAR/DINGO_01", "/assets/CHAR/DINGO_02"])

    def test_errors_are_not_cached(self) -> None:
        self.answer = {"ok": False, "_offline": True}
        self.assertEqual(self.ns["_items"](self.node), [])
        self.answer = {"ok": True, "items": [SHOT]}
        self.assertEqual(len(self.ns["_items"](self.node)), 1)


if __name__ == "__main__":
    unittest.main()
