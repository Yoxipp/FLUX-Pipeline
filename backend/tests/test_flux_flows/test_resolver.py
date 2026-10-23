# P3 (2026-10-23): the one text resolver (01 §11) and POST /flows/preview (01 §14).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import resolver, rights
from flux_flows.nodes.contract import NodeError
from routers import flows as flows_router

CTX = {"user": "ADAM", "host": "PC1", "flow": "daily", "run_id": "r1", "date": "2026-10-23",
       "time": "10-30-00", "project": "DEMO", "project_path": "D:/P/DEMO", "shot": "SH010"}


def _vars(values):
    return values.__getitem__, list(values)


class Resolve(unittest.TestCase):
    def test_context_tokens_and_date_format(self) -> None:
        self.assertEqual(resolver.resolve("{project}/{shot}_{user}", CTX), "DEMO/SH010_ADAM")
        self.assertEqual(resolver.resolve("{date:%Y%m%d}_{time:%H%M}", CTX), "20261023_1030")
        self.assertEqual(resolver.resolve("{SHOT}", CTX), "SH010")   # case falls back to lower

    def test_non_strings_and_plain_text_untouched(self) -> None:
        self.assertEqual(resolver.resolve(12, CTX), 12)
        self.assertEqual(resolver.resolve("plain", CTX), "plain")
        self.assertEqual(resolver.resolve("$HIP/x_$SHOT", CTX), "$HIP/x_$SHOT")

    def test_literal_braces(self) -> None:
        self.assertEqual(resolver.resolve("{{shot}}", CTX), "{shot}")
        for bad in ("{", "a}", "{1x}"):
            with self.assertRaises(NodeError) as cm:
                resolver.resolve(bad, CTX)
            self.assertEqual(cm.exception.code, resolver.PARAM_INVALID)

    def test_unknown_token_suggests_closest(self) -> None:
        with self.assertRaises(NodeError) as cm:
            resolver.resolve("{shto}", CTX)
        self.assertEqual(cm.exception.code, resolver.UNKNOWN_TOKEN)
        self.assertEqual(cm.exception.details["suggestion"], "shot")
        self.assertIn("{shot}", cm.exception.message)
        with self.assertRaises(NodeError) as cm:
            resolver.resolve("{zzzzzz}", CTX)
        self.assertNotIn("suggestion", cm.exception.details)

    def test_known_key_without_value_says_when(self) -> None:
        with self.assertRaises(NodeError) as cm:
            resolver.resolve("{seq}", CTX)
        self.assertIn("evenement", cm.exception.message)
        with self.assertRaises(NodeError) as cm:
            resolver.resolve("{project}", {**CTX, "project": None})
        self.assertIn("projet", cm.exception.message)

    def test_format_only_for_date_and_time(self) -> None:
        with self.assertRaises(NodeError):
            resolver.resolve("{shot:%Y}", CTX)

    def test_variables(self) -> None:
        get, names = _vars({"dest": "D:/OUT", "count": 3})
        self.assertEqual(resolver.resolve("${dest}/{shot}_${count}", CTX, get, names), "D:/OUT/SH010_3")
        with self.assertRaises(NodeError) as cm:
            resolver.resolve("${dset}", CTX, get, names)
        self.assertEqual(cm.exception.details["suggestion"], "dest")
        with self.assertRaises(NodeError):
            resolver.resolve("${dest}", CTX)        # no variable lookup at all

    def test_flux_only_at_the_head_of_a_path_field(self) -> None:
        root = Path(tempfile.gettempdir())
        with mock.patch("core.paths.get_flux_root", return_value=root):
            out = resolver.resolve("$FLUX/DAILY/{shot}", CTX, path_field=True)
            self.assertEqual(Path(out), root / "DAILY" / "SH010")
            self.assertEqual(resolver.resolve("${FLUX}", CTX, path_field=True), str(root))
        self.assertEqual(resolver.resolve("$FLUX/x", CTX), "$FLUX/x")                     # not a path field
        self.assertEqual(resolver.resolve("a/$FLUX/x", CTX, path_field=True), "a/$FLUX/x")  # not at the head
        self.assertEqual(resolver.resolve("$FLUXY", CTX, path_field=True), "$FLUXY")

    def test_flux_without_root_is_a_clear_error(self) -> None:
        with mock.patch("core.paths.get_flux_root", side_effect=RuntimeError("FLUX_ROOT is not set")):
            with self.assertRaises(NodeError) as cm:
                resolver.resolve("$FLUX/x", CTX, path_field=True)
        self.assertEqual(cm.exception.code, resolver.PARAM_INVALID)

    def test_suggest_and_levenshtein(self) -> None:
        self.assertEqual(resolver.levenshtein("kitten", "sitting"), 3)
        self.assertEqual(resolver.suggest_token("projet", ["project", "shot"]), "project")
        self.assertIsNone(resolver.suggest_token("abcdef", ["shot"]))

    def test_tokens_in(self) -> None:
        self.assertEqual(resolver.tokens_in("{shot}_{date:%Y}_${dest}_$FLUX_{{x}}"), ["shot", "date", "$dest"])
        self.assertEqual(resolver.tokens_in(3), [])

    def test_context_from_name(self) -> None:
        ctx = resolver.context_from_name("D:/x/SEQ0010_SHOT0015_ANIM_null_v003.abc")
        self.assertEqual((ctx.get("seq"), ctx.get("shot")), ("SEQ0010", "SHOT0015"))
        self.assertEqual(resolver.context_from_name("readme.txt"), {})


class Preview(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self.client = TestClient(app)
        self.patch = mock.patch.object(rights, "current_rights", side_effect=lambda: rights.rights_from_data("ADAM", {}))
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()

    def _post(self, **body):
        r = self.client.post("/flows/preview", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_resolve(self) -> None:
        out = self._post(kind="resolve", text="{user}_${dest}", variables={"dest": "OUT"})
        self.assertEqual(out, {"result": "ADAM_OUT", "error": None})
        out = self._post(kind="resolve", text="{shto}")
        self.assertIsNone(out["result"])
        self.assertEqual((out["code"], out["suggestion"]), (resolver.UNKNOWN_TOKEN, "shot"))

    def test_pattern(self) -> None:
        out = self._post(kind="pattern", text="*.exr ^*_tmp*", names=["a.exr", "a_tmp.exr", "b.jpg"])
        self.assertEqual(out, {"result": ["a.exr"], "error": None})
        out = self._post(kind="pattern", text="[z-a]", names=["a"])
        self.assertIsNone(out["result"])
        self.assertTrue(out["error"])

    def test_unknown_kind(self) -> None:
        self.assertEqual(self.client.post("/flows/preview", json={"kind": "x"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
