# 2026-09-19: the USD library source of FLUX Import had one menu mixing components,
# decors and shots. It now goes Type -> Classe (assets) / Sequence (shots) -> Element.

from __future__ import annotations

import unittest

from dcc.houdini.hda import flux_importer_hda

_ITEMS = [
    {"key": "component:DINGO", "name": "DINGO", "label": "Component  DINGO", "kind": "asset",
     "class": "CHAR", "seq": "", "versions": ["LAST"]},
    {"key": "component:BOX", "name": "BOX", "label": "Component  BOX", "kind": "asset",
     "class": "PROPS", "seq": "", "versions": ["LAST"]},
    {"key": "assembly:PARK", "name": "PARK", "label": "Assembly  PARK", "kind": "decor",
     "class": "SET", "seq": "", "versions": ["LAST"]},
    {"key": "shot:SEQ001/SHOT010", "name": "SHOT010", "label": "Shot  SEQ001 SHOT010", "kind": "shot",
     "class": "", "seq": "SEQ001", "versions": ["LAST"]},
    {"key": "shot:SEQ002/SHOT010", "name": "SHOT010", "label": "Shot  SEQ002 SHOT010", "kind": "shot",
     "class": "", "seq": "SEQ002", "versions": ["LAST"]},
]


class _Parm:
    def __init__(self, value):
        self.value = value

    def eval(self):
        return self.value

    def evalAsString(self):
        return self.value

    def set(self, value):
        self.value = value


class _Node:
    def __init__(self, **values):
        self.parms = {k: _Parm(v) for k, v in values.items()}

    def parm(self, name):
        return self.parms.get(name)

    def value(self, name):
        return self.parms[name].value


def _module() -> dict:
    ns: dict = {}
    exec(flux_importer_hda._MODULE_FUNCTIONS, ns)
    ns["_library"] = lambda node: _ITEMS
    ns["_apply"] = lambda node, r: None
    ns["_get"] = lambda *a, **kw: {"ok": True}
    return ns


def _node(**over) -> _Node:
    base = dict(project="P", source_mode="library", lib_kind="asset", lib_class="", lib_seq="",
                lib_item="", lib_version="LAST", status_msg="")
    base.update(over)
    return _Node(**base)


class LibraryMenus(unittest.TestCase):
    def test_elements_are_filtered_by_type_and_class(self) -> None:
        ns = _module()
        self.assertEqual(ns["menu_lib_item"](_node()), ["component:BOX", "BOX", "component:DINGO", "DINGO"])
        self.assertEqual(ns["menu_lib_item"](_node(lib_class="CHAR")), ["component:DINGO", "DINGO"])
        self.assertEqual(ns["menu_lib_item"](_node(lib_kind="decor")), ["assembly:PARK", "PARK"])
        self.assertEqual(ns["menu_lib_class"](_node()), ["", "Toutes", "CHAR", "CHAR", "PROPS", "PROPS"])

    def test_shots_are_filtered_by_sequence(self) -> None:
        ns = _module()
        self.assertEqual(ns["menu_lib_seq"](_node(lib_kind="shot")), ["", "Toutes", "SEQ001", "SEQ001",
                                                                       "SEQ002", "SEQ002"])
        self.assertEqual(ns["menu_lib_item"](_node(lib_kind="shot", lib_seq="SEQ002")),
                         ["shot:SEQ002/SHOT010", "SHOT010"])

    def test_changing_the_type_picks_a_matching_element(self) -> None:
        ns = _module()
        node = _node(lib_kind="shot", lib_item="component:DINGO")
        ns["on_lib_filter"](node)
        self.assertEqual(node.value("lib_item"), "shot:SEQ001/SHOT010")
        node = _node(lib_class="CHAR", lib_item="component:DINGO")
        ns["on_lib_filter"](node)
        self.assertEqual(node.value("lib_item"), "component:DINGO")

    def test_open_in_sets_the_filters_from_the_element(self) -> None:
        # "Open in" only sets lib_item: resolve puts Type / Classe / Sequence in line.
        ns = _module()
        node = _node(lib_kind="asset", lib_class="PROPS", lib_item="shot:SEQ002/SHOT010")
        ns["resolve_path"](node)
        self.assertEqual((node.value("lib_kind"), node.value("lib_class"), node.value("lib_seq")),
                         ("shot", "", ""))
        node = _node(lib_class="PROPS", lib_item="component:DINGO")
        ns["resolve_path"](node)
        self.assertEqual(node.value("lib_class"), "CHAR")

    def test_the_build_adds_the_filter_menus(self) -> None:
        code = flux_importer_hda._build_code("x.hda", flux_importer_hda.PYTHON_MODULE)
        compile(code, "build", "exec")
        for parm in ('"lib_kind"', '"lib_class"', '"lib_seq"', '"lib_item"'):
            self.assertIn(parm, code)
        self.assertLess(code.index('"lib_kind"'), code.index('"lib_item"'))
        compile(flux_importer_hda.PYTHON_MODULE, "bootstrap", "exec")
        self.assertIn("on_lib_filter", flux_importer_hda.PYTHON_MODULE)


if __name__ == "__main__":
    unittest.main()
