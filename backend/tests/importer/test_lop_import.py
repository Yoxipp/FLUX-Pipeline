# LOP import (Reference / Payload / Sublayer): backend-side checks and the hou code
# sent to Houdini. The generated code itself was run in hython 22 (2026-09-24):
# reference bgeo.sc, payload abc added to the selected Reference LOP, sublayer
# obj / usda / bgeo.sc stacked on a selected Sublayer LOP.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

import dcc.houdini.houdini_import as hi
from routers import dcc as dcc_router


def _capture(file_path: str, mode: str, abs_path: str | None = None) -> tuple[dict, list[str]]:
    sent: list[str] = []

    def fake_run(code: str) -> dict:
        sent.append(code)
        return {"ok": True, "result": {"handled": True, "node_path": "/stage/x"}}

    with mock.patch.object(hi.houdini_client, "run", side_effect=fake_run):
        resp = hi.import_into_lop(file_path, mode, abs_path)
    return resp, sent


class ImportIntoLop(unittest.TestCase):
    def test_unknown_mode_refused(self) -> None:
        resp, sent = _capture("C:/p/a.usd", "inherit")
        self.assertFalse(resp["ok"])
        self.assertEqual(sent, [])

    def test_unreadable_ext_refused_when_explicit(self) -> None:
        resp, sent = _capture("C:/p/a.ma", "reference")
        self.assertFalse(resp["ok"])
        self.assertEqual(sent, [])

    def test_unreadable_ext_not_handled_in_auto(self) -> None:
        resp, sent = _capture("C:/p/a.ma", "auto")
        self.assertTrue(resp["ok"])
        self.assertFalse(resp["result"]["handled"])
        self.assertEqual(sent, [])

    def test_geometry_formats_are_lop_readable(self) -> None:
        for f in ("a.bgeo.sc", "a.abc", "a.obj", "a.fbx", "a.vdb", "a.usdc"):
            resp, sent = _capture("C:/p/" + f, "sublayer")
            self.assertTrue(resp["ok"], f)
            self.assertEqual(len(sent), 1, f)

    def test_payload_code_sets_payload_type_and_prim_from_stem(self) -> None:
        _, sent = _capture("C:\\p\\CHAR_GEO_box_v001.bgeo.sc", "payload")
        code = sent[0]
        self.assertIn("_mode = 'payload'", code)
        self.assertIn("'/CHAR_GEO_box_v001'", code)
        self.assertIn("'C:/p/CHAR_GEO_box_v001.bgeo.sc'", code)
        compile(code, "<lop>", "exec")

    def test_usd_prim_path_comes_from_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            usd = Path(tmp) / "DINGO.usda"
            usd.write_text("#usda 1.0\n", encoding="utf-8")
            with mock.patch("features.importer.usd_probe.probe_usd",
                            return_value={"default_prim": "DINGO", "kind": "component"}):
                _, sent = _capture("$FLUX/p/DINGO.usda", "reference", str(usd))
        self.assertIn("'/assets/DINGO'", sent[0])
        self.assertIn("'$FLUX/p/DINGO.usda'", sent[0])


class LopImportRoute(unittest.IsolatedAsyncioTestCase):
    async def test_missing_file_is_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("core.paths.get_project_path", return_value=Path(tmp)):
                req = dcc_router.HoudiniLopImportRequest(project="P", rel_path="nope.abc", mode="payload")
                with self.assertRaises(HTTPException) as ctx:
                    await dcc_router.houdini_import_lop(req)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_bad_mode_is_400(self) -> None:
        req = dcc_router.HoudiniLopImportRequest(project="P", rel_path="a.abc", mode="inherit")
        with self.assertRaises(HTTPException) as ctx:
            await dcc_router.houdini_import_lop(req)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_file_is_sent_with_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "geo" / "box.abc"
            f.parent.mkdir()
            f.write_bytes(b"x")
            with mock.patch("core.paths.get_project_path", return_value=Path(tmp)), \
                 mock.patch("flux_actions.switch.portable_paths_enabled", return_value=False), \
                 mock.patch.object(dcc_router, "_refuse_legacy"), \
                 mock.patch("dcc.houdini.houdini_import.import_into_lop",
                            return_value={"ok": True, "result": {"handled": True}}) as imp:
                req = dcc_router.HoudiniLopImportRequest(project="P", rel_path="geo/box.abc", mode="payload")
                resp = await dcc_router.houdini_import_lop(req)
        self.assertTrue(resp["ok"])
        args = imp.call_args[0]
        self.assertEqual(Path(args[0]), f.resolve())
        self.assertEqual(args[1], "payload")


if __name__ == "__main__":
    unittest.main()
