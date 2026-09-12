# repository_factory.py — the single place that decides the active repository.
#
# V5 wiring: features/stores never build a repository themselves; they ask here.
# get_repository() picks the backend from config ("metadata_backend"): the JSON
# file backend (default), the local SQLite backend, or the remote server backend
# (skeleton). This is the ONE point that flips local -> server; no store/feature
# is touched. Default stays "json" so nothing changes until the maintainer validates the
# migration and flips it explicitly.
#
# `locate(collection, doc_id)` maps a logical (collection, doc_id) to a file path.
# Each collection registers a resolver so the on-disk layout stays in one place.
# Resolvers matter to the JSON backend only; the SQLite / remote backends key by
# the logical (collection, doc_id) and ignore paths entirely.
# The "read_state" pilot is addressed by path (doc_id IS the companion path): a
# transitional shape that lets the store route through the repository now, with the
# path-building moved into a resolver later (Phase 1c), without changing this seam.

from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.json_repository import JsonFileRepository
from flux_core import MetadataRepository, StorageLocator

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

# user_settings: one User.json per artist, at USER/<name>/UserSettings/User.json.
# doc_id = the user name; the path is resolved fresh each call (get_user_dir), so a
# runtime set_flux_root still wins (matches the old direct read/write_json).
from core.constants import JSON_USER_SETTINGS  # noqa: E402  (kept next to use)
from core.paths import get_user_dir  # noqa: E402  (kept next to use)

register_collection(
    "user_settings",
    lambda doc_id: get_user_dir(str(doc_id)) / "UserSettings" / JSON_USER_SETTINGS,
)

# feed logs (append-only JSONL: chat, mentions, activity) + their cold archives.
# Addressed by their own path for now (doc_id IS the log/archive path the store
# already computes, incl. the test-injected one), like the read_state pilot. The
# collections stay distinct so a SQLite backend keys each feed by its own table.
register_collection("chat_log", lambda doc_id: Path(str(doc_id)))
register_collection("mentions_log", lambda doc_id: Path(str(doc_id)))
register_collection("activity_log", lambda doc_id: Path(str(doc_id)))
register_collection("feed_archive", lambda doc_id: Path(str(doc_id)))


_repository: MetadataRepository | None = None


def _build_repository() -> MetadataRepository:
    """Build the backend the config selects. Default "json" keeps today's
    behaviour; "sqlite" / "remote" are explicit opt-ins.

    The selection is read from config.json directly (core.paths), NOT through the
    repository - the config store itself asks get_repository(), so reading it here
    via a repository would recurse.
    """
    from core import paths  # local: avoid a bootstrap import cycle

    backend = paths.get_metadata_backend()

    if backend == "sqlite":
        from core.sqlite_repository import SqliteRepository
        db_path = paths.get_sqlite_path()
        if db_path is None:
            # No explicit path: default to CONFIG/metadata.db (needs FLUX_ROOT).
            db_path = paths.get_config_dir() / "metadata.db"
        return SqliteRepository(db_path)

    if backend == "remote":
        from core.remote_repository import RemoteRepository
        base_url = paths._read_config_json().get("remote_url", "")
        return RemoteRepository(base_url)

    # Default and explicit "json": the file backend with the registered resolvers.
    return JsonFileRepository(_locate)


def get_repository() -> MetadataRepository:
    """Return the process-wide active repository, chosen by config (default JSON)."""
    global _repository
    if _repository is None:
        _repository = _build_repository()
    return _repository


def reset_repository() -> None:
    """Drop the cached repository so the next get_repository() rebuilds from config.

    For tests and a possible in-app backend switch; not used on the hot path.
    """
    global _repository
    _repository = None


# ── storage frontier (big files) ──────────────────────────────────────────────
# Sibling of the metadata repository, second axis: where the heavy bytes live.
# get_storage() picks the StorageLocator from config ("storage_backend"): the local
# backend (default), or the object-store backend (skeleton). One point flips local
# -> web; no feature is touched. Default "local" rooted at the projects dir keeps
# today's paths byte-for-byte.

_storage: StorageLocator | None = None


def _build_storage() -> StorageLocator:
    from core import paths  # local: avoid a bootstrap import cycle

    backend = paths.get_storage_backend()

    if backend == "object":
        from core.object_storage import ObjectStorage
        base_url = paths._read_config_json().get("remote_url", "")
        return ObjectStorage(base_url)

    # Default and explicit "local": rooted at the configured root, or the projects
    # dir (root=None) so the resolved paths match today's layout exactly.
    from core.local_storage import LocalStorage
    return LocalStorage(paths.get_storage_root())


def get_storage() -> StorageLocator:
    """Return the process-wide active storage locator, chosen by config (default local)."""
    global _storage
    if _storage is None:
        _storage = _build_storage()
    return _storage


def reset_storage() -> None:
    """Drop the cached storage locator so the next get_storage() rebuilds from config.

    For tests and a possible in-app backend switch; not used on the hot path.
    """
    global _storage
    _storage = None
