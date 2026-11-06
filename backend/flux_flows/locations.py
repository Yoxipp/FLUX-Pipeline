# locations.py — where each scope keeps its flows (01_ARCHITECTURE §6, ADR 0057, 5).
#
#   shipped  backend/flux_flows/shipped/            read only, inside the exe
#   team     <FLUX_ROOT>/CONFIG/extensions/flows/   + nodes/ pages/ icons/ bridges/ runs/ history.jsonl
#   project  <project>/_flux_setup/flows/            + history.jsonl, ../pages/
#   perso    <FLUX_ROOT>/USER/<NAME>/flows/          drafts in _drafts/ (P4)
#
# core is imported lazily so flux_flows stays importable without a FLUX_ROOT (tests).

from __future__ import annotations

from pathlib import Path
from typing import Optional

SCOPES = ("perso", "project", "team", "shipped")   # resolution order, narrowest first
WRITABLE_SCOPES = ("perso", "project", "team")


def shipped_dir() -> Path:
    # Same pattern as flux_actions/runner.py: backend.spec bundles the folder next to the package.
    return Path(__file__).parent / "shipped"


def extensions_dir() -> Path:
    from core.paths import get_config_dir

    return get_config_dir() / "extensions"


def team_nodes_dir() -> Optional[Path]:
    try:
        return extensions_dir() / "nodes"
    except RuntimeError:  # no FLUX_ROOT yet
        return None


def project_flows_dir(project: str) -> Path:
    from core.constants import SETUP_DIR
    from core.paths import get_project_path

    return get_project_path(project) / SETUP_DIR / "flows"


def user_flows_dir(user: str) -> Path:
    from core.paths import get_user_dir

    return get_user_dir(user) / "flows"


def scope_dir(scope: str, *, project: Optional[str] = None, user: Optional[str] = None) -> Path:
    """Folder holding the flows of *scope*."""
    if scope == "shipped":
        return shipped_dir()
    if scope == "team":
        return extensions_dir() / "flows"
    if scope == "project":
        if not project:
            raise ValueError("portee project sans projet")
        return project_flows_dir(project)
    if scope == "perso":
        if not user:
            raise ValueError("portee perso sans utilisateur")
        return user_flows_dir(user)
    raise ValueError(f"portee inconnue '{scope}'")


def history_file(scope: str, *, project: Optional[str] = None) -> Optional[Path]:
    """history.jsonl of a scope; perso keeps none (its versions are enough)."""
    if scope == "team":
        return extensions_dir() / "history.jsonl"
    if scope == "project":
        return scope_dir("project", project=project) / "history.jsonl"
    return None


def roots_for(*, user: Optional[str], project: Optional[str]) -> dict:
    """{scope: folder or None} for the store: None = scope unavailable (no FLUX_ROOT,
    no project, no user). A project name is a single folder name, never a path."""
    if project and (project in (".", "..") or Path(project).name != project or "\\" in project):
        raise ValueError(f"nom de projet invalide '{project}'")
    roots: dict = {"shipped": shipped_dir(), "team": None, "project": None, "perso": None}
    try:
        roots["team"] = scope_dir("team")
        if user:
            roots["perso"] = scope_dir("perso", user=user)
        if project:
            roots["project"] = scope_dir("project", project=project)
    except RuntimeError:  # no FLUX_ROOT yet (first launch): shipped only
        pass
    return roots


def page_roots(project: Optional[str]) -> dict:
    """{scope: folder or None} of the TOOL pages (04 §2): shipped templates, team, project."""
    flows = roots_for(user=None, project=project)
    roots: dict = {"shipped": shipped_dir() / "pages"}
    for scope in ("team", "project"):   # next to flows/: CONFIG/extensions/pages, _flux_setup/pages
        roots[scope] = Path(flows[scope]).parent / "pages" if flows[scope] is not None else None
    return roots
