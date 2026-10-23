# P3 (2026-10-23): logic nodes (02_NODES §4): switch, compare (matches pattern too),
# and / or / not, is_empty, exists, select. Bodies called directly with a fake ctx.

from __future__ import annotations

import asyncio
import inspect
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from flux_flows.nodes import registry
from flux_flows.nodes.contract import EXEC_KEY, NodeError

CTX = SimpleNamespace(context={}, log=lambda *a, **k: None)


def call(node_type, inputs=None, params=None, ctx=CTX):
    res = registry.get_node(node_type).func(ctx, dict(inputs or {}), dict(params or {}))
    return asyncio.run(res) if inspect.isawaitable(res) else res


class Switch(unittest.TestCase):
    def branch(self, value, cases, kind="str"):
        return call("logic.switch", {"value": value}, {"cases": cases, "type": kind})[EXEC_KEY]

    def test_exact_value_then_default(self):
        self.assertEqual(self.branch("houdini", ["maya", "houdini"]), "case_1")
        self.assertEqual(self.branch("mayapy", ["maya", "houdini"]), "default")
        self.assertEqual(self.branch("ma*", ["ma*"]), "case_0")       # no pattern: literal match only
        self.assertEqual(self.branch("maya", ["*"]), "default")
        self.assertEqual(self.branch("anything", []), "default")

    def test_typed_cases(self):
        self.assertEqual(self.branch("2", [1, 2], "int"), "case_1")
        self.assertEqual(self.branch(0.5, ["0.50"], "float"), "case_0")
        with self.assertRaisesRegex(NodeError, "type int"):
            self.branch("x", [1], "int")

    def test_invalid_params(self):
        for cases, kind in ((list(range(9)), "str"), ([1], "bool")):
            with self.assertRaises(NodeError) as err:
                self.branch(1, cases, kind)
            self.assertEqual(err.exception.code, "E_PARAM_INVALID")


class Compare(unittest.TestCase):
    def cmp(self, op, a, b):
        return call("logic.compare", {"a": a, "b": b}, {"op": op})["result"]

    def test_ops(self):
        self.assertTrue(self.cmp("eq", 3, 3))
        self.assertTrue(self.cmp("ne", "a", "b"))
        self.assertTrue(self.cmp("lt", "2", 10))          # numbers when one side is not text
        self.assertFalse(self.cmp("lt", "b", "a"))        # text against text
        self.assertTrue(self.cmp("ge", 3, 3.0))
        self.assertTrue(self.cmp("contains", ["a", "b"], "b"))
        self.assertTrue(self.cmp("contains", "shot_010", "010"))
        self.assertTrue(self.cmp("startswith", "shot_010", "shot"))
        self.assertTrue(self.cmp("endswith", "a.abc", ".abc"))

    def test_matches_pattern(self):
        self.assertTrue(self.cmp("matches", "shot_010.abc", "*.abc ^*_tmp*"))
        self.assertFalse(self.cmp("matches", "shot_010_tmp.abc", "*.abc ^*_tmp*"))
        self.assertFalse(self.cmp("matches", "shot_010.usd", "*.abc"))

    def test_errors(self):
        with self.assertRaisesRegex(NodeError, "ne se comparent pas"):
            self.cmp("lt", "a", 1)
        with self.assertRaises(NodeError) as err:
            self.cmp("like", 1, 1)
        self.assertEqual(err.exception.code, "E_PARAM_INVALID")


class Booleans(unittest.TestCase):
    def test_and_or_not(self):
        self.assertTrue(call("logic.and", {"a": True, "b": True})["result"])
        self.assertFalse(call("logic.and", {"a": True, "b": True, "c": None, "d": False})["result"])
        self.assertTrue(call("logic.or", {"a": False, "b": False, "c": True})["result"])
        self.assertFalse(call("logic.or", {"a": False, "b": False})["result"])
        self.assertFalse(call("logic.not", {"value": True})["result"])

    def test_not_a_bool_is_refused(self):
        with self.assertRaisesRegex(NodeError, "booleen attendu"):
            call("logic.and", {"a": True, "b": 1})
        with self.assertRaisesRegex(NodeError, "booleen attendu"):
            call("logic.or", {"a": True})              # b is required
        with self.assertRaisesRegex(NodeError, "booleen attendu"):
            call("logic.not", {"value": "true"})

    def test_is_empty(self):
        for value in (None, "", [], {}, ()):
            self.assertTrue(call("logic.is_empty", {"value": value})["result"], value)
        for value in (0, False, " ", [None], {"a": 1}):
            self.assertFalse(call("logic.is_empty", {"value": value})["result"], value)

    def test_select(self):
        self.assertEqual(call("logic.select", {"condition": True, "a": "maya", "b": "houdini"})["value"], "maya")
        self.assertEqual(call("logic.select", {"condition": False, "a": "maya", "b": "houdini"})["value"], "houdini")
        with self.assertRaises(NodeError):
            call("logic.select", {"condition": "yes", "a": 1, "b": 2})


class Exists(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="flux_logic_")).resolve()
        (self.root / "DAILY").mkdir()
        (self.root / "DAILY" / "a.abc").write_text("x")
        self.patch = mock.patch("core.paths.get_flux_root", return_value=self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_exists(self):
        self.assertEqual(call("logic.exists", {"path": "$FLUX/DAILY"}), {"result": True, "is_dir": True})
        self.assertEqual(call("logic.exists", {"path": "$FLUX/DAILY/a.abc"}), {"result": True, "is_dir": False})
        self.assertEqual(call("logic.exists", {"path": str(self.root / "nope")}), {"result": False, "is_dir": False})
        ctx = SimpleNamespace(context={"project_path": str(self.root / "DAILY")})
        self.assertTrue(call("logic.exists", {"path": "a.abc"}, ctx=ctx)["result"])   # relative to the project
        with self.assertRaisesRegex(NodeError, "vide"):
            call("logic.exists", {"path": ""})


if __name__ == "__main__":
    unittest.main()
