# file_browser.py — read-only file browsing within a project path.

from __future__ import annotations

from pathlib import Path

from core.constants import JSON_MODIF_LOG
from core.paths import is_subpath
from features.publisher.modif_log import get_logs_for_file
from features.folder_manager.naming_validator import get_base_name
from core.logger import get_logger

log = get_logger(__name__)

_EXCLUDED_NAMES = {JSON_MODIF_LOG}


def list_files(
    project_path: Path,
    class_filter: str | None = None,
    type_filter: str | None = None,
    name_filter: str | None = None,
    last_only: bool = False,
) -> list[Path]:
    """Return all publishable files under *project_path*, sorted alphabetically.

    Excludes modif_logs.json and any .json file.
    Each returned path is validated to be inside *project_path*.
    """
    project_path = project_path.resolve()
    results: list[Path] = []

    try:
        for p in project_path.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() == ".json":
                continue
            if p.name in _EXCLUDED_NAMES:
                continue
            if not is_subpath(p.resolve(), project_path):
                continue

            name = p.name
            if last_only and "_LAST." not in name:
                continue

            if class_filter or type_filter or name_filter:
                from features.folder_manager.naming_validator import parse_filename
                parsed = parse_filename(name)
                if parsed is None:
                    continue
                if class_filter and parsed.get("CLASS", "").upper() != class_filter.upper():
                    continue
                if type_filter and parsed.get("TYPE", "").upper() != type_filter.upper():
                    continue
                if name_filter and parsed.get("NAME", "").upper() != name_filter.upper():
                    continue

            results.append(p)
    except OSError as e:
        log.warning("list_files error at %s: %s", project_path, e)

    return sorted(results, key=lambda p: p.name.lower())


def list_folders(project_path: Path, parent_rel: str = "") -> list[str]:
    """Return immediate subdirectory names under project_path/parent_rel.

    Excludes hidden directories (starting with '.').
    """
    project_path = project_path.resolve()
    target = (project_path / parent_rel).resolve() if parent_rel else project_path

    if not is_subpath(target, project_path) and target != project_path:
        log.warning("list_folders: %s is outside project root", target)
        return []

    try:
        return sorted(
            d.name for d in target.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    except OSError as e:
        log.warning("list_folders error at %s: %s", target, e)
        return []


def list_files_immediate(folder_path: Path) -> list[Path]:
    """Return immediate (non-recursive) files in *folder_path*, excluding .json files."""
    folder_path = folder_path.resolve()
    try:
        return sorted(
            [p for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() != ".json"],
            key=lambda p: p.name.lower(),
        )
    except OSError as e:
        log.warning("list_files_immediate error at %s: %s", folder_path, e)
        return []


def get_file_info(file_path: Path, project_path: Path) -> dict:
    """Return the most recent modif_log entry for *file_path*, or empty dict."""
    empty = {"name": file_path.name, "base_name": "", "version": "", "date": "", "time": "", "modification": "", "user": ""}
    file_path = file_path.resolve()
    project_path = project_path.resolve()

    if not is_subpath(file_path, project_path):
        log.warning("get_file_info: %s is outside project root", file_path)
        return empty

    folder = file_path.parent
    base = get_base_name(file_path.name)
    entries = get_logs_for_file(folder, base)

    # Per-format layout: the file sits in <instance>/<ext>/, but the modif log is
    # written once at the instance leaf (<instance>/modif_logs.json). Fall back one
    # level up so the info panel still finds the history for a format-nested file.
    if not entries:
        entries = get_logs_for_file(folder.parent, base)

    if not entries:
        empty["base_name"] = base
        return empty

    entry = entries[0]
    return {
        "name":         file_path.name,
        "base_name":    base,
        "version":      entry.get("version", ""),
        "date":         entry.get("date", ""),
        "time":         entry.get("time", ""),
        "modification": entry.get("modification", ""),
        "user":         entry.get("user", ""),
    }

