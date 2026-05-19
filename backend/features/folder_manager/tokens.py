# tokens.py — load, save and query tokens.json for a Flux project.
#
# tokens.json is the single source of truth for token→path resolution.
# Every other pipeline module (publisher, importer, DCC bridge) reads from here
# instead of hardcoding folder names.

from __future__ import annotations

import copy
from pathlib import Path

from core.constants import DEFAULT_CLASS_TOKENS, DEFAULT_TYPE_TOKENS, JSON_TOKENS
from core.json_manager import read_json, write_json
from core.logger import get_logger

log = get_logger(__name__)

# All recognised token-type section keys in tokens.json
_TOKEN_SECTIONS = ("CLASS", "TYPE", "NAME", "INSTANCE", "SEQ", "SHOT", "custom")


def _tokens_path(project_path: Path) -> Path:
    return project_path / JSON_TOKENS


# ── bootstrap ─────────────────────────────────────────────────────────────────

def build_default_tokens() -> dict:
    """Return a fresh tokens dict seeded with the default CLASS and TYPE entries."""
    return {
        "CLASS":    dict(DEFAULT_CLASS_TOKENS),
        "TYPE":     dict(DEFAULT_TYPE_TOKENS),
        "NAME":     {},
        "INSTANCE": {},
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
    path = _tokens_path(project_path)
    raw = read_json(path)
    if not isinstance(raw, dict) or "CLASS" not in raw:
        log.warning("tokens.json missing or invalid at %s — using defaults", path)
        return build_default_tokens()

    defaults = build_default_tokens()
    for section in _TOKEN_SECTIONS:
        default_section = defaults.get(section, {})
        if section in ("CLASS", "TYPE") and default_section:
            # Always ensure built-in tokens exist; custom entries take priority on key collision
            raw[section] = {**default_section, **raw.get(section, {})}
        else:
            raw.setdefault(section, default_section)
    return raw


def save_tokens(project_path: Path, tokens: dict) -> bool:
    """Write *tokens* to tokens.json atomically. Returns True on success."""
    ok = write_json(_tokens_path(project_path), tokens)
    if not ok:
        log.error("Failed to write tokens.json at %s", _tokens_path(project_path))
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


def get_all_tokens(project_path: Path) -> dict:
    """Return a deep copy of the full tokens dict (safe for mutation by callers)."""
    return copy.deepcopy(load_tokens(project_path))


# ── mutate ────────────────────────────────────────────────────────────────────

def add_token(
    project_path: Path,
    token_type: str,
    token_value: str,
    rel_path: str,
) -> bool:
    """Add or update a single token entry in tokens.json.

    *token_type* : one of CLASS / TYPE / NAME / SEQ / SHOT / custom
    *rel_path*   : forward-slash relative path from the project root
    Returns True on success.
    """
    if token_type not in _TOKEN_SECTIONS:
        log.warning("Unknown token section %r — falling back to 'custom'", token_type)
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

