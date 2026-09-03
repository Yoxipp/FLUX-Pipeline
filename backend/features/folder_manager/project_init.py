# project_init.py — create a new Flux project on disk.
#
# Responsibilities:
#   - validate project name
#   - create the standard folder tree under DOSSIER_PROJETS/<name>/
#   - write tokens.json with default CLASS entries

from __future__ import annotations

import shutil
from pathlib import Path

from core.logger import get_logger
from core.paths import ensure_dir, get_projects_dir
from features.folder_manager.naming_validator import format_token, validate_token
from features.folder_manager.tokens import build_default_tokens, save_tokens

log = get_logger(__name__)

# Top-level directories created inside every new project
_PROJECT_DIRS = (
    "assets/chara",
    "assets/props",
    "assets/enviros",
    "assets/fx_rig",
    "shot",
    "lighting",
    "comp",
    "assembly",
    "render",
    # template/ holds the interchangeable Houdini lighting base scenes the
    # seq/shot generators read. Seeded below; the team can swap the files freely.
    "template",
)

# Pipeline seed for the interchangeable Houdini lighting template (versioned default).
_SEED_HOUDINI_DIR = Path(__file__).parent.parent.parent / "resources" / "scenes" / "houdini"


# ── public API ────────────────────────────────────────────────────────────────

def create_project(project_name: str, projects_root: Path | None = None) -> Path:
    """Create a new project under *projects_root* (defaults to DOSSIER_PROJETS).

    *project_name* is formatted automatically (uppercase, underscores, no accents).

    Returns the project root Path.
    Raises FileExistsError if the project already exists.
    Raises ValueError if the (formatted) name is empty or invalid.
    """
    safe_name = format_token(project_name)
    err = validate_token(safe_name)
    if err:
        raise ValueError(f"Invalid project name {project_name!r}: {err}")

    root = projects_root or get_projects_dir()
    project_path = root / safe_name

    if project_path.exists():
        raise FileExistsError(f"Project '{safe_name}' already exists at {project_path}")

    _scaffold_directories(project_path)
    _seed_template_dir(project_path)
    _write_initial_tokens(project_path)

    log.info("Project created: %s", project_path)
    return project_path


def project_exists(project_name: str, projects_root: Path | None = None) -> bool:
    """Return True if a project with *project_name* (raw or formatted) already exists."""
    safe_name = format_token(project_name)
    root = projects_root or get_projects_dir()
    return (root / safe_name).exists()


def list_projects(projects_root: Path | None = None) -> list[str]:
    """Return sorted list of project names found under *projects_root*."""
    root = projects_root or get_projects_dir()
    try:
        return sorted(
            p.name for p in root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
    except OSError:
        return []


# ── internals ─────────────────────────────────────────────────────────────────

def _scaffold_directories(project_path: Path) -> None:
    for rel in _PROJECT_DIRS:
        ensure_dir(project_path / rel)
    log.debug("Scaffolded %d dirs under %s", len(_PROJECT_DIRS), project_path)


def _seed_template_dir(project_path: Path) -> None:
    """Seed <project>/template/ with the default Houdini lighting base scenes.

    Copied from the pipeline seed resource. Idempotent: never overwrites files the
    team may have customised. Non-fatal — a missing seed only logs, project stands.
    The seed is .hipnc (Apprentice-authored); the team can drop .hip versions in,
    which the generators resolve first (see houdini_scene_template.resolve_template).
    """
    tpl_dir = project_path / "template"
    seed = _SEED_HOUDINI_DIR / "flux_template_sequence.hipnc"
    if not seed.is_file():
        log.warning("Houdini template seed missing (%s); template/ left empty.", seed)
        return
    # Seed both the sequence and shot base scenes (same scene at first — the shot
    # scene refines the seq lighting, but starts from the identical rig).
    targets = ("flux_template_sequence.hipnc", "flux_template_shot.hipnc")
    for name in targets:
        dest = tpl_dir / name
        if dest.exists():
            continue  # keep any customised file
        try:
            shutil.copy2(seed, dest)
            log.info("Seeded Houdini template: %s", dest)
        except OSError as exc:
            log.warning("Could not seed Houdini template %s: %s", dest, exc)


def _write_initial_tokens(project_path: Path) -> None:
    tokens = build_default_tokens()
    if not save_tokens(project_path, tokens):
        log.error("Could not write tokens.json for new project at %s", project_path)

