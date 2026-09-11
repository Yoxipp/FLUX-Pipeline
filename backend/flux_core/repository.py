# repository.py — the MetadataRepository contract (V5 storage frontier).
#
# ONE job: persist and read back small metadata documents, so the code that owns
# domain meaning (the feature "stores": production_store, chat_manager, ...) stays
# unchanged whether the bytes live in JSON files, a local SQLite base, or a remote
# server later. The stores keep the Flux vocabulary; this layer only stores.
#
# Generic on purpose (document / collection, not projects/assets/tasks): the domain
# already lives in the stores, so duplicating it here would blur the layering. A
# document is one JSON blob addressed by (collection, doc_id); a collection also
# has an append-only log form (list / append) for JSONL feeds.
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

    # ── document ops (one JSON blob per doc_id) ──────────────────────────────
    def get(self, collection: str, doc_id: str) -> dict | None:
        """Return the document, or None when it does not exist."""
        ...

    def set(self, collection: str, doc_id: str, data: dict) -> None:
        """Replace the whole document."""
        ...

    def update(self, collection: str, doc_id: str, patch: dict) -> None:
        """Shallow-merge *patch* into the document (create it if absent)."""
        ...

    def delete(self, collection: str, doc_id: str) -> None:
        """Remove the document. A no-op when it does not exist."""
        ...

    # ── collection / log ops (append-only JSONL form) ────────────────────────
    def list(self, collection: str) -> list[dict]:
        """Return every entry of an append-only collection (empty when absent)."""
        ...

    def append(self, collection: str, entry: dict) -> None:
        """Append one entry to an append-only collection."""
        ...
