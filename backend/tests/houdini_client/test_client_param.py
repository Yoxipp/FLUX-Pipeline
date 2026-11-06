# P6a refactor (2026-10-23): houdini_export / houdini_import take ``client=`` (the Flows
# session of a chosen instance); without it they use the singleton as before.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dcc.houdini import client as client_mod
from dcc.houdini import houdini_export, houdini_import


class FakeClient:
    def __init__(self) -> None:
        self.codes = []

    def run(self, code, timeout=600.0):
        self.codes.append(code)
        return {"ok": True, "result": {"rop": "/out/geo1", "parm": "sopoutput"}}

    def state(self):
        return {"selected_nodes": ["/obj/geo1/rop1"]}


class ClientParam(unittest.TestCase):
    def test_default_is_the_singleton(self) -> None:
        with mock.patch.object(houdini_export, "houdini_client") as single:
            single.run.return_value = {"ok": True}
            houdini_export.cook_rop("/out/rop1")
        single.run.assert_called_once()

    def test_export_functions_use_the_given_client(self) -> None:
        fake = FakeClient()
        with mock.patch.object(houdini_export, "houdini_client") as single:
            houdini_export.cook_rop("/out/rop1", client=fake)
            houdini_export.export_scene("/tmp/a.hip", client=fake)
            houdini_export.set_rop_output("/out/rop1", "/tmp/a.bgeo.sc", client=fake)
            houdini_export.export_geo("/obj/geo1/out", "/tmp/a.bgeo.sc", ".bgeo.sc", client=fake)
            houdini_export.export_via_node("/obj/geo1/out", ".bgeo.sc", "/tmp/a.bgeo.sc", client=fake)
        single.run.assert_not_called()
        self.assertEqual(len(fake.codes), 5)

    def test_import_functions_use_the_given_client(self) -> None:
        fake = FakeClient()
        with mock.patch.object(houdini_import, "houdini_client") as single:
            houdini_import.create_import_node("/obj/geo1", "/tmp/a.abc", client=fake)
            houdini_import.import_into_lop("/tmp/a.usd", "reference", client=fake)
            houdini_import.set_import_path("/obj/geo1/file1", "/tmp/a.abc", client=fake)
        single.run.assert_not_called()
        self.assertEqual(len(fake.codes), 3)

    def test_export_failure_names_the_exported_node_and_frame(self) -> None:
        # The real message of a guide deform failing upstream of a feather node.
        houdini_error = (
            "The attempted operation failed.\n"
            "Error: Invalid source /obj/sim/guidedeform.\n"
            "Error cooking /obj/sim/guidedeform at time -1.95833."
        )
        rop = mock.MagicMock()
        rop.type.return_value.name.return_value = "rop_geometry"
        rop.type.return_value.category.return_value.name.return_value = "Driver"
        rop.path.return_value = "/obj/body/feather"
        rop.render.side_effect = RuntimeError(houdini_error)
        fake_hou = mock.MagicMock()
        fake_hou.node.return_value = rop
        fake_hou.timeToFrame.side_effect = lambda t: round(t * 24 + 1)

        class ExecClient:
            def run(self, code):
                ns = {"hou": fake_hou}
                try:
                    exec(compile(code, "<flux_run>", "exec"), ns)
                except Exception as exc:
                    return {"ok": False, "error": str(exc)}
                return {"ok": True, "result": ns.get("result")}

        with tempfile.TemporaryDirectory() as tmp:
            resp = houdini_export.export_via_node(
                "/obj/body/feather", ".bgeo.sc", Path(tmp) / "a.bgeo.sc", client=ExecClient())
        self.assertFalse(resp["ok"])
        self.assertIn("Export of /obj/body/feather failed at frame -46.", resp["error"])
        self.assertIn("Error cooking /obj/sim/guidedeform", resp["error"])
        self.assertNotIn("The attempted operation failed", resp["error"])

    def test_public_transport_names(self) -> None:
        c = client_mod.HoudiniClient(port=1)
        with mock.patch.object(c, "_get", return_value={"ok": True}) as get, \
             mock.patch.object(c, "_post", return_value={"ok": True}) as post:
            c.get("/ping")
            c.post("/run", {"code": "x"}, timeout=5)
        get.assert_called_once_with("/ping", timeout=3.0)
        post.assert_called_once_with("/run", {"code": "x"}, timeout=5)


if __name__ == "__main__":
    unittest.main()
