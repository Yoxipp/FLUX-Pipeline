# P3 (2026-10-23): value operators (02_NODES §5): math, str_*, list_* (list_filter
# patterns, list_sort natural), path_*, path_flux_token, date_*. Bodies called
# directly with a fake ctx; a temp dir is FLUX_ROOT where $FLUX is involved.

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeError

CTX = SimpleNamespace(context={}, log=lambda *a, **k: None)


def call(node_type, inputs=None, params=None, ctx=CTX):
    res = registry.get_node(node_type).func(ctx, dict(inputs or {}), dict(params or {}))
    return asyncio.run(res) if inspect.isawaitable(res) else res


class MathNode(unittest.TestCase):
    def m(self, op, a, b=None):
        return call("operator.math", {"a": a, "b": b}, {"op": op})

    def test_ops(self):
        self.assertEqual(self.m("add", 3, 2), {"result": 5.0, "as_int": 5})
        self.assertEqual(self.m("sub", "3", 4.5)["result"], -1.5)
        self.assertEqual(self.m("div", 7, 2), {"result": 3.5, "as_int": 3})
        self.assertEqual(self.m("mod", 7, 3)["result"], 1.0)
        self.assertEqual(self.m("max", 1, 9)["result"], 9.0)
        self.assertEqual(self.m("round", 2.6)["result"], 3.0)
        self.assertEqual(self.m("floor", -0.5)["result"], -1.0)
        self.assertEqual(self.m("ceil", 0.1)["result"], 1.0)
        self.assertEqual(self.m("abs", -4)["result"], 4.0)
        self.assertEqual(self.m("add", 3)["result"], 3.0)     # b missing = 0

    def test_errors(self):
        with self.assertRaisesRegex(NodeError, "zero"):
            self.m("div", 1, 0)
        with self.assertRaisesRegex(NodeError, "nombre attendu"):
            self.m("add", "x", 1)
        with self.assertRaisesRegex(NodeError, "nombre attendu"):
            self.m("add", True, 1)
        with self.assertRaises(NodeError) as err:
            self.m("pow", 2, 2)
        self.assertEqual(err.exception.code, "E_PARAM_INVALID")


class Strings(unittest.TestCase):
    def test_join_split(self):
        self.assertEqual(call("operator.str_join", {"items": ["a", 1, None]}, {"sep": "_"})["text"], "a_1_")
        self.assertEqual(call("operator.str_split", {"text": "a_b_c"}, {"sep": "_"})["items"], ["a", "b", "c"])
        self.assertEqual(call("operator.str_split", {"text": " a  b "})["items"], ["a", "b"])
        with self.assertRaisesRegex(NodeError, "liste attendue"):
            call("operator.str_join", {"items": "ab"})

    def test_replace(self):
        self.assertEqual(call("operator.str_replace", {"text": "s_010_tmp"}, {"find": "_tmp"})["text"], "s_010")
        self.assertEqual(call("operator.str_replace", {"text": "v002"}, {"find": r"v(\d+)", "with": r"\1",
                                                                          "regex": True})["text"], "002")
        self.assertEqual(call("operator.str_replace", {"text": "a.b"}, {"find": ".", "with": "_"})["text"], "a_b")
        with self.assertRaises(NodeError) as err:
            call("operator.str_replace", {"text": "x"}, {"find": "(", "regex": True})
        self.assertEqual(err.exception.code, "E_PARAM_INVALID")
        with self.assertRaisesRegex(NodeError, "find"):
            call("operator.str_replace", {"text": "x"}, {"find": ""})

    def test_case_and_format(self):
        self.assertEqual(call("operator.str_case", {"text": "jerome"}, {"op": "upper"})["text"], "JEROME")
        self.assertEqual(call("operator.str_case", {"text": "  a "}, {"op": "strip"})["text"], "a")
        with self.assertRaises(NodeError):
            call("operator.str_case", {"text": "a"}, {"op": "swap"})
        self.assertEqual(call("operator.str_format", {"value": 7}, {"spec": "03d"})["text"], "007")
        self.assertEqual(call("operator.str_format", {"value": "7"}, {"spec": "03d"})["text"], "007")
        self.assertEqual(call("operator.str_format", {"value": "3.14159"}, {"spec": ".2f"})["text"], "3.14")
        self.assertEqual(call("operator.str_format", {"value": 7})["text"], "7")
        with self.assertRaises(NodeError):
            call("operator.str_format", {"value": "abc"}, {"spec": "03d"})


