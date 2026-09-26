# test_mari_flux_node.py - the FLUX Export custom node of the Mari bridge (2026-09-26).

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dcc.mari import mari_bridge as b


class FakeNode:
    def __init__(self, name, type_id, src=None, baked=None):
        self._name, self._type, self._src, self._baked = name, type_id, src, baked
        self.meta, self.lists, self.export_path = {}, {}, "C:/orig/$UDIM.exr"

    def name(self): return self._name
    def typeID(self): return self._type
    def inputNode(self, port): return self._src
    def metadata(self, key): return self.meta[key]
    def setMetadata(self, key, value): self.meta[key] = value
    def setMetadataItemList(self, key, items): self.lists[key] = items
    def setMetadataDisplayName(self, key, label): pass
    # Bake Point
    def hasBakedResult(self): return bool(self._baked)
    def isBakedResultUpToDate(self): return bool(self._baked)
    def exportPath(self): return self.export_path
    def setExportPath(self, path): self.export_path = path

    def exportBakedResult(self, *args):
        folder, template = os.path.split(self.export_path)
        Path(folder, template.replace("$UDIM", "1001")).write_bytes(b"x")


class FakeItem:
    def __init__(self): self.template = ""
    def setSourceNode(self, node): self.node = node
    def setFileTemplate(self, template): self.template = template
    def errorStringList(self): return []


def fake_mari(nodes, calls):
    def export_textures(items, out_dir, *overrides):
        calls.append(("em", items[0].node.name(), overrides))
        Path(out_dir, items[0].template.replace("$UDIM", "1001")).write_bytes(b"x")

    graph = SimpleNamespace(nodeList=lambda: nodes)
    geo = SimpleNamespace(name=lambda: "Utah", nodeGraph=lambda: graph, channelList=lambda: [],
                          patchList=lambda: [1])
    return SimpleNamespace(
        geo=SimpleNamespace(current=lambda: geo), ExportItem=FakeItem,
        exports=SimpleNamespace(addExportItem=lambda item, g: calls.append(("add",)),
                                exportTextures=export_textures,
                                removeExportItem=lambda item, g: calls.append(("remove",))),
        Image=SimpleNamespace(DEFAULT_OPTIONS=0))


class FluxExportNode(unittest.TestCase):
    def test_map_list_matches_flux_map_tokens(self):
        from dcc.texture_publish import MAP_ALIASES
        self.assertEqual(sorted(b.FLUX_MAPS), sorted(MAP_ALIASES))

    def test_map_is_guessed_from_the_node_before(self):
        self.assertEqual(b.guess_map("BAKE_COL"), "BCOL")
        self.assertEqual(b.guess_map("Bake Point ROUGH"), "ROUGH")
        self.assertEqual(b.guess_map("zdisp_bake"), "ZDISP")
        self.assertEqual(b.guess_map("Height"), "DISP")
        self.assertEqual(b.guess_map("whatever"), "BCOL")

    def _nodes(self):
        bake_ok = FakeNode("BAKE_COL", "Bake_Point", baked=True)
        bake_old = FakeNode("BAKE_ROUGH", "Bake_Point", baked=False)
        n1 = FakeNode("FLUX_BCOL", "FLUX/FLUX Export", src=bake_ok)
        n2 = FakeNode("FLUX Export", "FLUX_Export", src=bake_old)
        free = FakeNode("FLUX Export1", "FLUX_Export")
        return [bake_ok, bake_old, n1, n2, free]

    def test_info_lists_the_flux_nodes_with_their_map(self):
        nodes = self._nodes()
        with mock.patch.object(b, "mari", fake_mari(nodes, [])), mock.patch.object(b, "_MARI_AVAILABLE", True):
            res = b._do_info()
        self.assertEqual(res["mode"], "nodes")
        self.assertEqual([c["name"] for c in res["channels"]], ["BCOL", "ROUGH", "BCOL (2)"])
        self.assertEqual(res["channels"][0]["baked"], True)
        self.assertEqual(res["channels"][1]["baked"], False)
        self.assertEqual(res["channels"][2]["input"], "")
        # A node made from the palette got its "Map FLUX" list.
        self.assertEqual(nodes[3].lists[b.META_MAP], b.FLUX_MAPS)

    def test_export_uses_the_bake_when_up_to_date_else_the_export_manager(self):
        nodes, calls = self._nodes(), []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(b, "mari", fake_mari(nodes, calls)), mock.patch.object(b, "_MARI_AVAILABLE", True), \
                mock.patch.object(b, "_diag", lambda msg: None):
            res = b._do_export(tmp, "auto", None, {"*": "jpg", "ROUGH": "exr"}, {"ROUGH": 512})
            names = sorted(os.listdir(tmp))
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["mode"], "nodes")
        self.assertEqual(names, ["BCOL.1001.tif", "ROUGH.1001.exr"])
        # BCOL came from the baked result (no Export Manager), the Bake Point path restored.
        self.assertEqual(nodes[0].export_path, "C:/orig/$UDIM.exr")
        self.assertEqual([c[1] for c in calls if c[0] == "em"], ["FLUX Export"])
        self.assertIn(("remove",), calls)
        self.assertIn("rien n'est branche", " ".join(res["errors"]))

    def test_no_flux_node_keeps_the_channel_export(self):
        with mock.patch.object(b, "mari", fake_mari([], [])), mock.patch.object(b, "_MARI_AVAILABLE", True):
            res = b._do_info()
        self.assertEqual(res["mode"], "channels")


if __name__ == "__main__":
    unittest.main()
