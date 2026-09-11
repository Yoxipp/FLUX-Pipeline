# test_json_repository.py - the JSON-file MetadataRepository backend (V5 Phase 1a).
#
# Proves the generic surface round-trips and that JsonFileRepository satisfies the
# MetadataRepository contract. Offline: a temp locate maps (collection, doc_id) to
# files under a TemporaryDirectory, so nothing depends on config.json / paths.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.json_repository import JsonFileRepository
from flux_core import MetadataRepository


def _repo_in(root: Path) -> JsonFileRepository:
    def locate(collection: str, doc_id: str | None) -> Path:
        base = root / collection
        base.mkdir(parents=True, exist_ok=True)
        if doc_id is None:
            return root / f"{collection}.jsonl"
        return base / f"{doc_id}.json"
    return JsonFileRepository(locate)


class JsonRepositoryContractTests(unittest.TestCase):
    def test_satisfies_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsInstance(_repo_in(Path(d)), MetadataRepository)

    def test_get_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(_repo_in(Path(d)).get("things", "nope"))

    def test_set_then_get_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _repo_in(Path(d))
            repo.set("things", "a", {"x": 1, "y": "hi"})
            self.assertEqual(repo.get("things", "a"), {"x": 1, "y": "hi"})

    def test_update_merges(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _repo_in(Path(d))
            repo.set("things", "a", {"x": 1, "y": 2})
            repo.update("things", "a", {"y": 9, "z": 3})
            self.assertEqual(repo.get("things", "a"), {"x": 1, "y": 9, "z": 3})

    def test_update_creates_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _repo_in(Path(d))
            repo.update("things", "new", {"a": 1})
            self.assertEqual(repo.get("things", "new"), {"a": 1})

    def test_delete_removes(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _repo_in(Path(d))
            repo.set("things", "a", {"x": 1})
            repo.delete("things", "a")
            self.assertIsNone(repo.get("things", "a"))

    def test_delete_missing_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            _repo_in(Path(d)).delete("things", "ghost")  # must not raise

    def test_list_and_append(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _repo_in(Path(d))
            self.assertEqual(repo.list("events"), [])
            repo.append("events", {"id": "e1"})
            repo.append("events", {"id": "e2"})
            ids = [e["id"] for e in repo.list("events")]
            self.assertEqual(ids, ["e1", "e2"])


if __name__ == "__main__":
    unittest.main()
