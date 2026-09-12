# remote_repository.py — MetadataRepository over a remote server (V5, SKELETON).
#
# The end state of the storage roadmap: real multi-machine concurrency lives here,
# not in the local SQLite backend (one disk, one writer). A server owns the base
# and every machine talks to it, so several artists writing at once is safe.
#
# Intentionally unimplemented (YAGNI): this is a placeholder so the factory has a
# third branch to grow into and the surface stays honest. No server is deployed
# now, no auth, no Postgres - those decisions come when the maintainer needs them. Each
# method raises NotImplementedError; wiring it up is a later V5 step.

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

_NOT_YET = "RemoteRepository is a V5 skeleton: no server backend is implemented yet."


class RemoteRepository:
    """MetadataRepository talking to a remote server. Not implemented yet."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    # ── document ops ────────────────────────────────────────────────────────────

    def get(self, collection: str, doc_id: str) -> dict | list | None:
        raise NotImplementedError(_NOT_YET)

    def set(self, collection: str, doc_id: str, data: dict | list) -> bool:
        raise NotImplementedError(_NOT_YET)

    def update(self, collection: str, doc_id: str, patch: dict) -> bool:
        raise NotImplementedError(_NOT_YET)

    def delete(self, collection: str, doc_id: str) -> None:
        raise NotImplementedError(_NOT_YET)

    # ── log ops ──────────────────────────────────────────────────────────────────

    def read_log(
        self,
        collection: str,
        doc_id: str,
        *,
        fresh: bool = False,
        sig: tuple[int, int] | None = None,
    ) -> list[dict]:
        raise NotImplementedError(_NOT_YET)

    def append_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        raise NotImplementedError(_NOT_YET)

    def replace_log(self, collection: str, doc_id: str, entries: list[dict]) -> bool:
        raise NotImplementedError(_NOT_YET)

    @contextmanager
    def log_transaction(self, collection: str, doc_id: str) -> Iterator[None]:
        raise NotImplementedError(_NOT_YET)
        yield  # pragma: no cover - unreachable; keeps this a generator/CM
