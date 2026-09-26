# ADR 0023 points 12-13: base Camera Rig and Light Rig on the Flux shelf, created in one
# click. Maya is faked: the test checks the hierarchy, the camera settings, the locks,
# the dome choice (Arnold loaded or not) and that each rig is one undo step.

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from dcc.maya import maya_rigs


class _FakeCmds:
    """Just enough of maya.cmds: a DAG of names, attributes and the calls made."""

    def __init__(self, arnold: bool = False) -> None:
        self.parent_of: dict[str, str | None] = {}
        self.shapes: dict[str, str] = {}
        self.types: dict[str, str] = {}
        self.attrs: dict[str, object] = {}
        self.locked: set[str] = set()
        self.undo: list[str] = []
        self.selected: list[str] = []
        self.arnold = arnold

    def _new(self, name: str, kind: str, shape_kind: str | None = None) -> str:
        n, i = name, 1
        while n in self.parent_of:
            i += 1
            n = f"{name}{i}"
        self.parent_of[n] = None
        self.types[n] = kind
        if shape_kind:
            shape = f"{n}Shape"
            self.parent_of[shape] = n
            self.types[shape] = shape_kind
            self.shapes[n] = shape
        return n

    def undoInfo(self, openChunk=False, closeChunk=False):     # noqa: N802,N803
        self.undo.append("open" if openChunk else "close")

    def circle(self, name, **_kw):
        return [self._new(name, "transform", "nurbsCurve")]

    def camera(self, name):
        t = self._new(name, "transform", "camera")
        return [t, self.shapes[t]]

    def group(self, empty, name):
        return self._new(name, "transform")

    def directionalLight(self, name, intensity):             # noqa: N802
        t = self._new(name, "transform", "directionalLight")
        self.attrs[f"{self.shapes[t]}.intensity"] = intensity
        return self.shapes[t]

    def ambientLight(self, name, intensity):                 # noqa: N802
        t = self._new(name, "transform", "ambientLight")
        return self.shapes[t]

    def shadingNode(self, kind, asLight, name):              # noqa: N802,N803
        return self._new(name, "transform", kind)

    def rename(self, node, new):
        self.parent_of[new] = self.parent_of.pop(node)
        self.types[new] = self.types.pop(node)
        if node in self.shapes:
            self.shapes[new] = self.shapes.pop(node)
            self.parent_of[self.shapes[new]] = new
        return new

    def parent(self, node, parent):
        self.parent_of[node] = parent
        return [node]

    def listRelatives(self, node, parent=False, shapes=False, **_kw):   # noqa: N802
        if parent:
            p = self.parent_of.get(node)
            return [p] if p else None
        return [self.shapes[node]] if shapes and node in self.shapes else None

    def pluginInfo(self, name, query, loaded):              # noqa: N802
        return self.arnold

    def setAttr(self, plug, *values, lock=None, keyable=None, channelBox=None, type=None):   # noqa: N802,A002
        if lock:
            self.locked.add(plug)
        if values:
            self.attrs[plug] = values if len(values) > 1 else values[0]

    def attributeQuery(self, attr, node, exists):           # noqa: N802
        return f"{node}.{attr}" in self.attrs

    def addAttr(self, node, longName, dataType):             # noqa: N802,N803
        self.attrs[f"{node}.{longName}"] = ""

    def select(self, node, replace):
        self.selected = [node]


class MayaRigs(unittest.TestCase):
    def _run(self, func, arnold=False):
        fake = _FakeCmds(arnold)
        with mock.patch.object(maya_rigs, "cmds", fake):
            return func(), fake

    def test_camera_rig_imports_the_flux_file_then_namespaces_the_next_one(self) -> None:
        fake = _FakeCmds()
        imports: list[dict] = []

        def file(path, **kw):
            imports.append({"path": path, **kw})
            ns = kw.get("namespace", "")
            pre = f"{ns}:" if ns else ""
            root = f"|{pre}Flux_Cam_Rig"
            for n in (root, f"{root}|{pre}Cam", f"{root}|{pre}Cam|{pre}CamShape"):
                fake.parent_of[n] = None
            fake.types[f"{root}|{pre}Cam|{pre}CamShape"] = "camera"
            return list(fake.parent_of)[-3:]

        fake.file = file
        fake.objExists = lambda n: any(k.split("|")[-1] == n for k in fake.parent_of)
        fake.ls = lambda nodes, type, long: [n for n in nodes if fake.types.get(n) == type]
        fake.listRelatives = lambda n, parent=False, **_kw: [n.rsplit("|", 1)[0]] if parent else None
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

    def test_the_shipped_camera_rig_holds_the_rig_only(self) -> None:
        text = maya_rigs.CAM_RIG_FILE.read_text(encoding="cp1252")
        self.assertIn('createNode transform -n "Flux_Cam_Rig";', text)
        self.assertIn('createNode camera -n "CamShape" -p "Cam";', text)
        self.assertIn('setAttr ".flux_rig" -type "string" "camera";', text)
        self.assertIn('requires maya "2024";', text)             # opens in Maya 2024 and 2025
        for banned in ("select -ne :", '"persp', "C:/", "stereoCamera", "createNode script",
                       "AutoRig_", "Flux_Cam_Rig:"):
            self.assertNotIn(banned, text, banned)

    def test_light_rig_three_points_and_dome(self) -> None:
        res, cmds = self._run(maya_rigs.create_light_rig)
        for role in ("key", "fill", "rim", "dome"):
            self.assertEqual(cmds.parent_of[res[role]], res["group"], role)
        self.assertEqual(res["dome_kind"], "ambientLight")
        self.assertEqual(cmds.attrs[f"{res['group']}.flux_rig"], "light")
        self.assertEqual(cmds.undo, ["open", "close"])
        res, cmds = self._run(maya_rigs.create_light_rig, arnold=True)
        self.assertEqual(res["dome_kind"], "aiSkyDomeLight")
        self.assertEqual(cmds.types[cmds.shapes[res["dome"]]], "aiSkyDomeLight")

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
        src = Path(maya_rigs.__file__).read_text(encoding="utf-8")
        self.assertIn("def create_camera_rig", src)

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
