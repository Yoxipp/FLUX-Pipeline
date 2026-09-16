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

from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from core.json_manager import (
    append_jsonl,
    append_lock,
    cached_read_json,
    cached_read_jsonl,
    file_validator,
    invalidate_cache,
    read_jsonl,
    write_json,
    write_jsonl,
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

    # ── log ops (append-only JSONL feeds) ─────────────────────────────────────
    # Straight delegation to json_manager so the cache, the O_APPEND atomic write
    # and the cross-instance file lock behave EXACTLY as the direct calls these
    # replace: rerouting a feed through here changes nothing observable on disk.

    def read_log(
        self,
        collection: str,
        doc_id: str,
        *,
        fresh: bool = False,
        sig: tuple[int, int] | None = None,
    ) -> list[dict]:
        path = self._locate(collection, doc_id)
        if fresh:
            return read_jsonl(path)              # uncached: live ids for mark-read
        return cached_read_jsonl(path, sig=sig)  # polling path: cached (+ ETag sig)

    def append_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        return append_jsonl(self._locate(collection, doc_id), list(entries))

    def replace_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        return write_jsonl(self._locate(collection, doc_id), list(entries))

    @contextmanager
    def log_transaction(self, collection: str, doc_id: str) -> Iterator[None]:
        # Same OS advisory lock append_jsonl takes, so a read_log(fresh) +
        # replace_log inside the block is atomic w.r.t. concurrent appends.
        with append_lock(self._locate(collection, doc_id)):
            yield

    # ── cache validation ─────────────────────────────────────────────────────

    def version_token(self, collection: str, doc_id: str) -> str:
        # The file's own stat validator (mtime_ns + size): a rewrite of the doc
        # or an append to the log both move it. Identical to the token routers
        # built directly from file stats before this method existed, so JSON-backed
        # ETags are byte-for-byte unchanged. "0" when the file does not exist yet.
        return file_validator(self._locate(collection, doc_id)) or "0"
