# repository.py — the MetadataRepository contract (V5 storage frontier).
#
# ONE job: persist and read back small metadata documents, so the code that owns
# domain meaning (the feature "stores": production_store, chat_manager, ...) stays
# unchanged whether the bytes live in JSON files, a local SQLite base, or a remote
# server later. The stores keep the Flux vocabulary; this layer only stores.
#
# Generic on purpose (document / collection, not projects/assets/tasks): the domain
# already lives in the stores, so duplicating it here would blur the layering. A
# document is one JSON value addressed by (collection, doc_id) - a dict (config,
# read-state) or a list (a per-folder log array); a collection also has an
# append-only log form (list / append) for JSONL feeds.
#
# Pure contract: typing only, zero dependency on any DCC or FastAPI, like the rest
# of flux_core. Treat it like pipe_core.py — never break the surface without
# checking every implementation and caller.

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MetadataRepository(Protocol):
    """Persistence frontier for small metadata. Implementations must be swappable
    (JSON files today, SQLite / remote later) behind this exact surface."""

    # ── document ops (one JSON value per doc_id: a dict or a list) ───────────
    def get(self, collection: str, doc_id: str) -> dict | list | None:
        """Return the document (dict or list), or None when it does not exist."""
        ...

    def set(self, collection: str, doc_id: str, data: dict | list) -> bool:
        """Replace the whole document. Return True on a successful write.

        A bool (not None): several stores surface write failures to the user
        (e.g. project creation), so the persistence layer must report success.
        """
        ...

    def update(self, collection: str, doc_id: str, patch: dict) -> bool:
        """Shallow-merge *patch* into a dict document (create it if absent)."""
        ...

    def delete(self, collection: str, doc_id: str) -> None:
        """Remove the document. A no-op when it does not exist."""
        ...

    # ── collection / log ops (append-only JSONL form) ────────────────────────
    def list(self, collection: str) -> list[dict]:
        """Return every entry of an append-only collection (empty when absent)."""
        ...

    def append(self, collection: str, entry: dict) -> bool:
        """Append one entry to an append-only collection. True on success."""
        ...
