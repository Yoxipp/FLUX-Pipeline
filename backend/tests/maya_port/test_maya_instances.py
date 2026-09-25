# U2: character instances of a Maya scene for the multi-instance shot anim publish.
# maya.cmds is faked: only the listing / numbering logic is tested here.

from __future__ import annotations

import unittest
from unittest import mock

from dcc.maya import maya_instances as mi


class FakeCmds:
    tops = ["|DINGO_02:rig", "|DINGO1:rig", "|dingo_hero", "|cam_grp", "|CHAR_RIG_DINGO_import", "|empty_DINGO"]
    meshes = {"|DINGO_02:rig": 3, "|DINGO1:rig": 3, "|dingo_hero": 2, "|cam_grp": 0,
              "|CHAR_RIG_DINGO_import": 1, "|empty_DINGO": 0}
    sources = {"|CHAR_RIG_DINGO_import": "assets/chara/DINGO/rig/CHAR_RIG_DINGO_null_LAST.mb"}

    def ls(self, assemblies=False, long=False):
        return list(self.tops)

    def listRelatives(self, node, **_kw):  # noqa: N802
        return [f"{node}|m{i}" for i in range(self.meshes[node])]

    def attributeQuery(self, attr, node, exists=True):  # noqa: N802
        return node in self.sources

    def getAttr(self, plug):  # noqa: N802
        return self.sources[plug.split(".")[0]]


class MayaInstances(unittest.TestCase):
    def test_instance_number(self) -> None:
        self.assertEqual(mi.instance_number("DINGO_02", "DINGO"), 2)
        self.assertEqual(mi.instance_number("dingo3", "DINGO"), 3)
        self.assertIsNone(mi.instance_number("DINGO", "DINGO"))
        self.assertIsNone(mi.instance_number("DINGO_hero", "DINGO"))

    def test_lists_named_and_imported_instances_with_meshes(self) -> None:
        with mock.patch.object(mi, "cmds", FakeCmds()):
            items = mi.list_instances("DINGO")
        self.assertEqual([(i["label"], i["instance"]) for i in items],
                         [("DINGO1", 1), ("DINGO_02", 2), ("dingo_hero", 3), ("CHAR_RIG_DINGO_import", 4)])
        self.assertEqual(items[1]["node"], "|DINGO_02:rig")


if __name__ == "__main__":
    unittest.main()
