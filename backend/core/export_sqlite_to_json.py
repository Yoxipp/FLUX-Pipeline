# export_sqlite_to_json.py — one-shot SQLite -> JSON metadata export (V8 U0).
#
# Reverse of migrate_json_to_sqlite. A workspace shared by a team on OneDrive must
# run on the JSON backend (SQLite is refused there by the factory). Writes made
# while SQLite was active live only in the base; this puts them back on disk.
#
# Guarantees:
#   * DRY RUN by default - nothing is written without --apply.
#   * NO SILENT LOSS - an existing file that differs is backed up next to itself
#     (<name>.bak-sqlite-<stamp>) before it is replaced.
#   * LOGS ARE MERGED, not replaced - entries written on disk by teammates while
#     the base was active are kept; base entries are added by "id".
#   * STALE KEYS SKIPPED - a doc whose folder no longer exists (test temp dirs,
#     moved projects), or outside the exported workspace, is never written.
#   * config.json is never exported: it is this machine's bootstrap file. Only its
#     metadata_backend is switched to "json" (with --apply).

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.doc_keys import to_store
from core.json_manager import invalidate_cache, read_jsonl, write_json, write_jsonl
from core.logger import get_logger
from core.migrate_json_to_sqlite import _json_locate_factory

log = get_logger(__name__)

_LOG_COLLECTIONS = ("activity_log", "chat_log", "mentions_log")


@dataclass
class ExportReport:
    """What the export wrote, left alone or skipped. Paths as strings."""

    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    backed_up: list[str] = field(default_factory=list)
    skipped_stale: list[str] = field(default_factory=list)
    skipped_foreign: list[str] = field(default_factory=list)
    merged_entries: int = 0

    def __str__(self) -> str:
        lines = [
            "SQLite -> JSON export report:",
            f"  written   {len(self.written)}",
            f"  unchanged {len(self.unchanged)}",
            f"  backed up {len(self.backed_up)}",
            f"  stale     {len(self.skipped_stale)} (folder missing, not recreated)",
            f"  foreign   {len(self.skipped_foreign)} (outside the workspace)",
            f"  log entries added from the base: {self.merged_entries}",
        ]
        lines += [f"    write  {p}" for p in self.written]
        lines += [f"    backup {p}" for p in self.backed_up]
        return "\n".join(lines)


def _read_disk_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _backup(path: Path, stamp: str) -> Path:
    dst = path.with_name(f"{path.name}.bak-sqlite-{stamp}")
    shutil.copy2(path, dst)
    return dst


def _merge_log(disk: list[dict], base: list[dict]) -> tuple[list[dict], int]:
    """Union by "id" (disk version wins on a shared id). Entries without an id are
    deduplicated on their canonical JSON. Sorted by id when every entry has one:
    ids start with a UTC-like timestamp, so this is chronological."""

    def key(entry: dict) -> str:
        eid = entry.get("id")
        return f"id:{eid}" if eid else "raw:" + json.dumps(entry, sort_keys=True)

    seen = {key(e) for e in disk}
    merged = list(disk)
    added = 0
    for entry in base:
        k = key(entry)
        if k not in seen:
            seen.add(k)
            merged.append(entry)
            added += 1
    if merged and all(e.get("id") for e in merged):
        merged.sort(key=lambda e: str(e["id"]))
    return merged, added


def _in_scope(target: Path, workspace_root: Path | None, report: ExportReport) -> bool:
    if workspace_root is not None:
        try:
            target.resolve().relative_to(Path(workspace_root).resolve())
        except ValueError:
            report.skipped_foreign.append(str(target))
            return False
    if not target.parent.is_dir():
        report.skipped_stale.append(str(target))
        return False
    return True


