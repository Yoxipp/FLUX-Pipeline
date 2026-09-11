# repository_factory.py — the single place that decides the active repository.
#
# V5 wiring: features/stores never build a repository themselves; they ask here.
# Today it always returns the JSON-file backend (the current behaviour). When the
# SqliteRepository / RemoteRepository land, only this file changes — the config
# read here picks the backend, and no store/feature is touched.
#
# `locate(collection, doc_id)` maps a logical (collection, doc_id) to a file path.
# Each collection registers a resolver so the on-disk layout stays in one place.
# The "read_state" pilot is addressed by path (doc_id IS the companion path): a
# transitional shape that lets the store route through the repository now, with the
# path-building moved into a resolver later (Phase 1c), without changing this seam.

from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.json_repository import JsonFileRepository

# resolver(doc_id) -> Path. doc_id is None for a collection's append-only log file.
_Resolver = Callable[[str | None], Path]

_resolvers: dict[str, _Resolver] = {}


def register_collection(collection: str, resolver: _Resolver) -> None:
    """Register how a collection maps (doc_id) -> Path. One place per collection."""
    _resolvers[collection] = resolver


def _locate(collection: str, doc_id: str | None) -> Path:
    resolver = _resolvers.get(collection)
    if resolver is None:
        raise KeyError(f"No path resolver registered for collection {collection!r}")
    return resolver(doc_id)


# ── built-in collections ──────────────────────────────────────────────────────
# read_state: the companion set-file is addressed by its own path for now, so the
# store can pass the path it already computes. Path building moves here in Phase 1c.
register_collection("read_state", lambda doc_id: Path(str(doc_id)))


_repository: JsonFileRepository | None = None


def get_repository() -> JsonFileRepository:
    """Return the process-wide active repository (JSON-file backend for now)."""
    global _repository
    if _repository is None:
        _repository = JsonFileRepository(_locate)
    return _repository
