# migrate_json_to_sqlite.py — one-shot JSON -> SQLite metadata migration (V5).
#
# Reads every existing JSON/JSONL document through the JSON backend and writes it
# into a SqliteRepository, so the same (collection, doc_id) keys the stores use at
# runtime resolve to the same values after the factory flips to SQLite.
#
# Two guarantees the caller can rely on:
#   * IDEMPOTENT   - re-running yields the same base, never a duplicate. Documents
#                    use INSERT OR REPLACE; logs are REPLACED (delete + re-insert)
#                    so a second run mirrors the source instead of re-appending.
#   * NON-DESTRUCTIVE - no JSON file is ever touched. They stay as the safety net
#                    until the maintainer validates the SQLite base and flips the default.
#
# The hard part is enumerating what to migrate: the resolvers are keyed by path or
# name, so we SCAN the disk per collection to rebuild the (collection, doc_id)
# pairs, reproducing EXACTLY the doc_id each store passes at runtime:
#   tokens/locks -> project path   production/user_settings -> name
#   config -> "prefs"              feeds/read_state/feed_archive -> the path
#   modif_log (opt-in) -> the publish folder path (deep recursive scan)

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.constants import (
    ARCHIVE_DIRNAME,
    JSON_ACTIVITY,
    JSON_ACTIVITY_READ,
    JSON_CHAT,
    JSON_LOCKS,
    JSON_MENTIONS,
    JSON_MENTIONS_READ,
    JSON_MODIF_LOG,
    JSON_PRODUCTION,
    JSON_TOKENS,
    JSON_USER_SETTINGS,
)
from core.json_repository import JsonFileRepository
from core.logger import get_logger
from core.doc_keys import to_logical
from core.sqlite_repository import SqliteRepository

log = get_logger(__name__)

# Feed logs (append-only JSONL) -> their repository collection. doc_id = the file
# path the store computes at runtime (CONFIG/<file>), so we key by that path.
_FEED_FILES = {
    JSON_ACTIVITY: "activity_log",
    JSON_CHAT: "chat_log",
    JSON_MENTIONS: "mentions_log",
}

# read-status companions (small JSON documents), keyed by their own path.
_READ_STATE_FILES = (JSON_ACTIVITY_READ, JSON_MENTIONS_READ)


@dataclass
class MigrationReport:
    """What the migration moved, per collection. Counts documents and logs."""

    documents: dict[str, int] = field(default_factory=dict)
    logs: dict[str, int] = field(default_factory=dict)

    def _bump(self, bucket: dict[str, int], collection: str) -> None:
        bucket[collection] = bucket.get(collection, 0) + 1

    def total_documents(self) -> int:
        return sum(self.documents.values())

    def total_logs(self) -> int:
        return sum(self.logs.values())

    def __str__(self) -> str:
        lines = ["JSON -> SQLite migration report:"]
        for coll, n in sorted(self.documents.items()):
            lines.append(f"  doc  {coll:<16} {n}")
        for coll, n in sorted(self.logs.items()):
            lines.append(f"  log  {coll:<16} {n}")
        lines.append(
            f"  total: {self.total_documents()} documents, {self.total_logs()} logs"
        )
        return "\n".join(lines)


def _json_locate_factory(projects_dir: Path, users_dir: Path, prefs_path: Path):
    """Return a locate(collection, doc_id) -> Path that MIRRORS the runtime
    resolvers in repository_factory, parametrised by the roots to scan. Reading
    through it means the migration reads exactly what the stores read."""

    def locate(collection: str, doc_id: str | None) -> Path:
        if collection == "tokens":
            return Path(str(doc_id)) / JSON_TOKENS
        if collection == "locks":
            return Path(str(doc_id)) / JSON_LOCKS
        if collection == "modif_log":
            return Path(str(doc_id)) / JSON_MODIF_LOG
        if collection == "production":
            return projects_dir / str(doc_id) / JSON_PRODUCTION
        if collection == "user_settings":
            return users_dir / str(doc_id) / "UserSettings" / JSON_USER_SETTINGS
        if collection == "config":
            return prefs_path
        # feeds, read_state, feed_archive: doc_id IS the path the store computes.
        return Path(str(doc_id))

    return locate


def _subdirs(parent: Path) -> list[Path]:
    """Immediate subdirectories of *parent*, or [] (missing dir / NAS hiccup)."""
    try:
        return [p for p in parent.iterdir() if p.is_dir()]
    except OSError:
        return []


