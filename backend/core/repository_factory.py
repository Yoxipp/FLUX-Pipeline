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

# modif_log: one JSON-array file per publish folder. doc_id = the folder path; the
# filename join lives here (a first step of moving path building off the feature).
from core.constants import JSON_MODIF_LOG, JSON_TOKENS  # noqa: E402  (kept next to use)

register_collection("modif_log", lambda doc_id: Path(str(doc_id)) / JSON_MODIF_LOG)

# tokens: one tokens.json per project folder. doc_id = the project path.
register_collection("tokens", lambda doc_id: Path(str(doc_id)) / JSON_TOKENS)

# locks: one locks.json per project folder (the folder lock registry). doc_id =
# the project path; the filename join lives here, like tokens/modif_log.
from core.constants import JSON_LOCKS  # noqa: E402  (kept next to use)

register_collection("locks", lambda doc_id: Path(str(doc_id)) / JSON_LOCKS)

# config: the single per-user prefs file (config.json next to the exe). doc_id is a
# fixed label; the path is get_prefs_path() resolved fresh each call, so a runtime
# paths.set_flux_root still wins (matches the old direct read_json(get_prefs_path())).
from core.paths import get_prefs_path  # noqa: E402  (kept next to use)

register_collection("config", lambda doc_id: get_prefs_path())

# production: one production.json per project. doc_id = the project name; the path
# is resolved fresh each call (get_project_production_path), so a runtime
# set_flux_root still wins (matches the old direct read/write_json).
from core.paths import get_project_production_path  # noqa: E402  (kept next to use)

register_collection("production", lambda doc_id: get_project_production_path(str(doc_id)))

# feed logs (append-only JSONL: chat, mentions, activity) + their cold archives.
# Addressed by their own path for now (doc_id IS the log/archive path the store
# already computes, incl. the test-injected one), like the read_state pilot. The
# collections stay distinct so a SQLite backend keys each feed by its own table.
register_collection("chat_log", lambda doc_id: Path(str(doc_id)))
register_collection("mentions_log", lambda doc_id: Path(str(doc_id)))
register_collection("activity_log", lambda doc_id: Path(str(doc_id)))
register_collection("feed_archive", lambda doc_id: Path(str(doc_id)))


_repository: JsonFileRepository | None = None


def get_repository() -> JsonFileRepository:
    """Return the process-wide active repository (JSON-file backend for now)."""
    global _repository
    if _repository is None:
        _repository = JsonFileRepository(_locate)
    return _repository
