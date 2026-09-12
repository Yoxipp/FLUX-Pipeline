# test_nuke_bridge.py — Nuke import/publish helpers (V6 B1), no Nuke needed.
#
# The Nuke-side code is a pure string builder and the orchestration talks to the
# generic run(code) bridge, so both are testable by asserting the generated code
# and by mocking the bridge client + the publisher.

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from dcc.nuke import nuke_import, nuke_publish


class BuildReadNodeCode(unittest.TestCase):
    def test_single_file(self):
        code = nuke_import.build_read_node_code("C:\\proj\\CHAR_REN_HERO_null_LAST.exr")
        self.assertIn("nuke.nodes.Read(file=", code)
        self.assertIn("C:/proj/CHAR_REN_HERO_null_LAST.exr", code)  # backslashes normalised
        self.assertIn("'colorspace'", code)
        self.assertIn('"rendering"', code)                          # project default
        self.assertIn("result = _r.name()", code)
        self.assertNotIn("first", code)                             # no range for a still

    def test_sequence_sets_frame_range(self):
        code = nuke_import.build_read_node_code("/p/seq.%04d.exr", first=1001, last=1050)
        self.assertIn("'first'].setValue(1001)", code)
        self.assertIn("'last'].setValue(1050)", code)

    def test_custom_colorspace(self):
        code = nuke_import.build_read_node_code("/p/x.exr", colorspace="ACES - ACEScg")
        self.assertIn('"ACES - ACEScg"', code)


class ImportIntoNuke(unittest.TestCase):
    def test_resolves_then_creates_read(self):
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch(
                 "features.importer.importer_resolve.resolve_import_path",
                 return_value={"ok": True, "path": "/proj/x_LAST.exr", "ext": ".exr"},
             ), \
             mock.patch.object(nuke_import.nuke_client, "run",
                               return_value={"ok": True, "result": "Read1"}) as run:
            out = nuke_import.import_into_nuke("PROJ", "CHAR", "REN", "HERO", "null")
        self.assertEqual(out, {"ok": True, "node": "Read1", "path": "/proj/x_LAST.exr"})
        self.assertIn("nuke.nodes.Read", run.call_args[0][0])

    def test_unresolved_path_does_not_call_nuke(self):
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch(
                 "features.importer.importer_resolve.resolve_import_path",
                 return_value={"ok": False, "error": "nope"},
             ), \
             mock.patch.object(nuke_import.nuke_client, "run") as run:
            out = nuke_import.import_into_nuke("PROJ", "CHAR", "REN", "HERO", "null")
        self.assertFalse(out["ok"])
        run.assert_not_called()


class NukePublish(unittest.TestCase):
    def test_active_write_path_ok(self):
        with mock.patch.object(nuke_publish.nuke_client, "run",
                               return_value={"ok": True, "result": "/r/out.exr"}):
            self.assertEqual(nuke_publish.get_active_write_path(),
                             {"ok": True, "path": "/r/out.exr"})

    def test_active_write_path_none(self):
        with mock.patch.object(nuke_publish.nuke_client, "run",
                               return_value={"ok": True, "result": None}):
            out = nuke_publish.get_active_write_path()
        self.assertFalse(out["ok"])

    def test_publish_ingests_write_output(self):
        src = "/r/out.exr"
        with mock.patch.object(nuke_publish, "get_active_write_path",
                               return_value={"ok": True, "path": src}), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch("features.publisher.publish_core.publish_file",
                        return_value=Path("/proj/dest/x_LAST.exr")) as pf:
            out = nuke_publish.publish_from_nuke("PROJ", "desc", "adam")
        self.assertTrue(out["ok"])
        self.assertEqual(out["path"], str(Path("/proj/dest/x_LAST.exr")))
        # the resolved Write output is what gets ingested
        self.assertEqual(str(pf.call_args[0][0]), str(Path(src)))

    def test_publish_no_write_returns_error(self):
        with mock.patch.object(nuke_publish, "get_active_write_path",
                               return_value={"ok": False, "error": "No Write node"}):
            out = nuke_publish.publish_from_nuke("PROJ")
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
