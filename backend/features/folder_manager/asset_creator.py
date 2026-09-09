# asset_creator.py — create asset folder trees and register NAME tokens.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from core.paths import ensure_dir
from features.folder_manager.naming_validator import format_token, validate_token
from features.folder_manager.tokens import add_token, get_path_for_token, load_tokens

log = get_logger(__name__)


# ── public API ────────────────────────────────────────────────────────────────

def create_asset(project_path: Path, class_token: str, asset_name: str) -> Path:
    """Create an asset folder under the project and register its NAME token.

    *class_token* : e.g. "CHAR", "PROPS", "ENV" — must exist in tokens.json CLASS section
    *asset_name*  : raw name, formatted automatically (uppercase, clean chars)

    Returns the asset root Path.
    Raises ValueError for invalid tokens or missing class.
    Raises FileExistsError if the asset already exists.
    """
    class_token = format_token(class_token)
    err = validate_token(class_token)
    if err:
        raise ValueError(f"Invalid class token: {err}")

    safe_name = format_token(asset_name)
    err = validate_token(safe_name)
    if err:
        raise ValueError(f"Invalid asset name {asset_name!r}: {err}")

    tokens = load_tokens(project_path)
    class_rel = get_path_for_token(tokens, "CLASS", class_token)
    if class_rel is None:
        raise ValueError(f"Class token '{class_token}' not defined in tokens.json")

    asset_rel = f"{class_rel}/{safe_name}"
    asset_path = project_path / asset_rel

    if asset_path.exists():
        raise FileExistsError(f"Asset '{safe_name}' already exists at {asset_path}")

    # Minimal structure only: create the asset root and register the NAME token.
    # No work sub-folders (model/rig/groom/…) are pre-invented — the artist (or a
    # publish/materialize) creates the ones actually needed, when needed.
    ensure_dir(asset_path)

    add_token(project_path, "NAME", safe_name, asset_rel)
    log.info("Asset created: %s", asset_path)
    return asset_path


def asset_exists(project_path: Path, class_token: str, asset_name: str) -> bool:
    """Return True if the asset folder already exists."""
    tokens = load_tokens(project_path)
    class_token = format_token(class_token)
    class_rel = get_path_for_token(tokens, "CLASS", class_token)
    if class_rel is None:
        return False
    safe_name = format_token(asset_name)
    return (project_path / class_rel / safe_name).exists()


def list_assets(project_path: Path, class_token: str | None = None) -> list[str]:
    """Return sorted asset names.

    If *class_token* is given, filter to that class only; otherwise list all NAME tokens.
    """
    tokens = load_tokens(project_path)
    if class_token:
        class_token = format_token(class_token)
        class_rel = get_path_for_token(tokens, "CLASS", class_token)
        if not class_rel:
            return []
        class_dir = project_path / class_rel
        try:
            return sorted(p.name for p in class_dir.iterdir() if p.is_dir())
        except OSError:
            return []
    return sorted(tokens.get("NAME", {}).keys())