def export_to_json(
    db_path: Path,
    *,
    projects_dir: Path,
    users_dir: Path,
    prefs_path: Path,
    apply: bool = False,
    include_modif_log: bool = True,
    workspace_root: Path | None = None,
) -> ExportReport:
    """Export every document/log of the base at *db_path* back to JSON files.
    With *workspace_root*, targets outside it (another workspace) are skipped."""
    json_locate = _json_locate_factory(Path(projects_dir), Path(users_dir), Path(prefs_path))

    # Logical keys (V8 U2) back to this machine's store keys; legacy path keys pass through.
    def locate(coll: str, doc_id: str) -> Path:
        store_key = to_store(coll, doc_id, flux_root=Path(projects_dir).parent, projects_dir=Path(projects_dir))
        return json_locate(coll, store_key)

    report = ExportReport()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Read-only: never create, migrate or checkpoint the base we export from.
    conn = sqlite3.connect(f"{Path(db_path).as_uri()}?mode=ro", uri=True)
    try:
        docs = conn.execute("SELECT collection, doc_id, data FROM documents").fetchall()
        logs: dict[tuple[str, str], list[dict]] = {}
        for coll, doc_id, raw in conn.execute(
            "SELECT collection, doc_id, entry FROM logs ORDER BY collection, doc_id, seq"
        ):
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                logs.setdefault((coll, doc_id), []).append(entry)
    finally:
        conn.close()

    for coll, doc_id, raw in docs:
        if coll == "config":
            continue  # bootstrap file of this machine, see module header
        if coll == "modif_log" and not include_modif_log:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        target = locate(coll, doc_id)
        if not _in_scope(target, workspace_root, report):
            continue
        if target.exists():
            if _read_disk_json(target) == data:
                report.unchanged.append(str(target))
                continue
            if apply:
                report.backed_up.append(str(_backup(target, stamp)))
        if apply and not write_json(target, data):
            log.error("Export failed for %s", target)
            continue
        report.written.append(str(target))

    for (coll, doc_id), entries in logs.items():
        if coll not in _LOG_COLLECTIONS:
            continue
        target = locate(coll, doc_id)
        if not _in_scope(target, workspace_root, report):
            continue
        invalidate_cache(target)
        disk = read_jsonl(target) if target.exists() else []
        merged, added = _merge_log(disk, entries)
        if added == 0:
            report.unchanged.append(str(target))
            continue
        report.merged_entries += added
        if apply:
            if target.exists():
                report.backed_up.append(str(_backup(target, stamp)))
            if not write_jsonl(target, merged):
                log.error("Export failed for %s", target)
                continue
        report.written.append(str(target))

    return report


def _switch_config_to_json(config_path: Path) -> None:
    data = _read_disk_json(config_path)
    if not isinstance(data, dict):
        return
    data["metadata_backend"] = "json"
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entry.

    Usage: python -m core.export_sqlite_to_json [db_path] [--apply] [--no-modif-log]
    Dry run without --apply. db_path defaults to the configured base.
    """
    import sys

    from core import paths
    from core.repository_factory import _sqlite_db_path

    args = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in args
    include_modif_log = "--no-modif-log" not in args
    args = [a for a in args if not a.startswith("--")]

    try:
        db_path = Path(args[0]) if args else _sqlite_db_path()
        projects_dir = paths.get_projects_dir()
        users_dir = paths.get_users_dir()
        prefs_path = paths.get_prefs_path()
    except RuntimeError as exc:
        print(f"Cannot export: {exc}")
        return 1
    if not db_path.exists():
        print(f"No base at {db_path}")
        return 1

    print(f"{'EXPORT' if apply else 'DRY RUN'} SQLite -> JSON from {db_path}")
    report = export_to_json(
        db_path,
        projects_dir=projects_dir,
        users_dir=users_dir,
        prefs_path=prefs_path,
        apply=apply,
        include_modif_log=include_modif_log,
        workspace_root=paths.get_flux_root(),
    )
    print(report)
    if apply:
        _switch_config_to_json(paths.get_config_json_path())
        print("config.json: metadata_backend=json. The base is left untouched.")
    else:
        print("Nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