def _scan(
    projects_dir: Path,
    users_dir: Path,
    config_dir: Path,
    prefs_path: Path,
    include_modif_log: bool,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return (document_items, log_items) as lists of (collection, doc_id)."""
    docs: list[tuple[str, str]] = []
    logs: list[tuple[str, str]] = []

    # per-project documents: tokens/locks keyed by path, production keyed by name.
    for project in _subdirs(projects_dir):
        if (project / JSON_TOKENS).exists():
            docs.append(("tokens", str(project)))
        if (project / JSON_LOCKS).exists():
            docs.append(("locks", str(project)))
        if (project / JSON_PRODUCTION).exists():
            docs.append(("production", project.name))
        if (project / JSON_CHAT).exists():   # per-project team chat (feed log)
            logs.append(("chat_log", str(project / JSON_CHAT)))

    # per-user settings, keyed by user name.
    for user in _subdirs(users_dir):
        if (user / "UserSettings" / JSON_USER_SETTINGS).exists():
            docs.append(("user_settings", user.name))

    # the single per-user prefs document.
    if prefs_path.exists():
        docs.append(("config", "prefs"))

    # read-status companions, keyed by their own path.
    for fname in _READ_STATE_FILES:
        p = config_dir / fname
        if p.exists():
            docs.append(("read_state", str(p)))

    # cold archives (JSON arrays), keyed by their own path.
    archive_dir = config_dir / ARCHIVE_DIRNAME
    if archive_dir.exists():
        for f in sorted(archive_dir.glob("*.json")):
            docs.append(("feed_archive", str(f)))

    # hot feeds (append-only JSONL), keyed by their own path.
    for fname, collection in _FEED_FILES.items():
        p = config_dir / fname
        if p.exists():
            logs.append((collection, str(p)))

    # opt-in: modif_logs are buried one-per-publish-folder (deep recursive scan).
    if include_modif_log:
        try:
            for f in projects_dir.rglob(JSON_MODIF_LOG):
                docs.append(("modif_log", str(f.parent)))
        except OSError:
            log.warning("modif_log scan hit an OS error; skipping the rest")

    return docs, logs


def migrate_to_sqlite(
    db_path: Path,
    *,
    projects_dir: Path,
    users_dir: Path,
    config_dir: Path,
    prefs_path: Path,
    include_modif_log: bool = False,
    dst: SqliteRepository | None = None,
) -> MigrationReport:
    """Migrate every JSON document/log under the given roots into the SQLite base
    at *db_path*. Idempotent and non-destructive. Returns a MigrationReport."""
    projects_dir = Path(projects_dir)
    users_dir = Path(users_dir)
    config_dir = Path(config_dir)
    prefs_path = Path(prefs_path)

    src = JsonFileRepository(_json_locate_factory(projects_dir, users_dir, prefs_path))
    dst = dst or SqliteRepository(Path(db_path))
    report = MigrationReport()

    doc_items, log_items = _scan(
        projects_dir, users_dir, config_dir, prefs_path, include_modif_log
    )

    # The base stores logical keys (ADR 0004, V8 U2), like the runtime wrapper does.
    def key(collection: str, doc_id: str) -> str:
        return to_logical(collection, doc_id, flux_root=config_dir.parent, projects_dir=projects_dir)

    for collection, doc_id in doc_items:
        data = src.get(collection, doc_id)
        if data is None:
            continue  # unreadable / vanished between scan and read: skip, never crash
        if dst.set(collection, key(collection, doc_id), data):  # INSERT OR REPLACE -> idempotent
            report._bump(report.documents, collection)
        else:
            log.error("Failed to migrate document %s/%s", collection, doc_id)

    for collection, doc_id in log_items:
        entries = src.read_log(collection, doc_id)
        # REPLACE, not append: a second run mirrors the source with no duplicates.
        if dst.replace_log(collection, key(collection, doc_id), entries):
            report._bump(report.logs, collection)
        else:
            log.error("Failed to migrate log %s/%s", collection, doc_id)

    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry: migrate the live workspace into a SQLite base.

    Usage: python -m core.migrate_json_to_sqlite [db_path] [--with-modif-log]
    db_path defaults to CONFIG/metadata.db. Roots come from the resolved FLUX_ROOT.
    """
    import sys

    from core import paths

    args = list(sys.argv[1:] if argv is None else argv)
    include_modif_log = "--with-modif-log" in args
    args = [a for a in args if not a.startswith("--")]

    try:
        projects_dir = paths.get_projects_dir()
        users_dir = paths.get_users_dir()
        config_dir = paths.get_config_dir()
        prefs_path = paths.get_prefs_path()
    except RuntimeError as exc:
        print(f"Cannot migrate: {exc}")
        return 1

    db_path = Path(args[0]) if args else config_dir / "metadata.db"

    print(f"Migrating JSON -> SQLite into {db_path}")
    print(f"  projects: {projects_dir}\n  users: {users_dir}\n  config: {config_dir}")
    if include_modif_log:
        print("  (including modif_log deep scan)")

    report = migrate_to_sqlite(
        db_path,
        projects_dir=projects_dir,
        users_dir=users_dir,
        config_dir=config_dir,
        prefs_path=prefs_path,
        include_modif_log=include_modif_log,
    )
    print(report)
    print("Done. JSON files left untouched (safety net).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
