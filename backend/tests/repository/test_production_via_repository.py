# test_production_via_repository.py - production.json routes through the repository (Phase 1a).
#
# End-to-end: production_store.load_production / save_production go through the
# process repository (production collection = one production.json per project,
# keyed by project name). Proves the reroute keeps the on-disk format (a dict),
# the missing-file default (default_schema), the write path, and the public
# signatures. The path is resolved by the factory, so we patch it there.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.production import production_store as store


def _patch_path(path: Path):
    # The factory resolves the collection via get_project_production_path.
    return mock.patch(
        "core.repository_factory.get_project_production_path",
        return_value=path,
    )


class ProductionViaRepositoryTests(unittest.TestCase):
    def test_missing_file_returns_default_schema(self):
        with tempfile.TemporaryDirectory() as d:
            prod = Path(d) / "production.json"
            with _patch_path(prod):
                data = store.load_production("SHOW_A")
                self.assertEqual(data["version"], store.SCHEMA_VERSION)
                self.assertEqual(data["sequences"], [])
                self.assertEqual(data["assets"], [])

    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            prod = Path(d) / "production.json"
            with _patch_path(prod):
                data = store.default_schema()
                store.add_sequence(data, "seq010")
                self.assertTrue(store.save_production("SHOW_A", data))
                loaded = store.load_production("SHOW_A")
                self.assertEqual(len(loaded["sequences"]), 1)
                self.assertEqual(loaded["sequences"][0]["name"], "SEQ010")

    def test_on_disk_format_stays_a_dict(self):
        with tempfile.TemporaryDirectory() as d:
            prod = Path(d) / "production.json"
            with _patch_path(prod):
                store.save_production("SHOW_A", store.default_schema())
                raw = json.loads(prod.read_text(encoding="utf-8"))
                self.assertIsInstance(raw, dict)
                self.assertEqual(raw["version"], store.SCHEMA_VERSION)
                self.assertIn("sequences", raw)

    def test_load_heals_missing_top_level_keys(self):
        with tempfile.TemporaryDirectory() as d:
            prod = Path(d) / "production.json"
            prod.write_text(json.dumps({"sequences": [{"id": "s1"}]}), encoding="utf-8")
            with _patch_path(prod):
                data = store.load_production("SHOW_A")
                # Missing lists are healed against the default schema.
                self.assertEqual(data["assets"], [])
                self.assertEqual(data["shots"], [])
                self.assertEqual(data["version"], store.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
