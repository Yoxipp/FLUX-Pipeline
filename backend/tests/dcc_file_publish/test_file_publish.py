# test_file_publish.py — Designer / Marvelous level-1 file ingest (V6 B3/B4).
#
# The router helper _ingest_file wraps the tested publish_file; here we verify it
# validates inputs and forwards the composed FLUX name.

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from routers import dcc as dcc_router


def _req(**kw):
    return dcc_router.FilePublishRequest(**kw)


class IngestFile(unittest.TestCase):
    def test_ingest_ok(self):
        req = _req(project_name="PROJ", source_path="/tmp/cloth.zprj",
                   target_name="CHAR_CLOTH_HERO_null", description="d", user="adam")
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("features.publisher.publish_core.publish_file",
                        return_value=Path("/proj/dest/CHAR_CLOTH_HERO_null_LAST.zprj")) as pf:
            out = dcc_router._ingest_file(req, "Marvelous")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["path"], str(Path("/proj/dest/CHAR_CLOTH_HERO_null_LAST.zprj")))
        # composed target name is forwarded to the publisher
        self.assertEqual(pf.call_args.args[5], "CHAR_CLOTH_HERO_null")

    def test_missing_source(self):
        req = _req(project_name="PROJ", source_path="/tmp/none.sbsar", target_name="X")
        with mock.patch("pathlib.Path.exists", return_value=False):
            out = dcc_router._ingest_file(req, "Designer")
        self.assertFalse(out["ok"])

    def test_publish_failure(self):
        req = _req(project_name="PROJ", source_path="/tmp/x.sbsar", target_name="bad name")
        with mock.patch("core.paths.get_project_path", return_value=Path("/proj")), \
             mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("features.publisher.publish_core.publish_file", return_value=None):
            out = dcc_router._ingest_file(req, "Designer")
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
