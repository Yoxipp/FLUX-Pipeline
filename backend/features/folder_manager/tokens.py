# tokens.py — load, save and query tokens.json for a Flux project.
#
# tokens.json is the single source of truth for token→path resolution.
# Every other pipeline module (publisher, importer, DCC bridge) reads from here
# instead of hardcoding folder names.

from __future__ import annotations

from pathlib import Path

from core.constants import DEFAULT_CLASS_TOKENS, DEFAULT_SHOT_TYPE_TOKENS, DEFAULT_TYPE_TOKENS
from core.logger import get_logger
from core.repository_factory import get_repository

log = get_logger(__name__)

# All recognised token-type section keys in tokens.json
# TYPE_SHOT: department of a shot publish (ADR 0019). Absent from old projects, which
# fall back to their CLASS tokens for the legacy CLASS_SEQ_SHOT names.
_TOKEN_SECTIONS = ("CLASS", "TYPE", "TYPE_SHOT", "NAME", "INSTANCE", "SEQ", "SHOT", "custom")

# Metadata frontier (V5): tokens.json goes through the repository. The document is
# a dict, addressed by its project folder (the resolver appends the file name).
_COLLECTION = "tokens"


# ── bootstrap ─────────────────────────────────────────────────────────────────

def build_default_tokens() -> dict:
    """Return a fresh tokens dict seeded with the default CLASS, TYPE and INSTANCE entries."""
    return {
        "CLASS":    dict(DEFAULT_CLASS_TOKENS),
        "TYPE":      dict(DEFAULT_TYPE_TOKENS),
        "TYPE_SHOT": dict(DEFAULT_SHOT_TYPE_TOKENS),
        "NAME":     {},
        "INSTANCE": {"null": ""},
        "SEQ":      {},
        "SHOT":     {},
        "custom":   {},
    }


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_tokens(project_path: Path) -> dict:
    """Load tokens.json for *project_path*.

    Falls back to defaults when the file is absent or malformed.
    Ensures all expected sections exist for forward-compatibility.
    """
    raw = get_repository().get(_COLLECTION, str(project_path))
    if not isinstance(raw, dict) or "CLASS" not in raw:
        log.warning("tokens.json missing or invalid for %s, using defaults", project_path)
        return build_default_tokens()

    defaults = build_default_tokens()
    for section in _TOKEN_SECTIONS:
        default_section = defaults.get(section, {})
        if section in ("CLASS", "TYPE", "TYPE_SHOT", "INSTANCE") and default_section:
            # Always ensure built-in tokens exist; custom entries take priority on key collision
            raw[section] = {**default_section, **raw.get(section, {})}
        else:
            raw.setdefault(section, default_section)
    return raw


def save_tokens(project_path: Path, tokens: dict) -> bool:
    """Write *tokens* to tokens.json atomically. Returns True on success."""
    ok = get_repository().set(_COLLECTION, str(project_path), tokens)
    if not ok:
        log.error("Failed to write tokens.json for %s", project_path)
    return ok


# ── query ─────────────────────────────────────────────────────────────────────

def get_path_for_token(tokens: dict, token_type: str, token_value: str) -> str | None:
    """Return the relative path string for *token_value* in *token_type*, or None."""
    return tokens.get(token_type, {}).get(token_value)


def resolve_path(project_path: Path, tokens: dict, token_type: str, token_value: str) -> Path | None:
    """Return the absolute path for a token, joining *project_path* + relative path.

    Returns None if the token is not defined.
    """
    rel = get_path_for_token(tokens, token_type, token_value)
    if rel is None:
        return None
    return project_path / rel


# ── mutate ────────────────────────────────────────────────────────────────────

def add_token(
    project_path: Path,
    token_type: str,
    token_value: str,
    rel_path: str,
) -> bool:
    """Add or update a single token entry in tokens.json.

    *token_type* : one of CLASS / TYPE / NAME / INSTANCE / SEQ / SHOT / custom
    *rel_path*   : forward-slash relative path from the project root
    Returns True on success.
    """
    if token_type not in _TOKEN_SECTIONS:
        log.warning("Unknown token section %r, falling back to 'custom'", token_type)
        token_type = "custom"

    tokens = load_tokens(project_path)
    tokens.setdefault(token_type, {})[token_value] = rel_path
    log.debug("add_token %s/%s → %r", token_type, token_value, rel_path)
    return save_tokens(project_path, tokens)


def remove_token(project_path: Path, token_type: str, token_value: str) -> bool:
    """Remove a token entry. Returns True if it existed and was removed."""
    tokens = load_tokens(project_path)
    section = tokens.get(token_type, {})
    if token_value not in section:
        return False
    del section[token_value]
    return save_tokens(project_path, tokens)

