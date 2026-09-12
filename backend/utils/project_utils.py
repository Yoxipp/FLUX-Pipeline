# project_utils.py — project management wrappers over config.py and paths.py.

from __future__ import annotations

from pathlib import Path

from core import config, paths
from core.logger import get_logger

log = get_logger(__name__)


def list_projects() -> list[str]:
    """Return sorted list of project names found in FLUX_ROOT/DOSSIER_PROJETS/."""
    try:
        projects_dir = paths.get_projects_dir()
        return sorted(d.name for d in projects_dir.iterdir() if d.is_dir())
    except (RuntimeError, OSError):
        return []


def get_current_project() -> str | None:
    """Return the active project, validated against what exists on disk.

    The stored ``last_project`` can point at a project that no longer exists (renamed,
    deleted, or a stale value carried over from an older config / migration). Returning
    a dead name leaves the app stuck on an empty screen, so when the stored project is
    missing we fall back to the first available project. Returns None only when the
    workspace genuinely holds no project. Pure getter: it does not rewrite config here;
    the corrected name is persisted when the user (or the frontend) selects a project.
    """
    stored = config.get_last_project()
    if stored and project_exists(stored):
        return stored
    available = list_projects()
    return available[0] if available else None


def set_current_project(name: str) -> None:
    """Persist *name* as the active project in config.json."""
    config.set_last_project(name)
    log.debug("Current project set to '%s'", name)


def project_exists(name: str) -> bool:
    """Return True if FLUX_ROOT/DOSSIER_PROJETS/<name>/ exists."""
    try:
        return paths.get_project_path(name).exists()
    except (RuntimeError, OSError):
        return False


def get_project_path(name: str) -> Path:
    """Return the absolute path for *name* inside DOSSIER_PROJETS."""
    return paths.get_project_path(name)

