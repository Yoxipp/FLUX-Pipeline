# Rig preset: skins_of keeps polygon meshes only. A rig also skins NURBS ribbons or
# curves; passing them on made MFnMesh raise "object is incompatible with MFnMesh
# constructor" (2026-09-27). Maya is faked.

from __future__ import annotations

import unittest
from unittest import mock

from dcc.maya import maya_usd_presets as mp


class _Cmds:
    types = {"|body|bodyShape": "mesh", "|ribbon|ribbonShape": "nurbsSurface", "|crv|crvShape": "nurbsCurve"}

    def ls(self, *a, type=None, **kw):
        return ["skinCluster1"] if type == "skinCluster" else []

    def skinCluster(self, sk, query=True, influence=False, geometry=False):
        return ["|root|spine"] if influence else list(self.types)

    def nodeType(self, node):
        return self.types[node]

    def listRelatives(self, node, parent=False, fullPath=True):
        return [node.rsplit("|", 1)[0]]


class SkinsOf(unittest.TestCase):
    def test_only_polygon_meshes_are_exported(self) -> None:
        with mock.patch.object(mp, "cmds", _Cmds()), mock.patch.object(mp, "_long", lambda n: n):
            self.assertEqual(mp.skins_of(["|root|spine"]), [("|body", "skinCluster1")])


if __name__ == "__main__":
    unittest.main()