class Lists(unittest.TestCase):
    def test_length_get_unique_append(self):
        self.assertEqual(call("operator.list_length", {"list": [1, 2, 3]})["length"], 3)
        self.assertEqual(call("operator.list_get", {"list": ["a", "b"], "index": -1}), {"item": "b", "found": True})
        self.assertEqual(call("operator.list_get", {"list": ["a"], "index": 4}, {"default": "z"}),
                         {"item": "z", "found": False})
        self.assertEqual(call("operator.list_unique", {"list": ["a", "b", "a", 1, 1]})["items"], ["a", "b", 1])
        src = ["a"]
        self.assertEqual(call("operator.list_append", {"list": src, "item": "b"})["items"], ["a", "b"])
        self.assertEqual(src, ["a"])      # a new list

    def test_filter_patterns(self):
        items = ["D:/x/a.abc", "D:/x/b_tmp.abc", "D:/x/c.usd", {"path": "D:/tmp_dir/d.abc"}]
        out = call("operator.list_filter", {"list": items}, {"pattern": "*.abc ^*_tmp*"})
        self.assertEqual(out["items"], ["D:/x/a.abc", {"path": "D:/tmp_dir/d.abc"}])   # match on the name
        self.assertEqual(out["rejected"], ["D:/x/b_tmp.abc", "D:/x/c.usd"])
        # a word with "/" tests the whole path, only when match_on is path
        out = call("operator.list_filter", {"list": items}, {"pattern": "*.abc ^**/tmp_dir/**", "match_on": "path"})
        self.assertEqual(out["items"], ["D:/x/a.abc", "D:/x/b_tmp.abc"])
        out = call("operator.list_filter", {"list": items}, {"pattern": "*.abc ^**/tmp_dir/**"})
        self.assertEqual(len(out["items"]), 3)
        self.assertEqual(call("operator.list_filter", {"list": ["A.ABC"]}, {"pattern": "*.abc"})["items"], ["A.ABC"])
        with self.assertRaises(NodeError):
            call("operator.list_filter", {"list": items}, {"pattern": "*", "match_on": "ext"})

    def test_sort(self):
        names = ["v10", "v2", "V1", "v02b"]
        self.assertEqual(call("operator.list_sort", {"list": names})["items"], ["V1", "v2", "v02b", "v10"])
        self.assertEqual(call("operator.list_sort", {"list": names}, {"key": "name"})["items"],
                         ["v02b", "V1", "v10", "v2"])
        self.assertEqual(call("operator.list_sort", {"list": ["a/s2", "a/s10"]}, {"reverse": True})["items"],
                         ["a/s10", "a/s2"])
        with self.assertRaises(NodeError):
            call("operator.list_sort", {"list": names}, {"key": "color"})

    def test_sort_by_size(self):
        root = Path(tempfile.mkdtemp(prefix="flux_sort_"))
        try:
            for name, size in (("big", 30), ("small", 1), ("mid", 10)):
                (root / name).write_bytes(b"x" * size)
            files = [str(root / n) for n in ("big", "small", "mid")]
            out = call("operator.list_sort", {"list": files}, {"key": "size"})["items"]
            self.assertEqual([Path(p).name for p in out], ["small", "mid", "big"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class Paths(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="flux_op_")).resolve()
        self.patch = mock.patch("core.paths.get_flux_root", return_value=self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_join(self):
        out = call("operator.path_join", {"base": "$FLUX/DAILY", "a": "2026-10-23", "b": "", "c": "maya"})
        self.assertEqual(out["path"], f"{self.root.as_posix()}/DAILY/2026-10-23/maya")
        for bad in ("../x", "a/../../b", str(self.root)):
            with self.assertRaisesRegex(NodeError, "relatif"):
                call("operator.path_join", {"base": "$FLUX", "a": bad})

    def test_split_and_relative(self):
        self.assertEqual(call("operator.path_split", {"path": "D:\\x\\shot_010_v002.abc"}),
                         {"parent": "D:/x", "name": "shot_010_v002.abc", "stem": "shot_010_v002", "ext": ".abc"})
        out = call("operator.path_relative", {"path": "$FLUX/proj/a/b.abc", "base": "$FLUX/proj"})
        self.assertEqual(out["relative"], "a/b.abc")

    def test_flux_token_both_ways(self):
        absolute = self.root / "DAILY" / "IN"
        self.assertEqual(call("operator.path_flux_token", {"value": str(absolute)}),
                         {"token": "$FLUX/DAILY/IN", "path": absolute.as_posix()})
        self.assertEqual(call("operator.path_flux_token", {"value": "$FLUX/DAILY/IN"}),
                         {"token": "$FLUX/DAILY/IN", "path": absolute.as_posix()})
        outside = Path(tempfile.gettempdir()).resolve() / "elsewhere_flux_test"
        self.assertEqual(call("operator.path_flux_token", {"value": str(outside)})["token"], outside.as_posix())

    def test_flux_token_without_root(self):
        with mock.patch("core.paths.get_flux_root", return_value=None):
            with self.assertRaisesRegex(NodeError, "FLUX"):
                call("operator.path_flux_token", {"value": "$FLUX/DAILY"})
            with self.assertRaisesRegex(NodeError, "FLUX"):
                call("operator.path_join", {"base": "$FLUX/DAILY", "a": "x"})


class Dates(unittest.TestCase):
    def test_now(self):
        out = call("operator.date_now")
        when = datetime.fromisoformat(out["iso"])
        self.assertEqual(out["date"], when.strftime("%Y-%m-%d"))
        self.assertAlmostEqual(out["epoch"], when.timestamp())
        self.assertLess(abs(when.timestamp() - datetime.now().timestamp()), 5)

    def test_format_and_add(self):
        self.assertEqual(call("operator.date_format", {"iso": "2026-10-23T22:00:00"}, {"fmt": "%Y%m%d"})["text"],
                         "20261023")
        self.assertEqual(call("operator.date_format", {"iso": "2026-10-23"})["text"], "2026-10-23")
        self.assertEqual(call("operator.date_add", {"iso": "2026-10-23"}, {"days": -1})["iso"], "2026-10-22T00:00:00")
        self.assertEqual(call("operator.date_add", {"iso": "2026-12-31T22:00:00"}, {"hours": 3})["iso"],
                         "2027-01-01T01:00:00")
        with self.assertRaisesRegex(NodeError, "Date ISO"):
            call("operator.date_add", {"iso": "23/10/2026"})


if __name__ == "__main__":
    unittest.main()
