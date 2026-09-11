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

from typing import ContextManager, Protocol, runtime_checkable


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

    # ── log ops (append-only JSONL feeds: chat, mentions, activity) ──────────
    # A log is an append-only sequence of entries addressed by (collection,
    # doc_id). These map cleanly onto any backend: append = INSERT, read = SELECT,
    # replace = the rare bounded rewrite (rotation/prune), a transaction = the
    # atomic scope that guards a read-modify-write. The JSON backend implements
    # them over JSONL files (cache + cross-instance file lock); a future SQLite /
    # remote backend implements the same surface with a table + real transaction.
    def read_log(
        self,
        collection: str,
        doc_id: str,
        *,
        fresh: bool = False,
        sig: tuple[int, int] | None = None,
    ) -> list[dict]:
        """Return every entry of the log (oldest→newest), empty when absent.

        *fresh* bypasses any read cache — needed when the caller must see the
        live set of ids right now (e.g. marking read). *sig* is an optional
        (mtime_ns, size) the caller already stat'd (ETag path); a backend may
        reuse it to skip a stat, and one that has no such cache ignores it.
        """
        ...

    def append_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        """Append *entries* to the log as one atomic write. True on success."""
        ...

    def replace_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        """Rewrite the whole log atomically (rotation / prune). True on success."""
        ...

    def log_transaction(self, collection: str, doc_id: str) -> ContextManager[None]:
        """Atomic scope over one log, for a read-modify-write (rotation).

        Everything done inside the ``with`` block is serialised against other
        writers of the same log — across instances, not just threads — so a
        read_log(fresh) + replace_log pair never loses a racing append. The JSON
        backend holds an OS advisory file lock; SQLite would open a transaction.
        """
        ...
