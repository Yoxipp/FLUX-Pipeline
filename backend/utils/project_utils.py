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
    """Return the last used project name from config, or None."""
    return config.get_last_project()


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

