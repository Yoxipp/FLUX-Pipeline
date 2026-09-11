# test_json_repository.py - the JSON-file MetadataRepository backend (V5 Phase 1a).
#
# Runs the shared backend-agnostic conformance suite (the same one SqliteRepository
# runs) against JsonFileRepository, so both backends are proven observably
# identical through the surface. A temp locate maps (collection, doc_id) to files
# under a TemporaryDirectory, so nothing depends on config.json / paths.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.json_repository import JsonFileRepository
from tests.repository._contract import RepositoryContractMixin


class JsonRepositoryContractTests(RepositoryContractMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._root = Path(self._dir.name)

    def make_repo(self) -> JsonFileRepository:
        root = self._root

        def locate(collection: str, doc_id: str | None) -> Path:
            base = root / collection
            base.mkdir(parents=True, exist_ok=True)
            if doc_id is None:
                return root / f"{collection}.jsonl"
            return base / f"{doc_id}.json"

        return JsonFileRepository(locate)


if __name__ == "__main__":
    unittest.main()
