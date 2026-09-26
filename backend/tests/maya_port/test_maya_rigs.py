# ADR 0023 points 12-13: base Camera Rig and Light Rig on the Flux shelf, created in one
# click by importing the maintainer's rig files (resources/rigs/maya). Maya is faked: the tests check
# the imported file, the namespace of a second rig, the flux_rig tag and one undo step
# per rig; the shipped files are checked to hold the rig only.

from __future__ import annotations

import unittest
from unittest import mock

from dcc.maya import maya_rigs


class _FakeCmds:
    """Just enough of maya.cmds: created nodes, attributes and the calls made."""

    def __init__(self) -> None:
        self.parent_of: dict[str, str | None] = {}
        self.types: dict[str, str] = {}
        self.attrs: dict[str, object] = {}
        self.undo: list[str] = []
        self.selected: list[str] = []

    def undoInfo(self, openChunk=False, closeChunk=False):     # noqa: N802,N803
        self.undo.append("open" if openChunk else "close")

    def setAttr(self, plug, *values, type=None):               # noqa: N802,A002
        self.attrs[plug] = values if len(values) > 1 else values[0]

    def attributeQuery(self, attr, node, exists):           # noqa: N802
        return f"{node}.{attr}" in self.attrs

    def addAttr(self, node, longName, dataType):             # noqa: N802,N803
        self.attrs[f"{node}.{longName}"] = ""

    def select(self, node, replace):
        self.selected = [node]


class MayaRigs(unittest.TestCase):
    def _importing_fake(self, root_name: str, child: str, shape_type: str):
        """Fake cmds whose file import creates <ns:>root|<ns:>child|<ns:>childShape."""
        fake = _FakeCmds()
        imports: list[dict] = []

        def file(path, **kw):
            imports.append({"path": path, **kw})
            pre = f"{kw['namespace']}:" if kw.get("namespace") else ""
            root = f"|{pre}{root_name}"
            nodes = [root, f"{root}|{pre}{child}", f"{root}|{pre}{child}|{pre}{child}Shape"]
            for n in nodes:
                fake.parent_of[n] = None
            fake.types[nodes[2]] = shape_type
            return nodes

        fake.file = file
        fake.objExists = lambda n: any(k.split("|")[-1] == n for k in fake.parent_of)
        fake.ls = lambda nodes, long, type=None, lights=False: [
            n for n in nodes if (lights and fake.types.get(n, "").endswith("Light"))
            or (type and fake.types.get(n) == type)]
        fake.listRelatives = lambda n, parent=False, **_kw: [n.rsplit("|", 1)[0]] if parent else None
        return fake, imports

    def test_camera_rig_imports_the_flux_file_then_namespaces_the_next_one(self) -> None:
        fake, imports = self._importing_fake("Flux_Cam_Rig", "Cam", "camera")
        with mock.patch.object(maya_rigs, "cmds", fake):
            first = maya_rigs.create_camera_rig()
            second = maya_rigs.create_camera_rig()
        self.assertEqual(imports[0]["path"], str(maya_rigs.CAM_RIG_FILE).replace("\\", "/"))
        self.assertTrue(imports[0]["i"])
        self.assertNotIn("namespace", imports[0])
        self.assertEqual((first["root"], first["camera"], first["namespace"]),
                         ("|Flux_Cam_Rig", "|Flux_Cam_Rig|Cam", ""))
        self.assertEqual(imports[1]["namespace"], "CAM")
        self.assertEqual(second["root"], "|CAM:Flux_Cam_Rig")
        self.assertEqual(fake.attrs["|Flux_Cam_Rig.flux_rig"], "camera")
        self.assertEqual(fake.undo, ["open", "close", "open", "close"])

    def test_light_rig_imports_the_flux_file_then_namespaces_the_next_one(self) -> None:
        fake, imports = self._importing_fake("Flux_Light_Rig", "Light_Key", "directionalLight")
        with mock.patch.object(maya_rigs, "cmds", fake):
            first = maya_rigs.create_light_rig()
            second = maya_rigs.create_light_rig()
        self.assertEqual(imports[0]["path"], str(maya_rigs.LIGHT_RIG_FILE).replace("\\", "/"))
        self.assertEqual((first["root"], first["lights"], first["namespace"]),
                         ("|Flux_Light_Rig", ["|Flux_Light_Rig|Light_Key"], ""))
        self.assertEqual((imports[1]["namespace"], second["root"]), ("LIGHT", "|LIGHT:Flux_Light_Rig"))
        self.assertEqual(fake.attrs["|Flux_Light_Rig.flux_rig"], "light")
        self.assertEqual(fake.selected, ["|LIGHT:Flux_Light_Rig"])

    def test_the_shipped_rigs_hold_the_rig_only(self) -> None:
        cam = maya_rigs.CAM_RIG_FILE.read_text(encoding="cp1252")
        self.assertIn('createNode transform -n "Flux_Cam_Rig";', cam)
        self.assertIn('createNode camera -n "CamShape" -p "Cam";', cam)
        self.assertIn('setAttr ".flux_rig" -type "string" "camera";', cam)
        light = maya_rigs.LIGHT_RIG_FILE.read_text(encoding="cp1252")
        self.assertIn('createNode transform -n "Flux_Light_Rig";', light)
        for role in ("Key", "Fill", "Rim", "Dom"):
            self.assertIn(f'createNode transform -n "Light_{role}" -p "Flux_Light_Rig";', light)
        self.assertIn('setAttr ".flux_rig" -type "string" "light";', light)
        for name, text in (("cam", cam), ("light", light)):
            self.assertIn('requires maya "2024";', text)          # opens in Maya 2024 and 2025
            for banned in ("select -ne :", '"persp', "C:/", "stereoCamera", "createNode script",
                           "AutoRig_", "Remap_Lock_Cam\" -p", ":Flux_"):
                self.assertNotIn(banned, text, f"{name}: {banned}")

    def test_both_rigs_are_checkable_tools_of_the_flux_shelf(self) -> None:
        from features.shelf_manager.shelf_core import build_flux_shelf_mel, list_tools

        labels = {t["id"]: t["label"] for t in list_tools()}
        self.assertEqual((labels["cam_rig"], labels["light_rig"]), ("CAM", "LIGHT"))
        mel = build_flux_shelf_mel(["cam_rig", "light_rig"])
        self.assertIn("maya_rigs.create_camera_rig()", mel)
        self.assertIn("maya_rigs.create_light_rig()", mel)
        self.assertIn('"flux_cam.png"', mel)
        self.assertIn('"flux_light.png"', mel)
        bare = build_flux_shelf_mel([])
        self.assertNotIn("maya_rigs.create_camera_rig()", bare)
        self.assertNotIn("maya_rigs.create_light_rig()", bare)

    def test_a_selection_saved_before_the_rigs_existed_gets_them_checked(self) -> None:
        from features.shelf_manager import shelf_core

        store: dict = {"maya_shelf_tools": ["flux_anim"]}
        fake = mock.Mock(get=store.get, set=store.__setitem__)
        with mock.patch.object(shelf_core, "config", fake):
            self.assertEqual(shelf_core.get_shelf_tool_selection(),
                             ["flux_anim", "cam_rig", "light_rig"])
            shelf_core.set_shelf_tool_selection(["adam_rig"])
            self.assertEqual(shelf_core.get_shelf_tool_selection(), ["adam_rig"])
            store["maya_shelf_tools"] = []
            self.assertEqual(shelf_core.get_shelf_tool_selection(), [])


if __name__ == "__main__":
    unittest.main()
