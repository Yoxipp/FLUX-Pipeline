# test_nuke_bridge.py — Nuke import/publish helpers (V6 B1), no Nuke needed.
#
# The Nuke-side code is a pure string builder and the orchestration talks to the
# generic run(code) bridge, so both are testable by asserting the generated code
# and by mocking the bridge client + the publisher.

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from dcc.nuke import flux_nuke_menu, nuke_import, nuke_publish


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


class BuildWriteExportCode(unittest.TestCase):
    def test_creates_write_on_selected_node_and_executes(self):
        code = nuke_publish.build_write_export_code("/p/x_LAST.exr")
        self.assertIn("nuke.selectedNodes()", code)             # acts on the selection
        self.assertIn("nuke.nodes.Write(inputs=[_src]", code)   # creates a Write
        self.assertIn("/p/x_LAST.exr", code)
        self.assertIn('"color_picking"', code)                  # project default colorspace
        self.assertIn("nuke.execute(_w", code)                  # renders it
        self.assertIn("nuke.delete(_w)", code)                  # cleans up the temp Write

    def test_named_node_and_options(self):
        code = nuke_publish.build_write_export_code(
            "/p/x.exr", options={"datatype": "16 bit half", "compression": "Zip (1 scanline)"},
            first=1001, last=1010, node_name="Merge1",
        )
        self.assertIn('nuke.toNode("Merge1")', code)
        self.assertIn('_w["datatype"].setValue("16 bit half")', code)
        self.assertIn("nuke.execute(_w, 1001, 1010)", code)

    def test_script_save_for_nk(self):
        code = nuke_publish.build_script_save_code("/p/comp_LAST.nk")
        self.assertIn("nuke.scriptSaveAs(", code)
        self.assertIn("/p/comp_LAST.nk", code)


class PublishFromNuke(unittest.TestCase):
    def test_resolves_dest_and_runs_write(self):
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(nuke_publish, "build_nuke_output_path",
                               return_value=(Path("/proj/dest/x_LAST.exr"), 3)), \
             mock.patch("features.publisher.publish_core.resolve_publish_path",
                        return_value=Path("/proj/dest")), \
             mock.patch("features.publisher.publish_layout.archive_flat_last", return_value=2), \
             mock.patch("features.folder_manager.naming_validator.get_base_name",
                        return_value="X_REN_HERO_null"), \
             mock.patch("features.activity.activity_writer.log_publish"), \
             mock.patch("features.publisher.modif_log.append_log"), \
             mock.patch.object(nuke_publish.nuke_client, "run",
                               return_value={"ok": True, "result": "/proj/dest/x_LAST.exr"}) as run:
            out = nuke_publish.publish_from_nuke("PROJ", "X_REN_HERO_null", ".exr")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["path"], str(Path("/proj/dest/x_LAST.exr")))
        self.assertIn("nuke.nodes.Write", run.call_args[0][0])   # a Write was authored

    def test_unresolved_path_does_not_run(self):
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch.object(nuke_publish, "build_nuke_output_path", return_value=(None, None)), \
             mock.patch.object(nuke_publish.nuke_client, "run") as run:
            out = nuke_publish.publish_from_nuke("PROJ", "bad", ".exr")
        self.assertFalse(out["ok"])
        run.assert_not_called()


class NukeMenuHelpers(unittest.TestCase):
    def test_backend_url(self):
        self.assertEqual(flux_nuke_menu.backend_url("/dcc/nuke/publish"),
                         "http://127.0.0.1:8765/dcc/nuke/publish")
        self.assertEqual(flux_nuke_menu.backend_url("dcc/nuke/import"),
                         "http://127.0.0.1:8765/dcc/nuke/import")

    def test_compose_asset_filename(self):
        self.assertEqual(
            flux_nuke_menu.compose_asset_filename("char", "ren", "hero", "null"),
            "CHAR_REN_HERO_NULL",
        )

    def test_compose_defaults_instance(self):
        self.assertEqual(
            flux_nuke_menu.compose_asset_filename("CHAR", "REN", "HERO", ""),
            "CHAR_REN_HERO_NULL",
        )


if __name__ == "__main__":
    unittest.main()
