"""The bundled manual lands in FLUX_DOC, is refreshed when it changes, and the old
copy in FLUX_UPDATE is removed only when it is the FLUX manual (ADR 0049)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.constants import FLUX_ROOT_DIRS
from features.system import manual as manual_mod
from features.system.manual import (
    FLOWS_FILENAME, FLOWS_SOURCE, MANUAL_FILENAME, MANUAL_SOURCE, ensure_manual, ensure_manual_in_root,
    remove_legacy_manual,
)


class EnsureManual(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "src.html"
        self.source.write_text("<html><title>Manuel de FLUX</title>v1</html>", encoding="utf-8")
        self.doc = self.root / "FLUX_DOC"
        self.update = self.root / "FLUX_UPDATE"

    def tearDown(self):
        self._tmp.cleanup()

    def test_bundled_manual_exists(self):
        self.assertTrue(MANUAL_SOURCE.is_file())
        self.assertIn(b"<title>Manuel de FLUX</title>", MANUAL_SOURCE.read_bytes()[:4096])

    def test_flux_doc_is_a_root_dir(self):
        self.assertIn("FLUX_DOC", FLUX_ROOT_DIRS)
        self.assertIn("FLUX_UPDATE", FLUX_ROOT_DIRS)

    def test_copies_when_missing(self):
        dest = ensure_manual(self.doc, self.source)
        self.assertEqual(dest, self.doc / MANUAL_FILENAME)
        self.assertIn("v1", dest.read_text(encoding="utf-8"))

    def test_refreshes_when_different(self):
        ensure_manual(self.doc, self.source)
        self.source.write_text("<html>v2</html>", encoding="utf-8")
        dest = ensure_manual(self.doc, self.source)
        self.assertEqual(dest.read_text(encoding="utf-8"), "<html>v2</html>")

    def test_missing_source_is_noop(self):
        self.assertIsNone(ensure_manual(self.doc, self.root / "nope.html"))
        self.assertFalse(self.doc.exists())

    def test_legacy_copy_removed_when_identical(self):
        self.update.mkdir()
        (self.update / MANUAL_FILENAME).write_bytes(self.source.read_bytes())
        ensure_manual(self.doc, self.source, legacy_dir=self.update)
        self.assertFalse((self.update / MANUAL_FILENAME).exists())
        self.assertTrue((self.doc / MANUAL_FILENAME).is_file())

    def test_legacy_older_flux_manual_removed(self):
        self.update.mkdir()
        (self.update / MANUAL_FILENAME).write_text(
            "<html><head><title>Manuel de FLUX</title></head>old</html>", encoding="utf-8")
        self.assertTrue(remove_legacy_manual(self.update, self.source))
        self.assertFalse((self.update / MANUAL_FILENAME).exists())

    def test_foreign_file_with_same_name_is_kept(self):
        self.update.mkdir()
        foreign = self.update / MANUAL_FILENAME
        foreign.write_text("<html>notes perso</html>", encoding="utf-8")
        self.assertFalse(remove_legacy_manual(self.update, self.source))
        self.assertTrue(foreign.is_file())

    def test_installers_in_flux_update_untouched(self):
        self.update.mkdir()
        installer = self.update / "FLUX Setup 1.2.3.exe"
        installer.write_bytes(b"MZ")
        (self.update / MANUAL_FILENAME).write_bytes(self.source.read_bytes())
        ensure_manual(self.doc, self.source, legacy_dir=self.update)
        self.assertTrue(installer.is_file())

    def test_ensure_in_root_uses_flux_doc(self):
        dest = ensure_manual_in_root(self.root, self.source)
        self.assertEqual(dest, self.root / "FLUX_DOC" / MANUAL_FILENAME)

    def test_ensure_in_root_also_ships_the_flows_manual(self):
        ensure_manual_in_root(self.root, self.source)
        copy = self.root / "FLUX_DOC" / FLOWS_FILENAME
        self.assertEqual(copy.read_bytes(), FLOWS_SOURCE.read_bytes())

    def test_bundled_flows_manual_exists(self):
        self.assertIn(b"<title>FLUX Flows</title>", FLOWS_SOURCE.read_bytes()[:4096])


class ManualPath(unittest.TestCase):
    def test_falls_back_to_bundled_without_root(self):
        with mock.patch("core.paths.get_flux_root", return_value=None):
            self.assertEqual(manual_mod.manual_path(), MANUAL_SOURCE)

    def test_prefers_local_bundled_over_flux_doc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "FLUX_DOC").mkdir()
            (root / "FLUX_DOC" / MANUAL_FILENAME).write_text("<html>copy</html>", encoding="utf-8")
            with mock.patch("core.paths.get_flux_root", return_value=root):
                self.assertEqual(manual_mod.manual_path(), MANUAL_SOURCE)

    def test_falls_back_to_flux_doc_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "FLUX_DOC").mkdir()
            copy = root / "FLUX_DOC" / MANUAL_FILENAME
            copy.write_text("<html>copy</html>", encoding="utf-8")
            missing = root / "nope.html"
            with mock.patch("core.paths.get_flux_root", return_value=root),                     mock.patch.object(manual_mod, "MANUAL_SOURCE", missing):
                self.assertEqual(manual_mod.manual_path(), copy)

    def test_flows_doc(self):
        self.assertEqual(manual_mod.manual_path("flows"), FLOWS_SOURCE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "FLUX_DOC").mkdir()
            copy = root / "FLUX_DOC" / FLOWS_FILENAME
            copy.write_text("<html>copy</html>", encoding="utf-8")
            with mock.patch("core.paths.get_flux_root", return_value=root), \
                    mock.patch.object(manual_mod, "FLOWS_SOURCE", root / "nope.html"):
                self.assertEqual(manual_mod.manual_path("flows"), copy)


class ManualRoute(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import system
        app = FastAPI()
        app.include_router(system.router, prefix="/system")
        self.client = TestClient(app)

    def test_serves_each_manual(self):
        self.assertIn("<title>Manuel de FLUX</title>", self.client.get("/system/manual").text)
        self.assertIn("<title>FLUX Flows</title>", self.client.get("/system/manual?doc=flows").text)

    def test_unknown_doc_is_refused(self):
        self.assertEqual(self.client.get("/system/manual?doc=../x").status_code, 422)

    def test_info_gives_the_flows_path(self):
        self.assertEqual(self.client.get("/system/manual-info").json()["flows_path"], str(FLOWS_SOURCE))


if __name__ == "__main__":
    unittest.main()
