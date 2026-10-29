# _fake_dcc.py — tiny stand-ins for `hou` and `maya.cmds` (P6a tests). The code the
# nodes send really runs against them through the fake bridges: it proves what is sent
# and how the answer is read, NOT that Houdini or Maya accept it (live check by the maintainer).

from __future__ import annotations

import fnmatch
import sys
import types
from typing import Any, Dict, List, Optional


# -- hou ---------------------------------------------------------------------------------

class _Parm:
    def __init__(self, node: "_HNode", name: str, value: Any) -> None:
        self.node, self.name, self.value = node, name, value

    def eval(self):
        return self.value

    def evalAtFrame(self, frame):  # noqa: N802 (hou API)
        return str(self.value).replace("$F4", f"{int(frame):04d}")

    def set(self, value):
        self.value = value


class _HType:
    def __init__(self, name: str, category: str) -> None:
        self._name, self._cat = name, category

    def name(self):
        return self._name

    def category(self):
        return types.SimpleNamespace(name=lambda: self._cat)


class _HNode:
    def __init__(self, hou: "FakeHou", path: str, type_name: str, category: str = "Sop",
                 parms: Optional[Dict[str, Any]] = None) -> None:
        self._hou, self._path = hou, path
        self._type = _HType(type_name, category)
        self.parms = {k: _Parm(self, k, v) for k, v in (parms or {}).items()}
        self.cooks = 0
        self.renders: List[Any] = []

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def type(self):
        return self._type

    def parm(self, name):
        return self.parms.get(name)

    def allSubChildren(self):  # noqa: N802
        prefix = self._path.rstrip("/") + "/"
        return [n for p, n in sorted(self._hou.nodes.items()) if p.startswith(prefix)]

    def cook(self, force=False):
        self.cooks += 1

    def render(self, frame_range=None, **kwargs):
        self.renders.append(frame_range)


class FakeHou:
    def __init__(self) -> None:
        self.nodes: Dict[str, _HNode] = {}
        self.selected: List[str] = []
        self.file = "untitled.hip"
        self.unsaved = False
        self.saved: List[str] = []
        self.add("/", "root", "Manager")
        self.add("/obj", "obj", "Manager")
        self.add("/out", "out", "Manager")
        self.hipFile = types.SimpleNamespace(
            path=lambda: self.file, hasUnsavedChanges=lambda: self.unsaved,
            load=self._load, save=self._save, clear=self._clear, setName=self._set_name)

    def add(self, path, type_name, category="Sop", **parms) -> _HNode:
        self.nodes[path] = _HNode(self, path, type_name, category, parms)
        return self.nodes[path]

    def node(self, path):
        return self.nodes.get(path)

    def selectedNodes(self):  # noqa: N802
        return [self.nodes[p] for p in self.selected if p in self.nodes]

    def frame(self):
        return 1001

    def _load(self, path, **kwargs):
        self.file, self.unsaved = path, False

    def _save(self, path=None, **kwargs):
        if path:
            self.file = path
        self.saved.append(self.file)
        self.unsaved = False

    def _clear(self, **kwargs):
        self.file, self.unsaved = "untitled.hip", False

    def _set_name(self, path):
        self.file = path

    def run(self, code: str) -> Any:
        """What flux_houdini_server /run does: exec with `hou`, give back `result`."""
        ns = {"hou": self}
        exec(compile(code, "<fake hou>", "exec"), ns)
        return ns.get("result")


# -- maya.cmds ---------------------------------------------------------------------------

class FakeCmds:
    def __init__(self) -> None:
        self.scene = ""
        self.modified = False
        self.attrs: Dict[str, Any] = {}
        self.nodes: Dict[str, str] = {}      # long name -> type
        self.calls: List[tuple] = []

    def file(self, *args, **kw):
        self.calls.append(("file", args, kw))
        if kw.get("q"):
            if kw.get("sceneName"):
                return self.scene
            if kw.get("modified"):
                return self.modified
        if kw.get("new"):
            self.scene, self.modified = "", False
        elif kw.get("open"):
            self.scene, self.modified = args[0], False
        elif "rename" in kw:
            self.scene = kw["rename"]
        elif kw.get("save"):
            self.modified = False
        elif kw.get("reference"):
            return [f"{kw.get('namespace')}:root"]
        return None

    def ls(self, *args, long=False, type=None, **kw):  # noqa: A002 (maya API)
        return [n for n, t in self.nodes.items() if type in (None, t)]

    def setAttr(self, plug, *values, **kw):  # noqa: N802
        self.attrs[plug] = values[0] if len(values) == 1 else list(values)

    def getAttr(self, plug):  # noqa: N802
        value = self.attrs.get(plug)
        return [tuple(value)] if isinstance(value, list) else value

    def about(self, version=False):
        return "2024"


def install_fake_maya(cmds: FakeCmds) -> Dict[str, Any]:
    """Put a fake `maya.cmds` in sys.modules; returns what to restore."""
    saved = {k: sys.modules.get(k) for k in ("maya", "maya.cmds")}
    maya = types.ModuleType("maya")
    mod = types.ModuleType("maya.cmds")
    for name in ("file", "ls", "setAttr", "getAttr", "about"):
        setattr(mod, name, getattr(cmds, name))
    maya.cmds = mod
    sys.modules["maya"], sys.modules["maya.cmds"] = maya, mod
    return saved


def restore_modules(saved: Dict[str, Any]) -> None:
    for key, value in saved.items():
        if value is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = value


def maya_command_port_handler(cmd: str) -> str:
    """The commandPort of Maya (Python source type): exec the line."""
    exec(compile(cmd, "<fake commandPort>", "exec"), {"__name__": "__main__"})
    return "None"
