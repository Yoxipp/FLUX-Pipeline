# json_repository.py — MetadataRepository backed by JSON files (V5 default).
#
# Delegates every operation to core.json_manager so the cache (stat-sig, short
# TTL) and the OS file locks are preserved EXACTLY: this backend must behave
# identically to the direct json_manager access it replaces, so rerouting a store
# through it changes nothing observable. The only new thing it adds is the seam
# that a SqliteRepository / RemoteRepository can slot into later, same surface.
#
# Where a document lives on disk is NOT this class's business: a `locate` callable
# maps (collection, doc_id) -> Path. That keeps the layout knowledge in one place
# (the factory) and lets a future path-free backend ignore paths entirely.

from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.json_manager import (
    append_jsonl,
    cached_read_json,
    cached_read_jsonl,
    invalidate_cache,
    write_json,
)

# locate(collection, doc_id) -> Path. doc_id is None for the collection's own
# append-only log file (list / append).
Locator = Callable[[str, str | None], Path]


class JsonFileRepository:
    """MetadataRepository over JSON/JSONL files, via json_manager (cache + locks)."""

    def __init__(self, locate: Locator) -> None:
        self._locate = locate

    # ── document ops ─────────────────────────────────────────────────────────

    def get(self, collection: str, doc_id: str) -> dict | list | None:
        path = self._locate(collection, doc_id)
        if not path.exists():
            return None
        data = cached_read_json(path)
        return data if isinstance(data, (dict, list)) else None

    def set(self, collection: str, doc_id: str, data: dict | list) -> bool:
        return write_json(self._locate(collection, doc_id), data)

    def update(self, collection: str, doc_id: str, patch: dict) -> bool:
        current = self.get(collection, doc_id) or {}
        current.update(patch)
        return self.set(collection, doc_id, current)

    def delete(self, collection: str, doc_id: str) -> None:
        path = self._locate(collection, doc_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        invalidate_cache(path)

    # ── collection / log ops ─────────────────────────────────────────────────

    def list(self, collection: str) -> list[dict]:
        return cached_read_jsonl(self._locate(collection, None))

    def append(self, collection: str, entry: dict) -> bool:
        return append_jsonl(self._locate(collection, None), [entry])
