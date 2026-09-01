# naming_validator.py — token parsing, formatting and filename validation.

from __future__ import annotations

import re
import unicodedata

from core.constants import (
    ACTIVE_VERSION_LABEL,
    DEFAULT_INSTANCE,
    DEFAULT_PADDING,
    TOKEN_TYPES,
    TOKEN_TYPES_SHOT,
)

# Characters forbidden in any token
_FORBIDDEN = re.compile(r'[\\/:*?"<>|&\s]')
_VERSION_RE = re.compile(r'^v(\d+)$', re.IGNORECASE)
_SEQ_RE  = re.compile(r'^SEQ(\d+)$', re.IGNORECASE)
_SHOT_RE = re.compile(r'^SHOT(\d+)$', re.IGNORECASE)


# ── token formatting ──────────────────────────────────────────────────────────

def format_token(raw: str) -> str:
    """Normalise *raw* into a valid uppercase token.

    Steps:
      1. Strip accents (NFD decompose → drop combining chars)
      2. Replace spaces / hyphens with underscores
      3. Strip remaining forbidden characters
      4. Uppercase
    """
    # decompose unicode and drop combining (accent) characters
    nfd = unicodedata.normalize("NFD", raw)
    ascii_only = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # spaces and hyphens → underscore
    cleaned = re.sub(r"[\s\-]+", "_", ascii_only)
    # strip anything else that is forbidden
    cleaned = _FORBIDDEN.sub("", cleaned)
    return cleaned.upper().strip("_")


def format_seq(number: int, padding: int = DEFAULT_PADDING) -> str:
    return f"SEQ{str(number).zfill(padding)}"


def format_shot(number: int, padding: int = DEFAULT_PADDING) -> str:
    return f"SHOT{str(number).zfill(padding)}"


def format_version(number: int, padding: int = 3) -> str:
    return f"v{str(number).zfill(padding)}"


# ── filename building ─────────────────────────────────────────────────────────

def build_asset_filename(
    class_token: str,
    type_token: str,
    name_token: str,
    instance: str = DEFAULT_INSTANCE,
    version: str = ACTIVE_VERSION_LABEL,
    extension: str = "",
) -> str:
    """Return a properly formatted asset filename."""
    parts = [
        format_token(class_token),
        format_token(type_token),
        format_token(name_token),
        format_token(instance) if instance else DEFAULT_INSTANCE,
        version.upper(),
    ]
    name = "_".join(parts)
    return f"{name}.{extension.lstrip('.')}" if extension else name


def build_shot_filename(
    class_token: str,
    seq_token: str,
    shot_token: str,
    instance: str = DEFAULT_INSTANCE,
    version: str = ACTIVE_VERSION_LABEL,
    extension: str = "",
) -> str:
    parts = [
        format_token(class_token),
        seq_token.upper(),
        shot_token.upper(),
        format_token(instance) if instance else DEFAULT_INSTANCE,
        version.upper(),
    ]
    name = "_".join(parts)
    return f"{name}.{extension.lstrip('.')}" if extension else name


# ── filename parsing ──────────────────────────────────────────────────────────

def parse_filename(filename: str) -> dict | None:
    """Parse a Flux filename into its token components.

    Returns a dict with keys matching TOKEN_TYPES / TOKEN_TYPES_SHOT,
    plus 'extension' and 'is_shot'. Returns None if unparseable.
    """
    stem, _, ext = filename.rpartition(".")
    if not stem:
        stem = filename
        ext = ""

    parts = stem.split("_")

    # shot filenames: CLASS_SEQ###_SHOT###_instance_ITER
    if len(parts) >= 4 and _SEQ_RE.match(parts[1]):
        return {
            "CLASS":     parts[0],
            "SEQ":       parts[1],
            "SHOT":      parts[2] if len(parts) > 2 else "",
            "INSTANCE":  parts[3] if len(parts) > 3 else DEFAULT_INSTANCE,
            "ITER":      parts[4] if len(parts) > 4 else "",
            "extension": ext,
            "is_shot":   True,
        }

    # asset filenames: CLASS_TYPE_NAME_instance_ITER
    if len(parts) < 4:
        return None
    return {
        "CLASS":     parts[0],
        "TYPE":      parts[1],
        "NAME":      parts[2],
        "INSTANCE":  parts[3] if len(parts) > 3 else DEFAULT_INSTANCE,
        "ITER":      parts[4] if len(parts) > 4 else "",
        "extension": ext,
        "is_shot":   False,
    }


def get_base_name(filename: str) -> str:
    """Return CLASS_TYPE_NAME_instance without version or extension."""
    stem, _, _ = filename.rpartition(".")
    if not stem:
        stem = filename
    parts = stem.split("_")
    # strip last part if it looks like a version or LAST
    if parts and (parts[-1].upper() == ACTIVE_VERSION_LABEL or _VERSION_RE.match(parts[-1])):
        parts = parts[:-1]
    return "_".join(parts)


def strip_version(filename: str) -> str:
    """Return filename without the _vXXX or _LAST suffix (keeps extension)."""
    stem, sep, ext = filename.rpartition(".")
    if not stem:
        stem = filename
        sep = ext = ""
    base = get_base_name(stem)
    return f"{base}{sep}{ext}" if sep else base


# ── validation ────────────────────────────────────────────────────────────────

def validate_token(value: str) -> str | None:
    """Return an error message if *value* is not a valid token, else None."""
    if not value:
        return "Token cannot be empty."
    if _FORBIDDEN.search(value):
        return f"Token contains forbidden characters: {value!r}"
    if value != value.upper():
        return f"Token must be uppercase: {value!r}"
    return None


def validate_filename(filename: str) -> str | None:
    """Return an error message if *filename* cannot be parsed, else None."""
    parsed = parse_filename(filename)
    if parsed is None:
        return (
            f"Cannot parse '{filename}'. "
            "Expected: CLASS_TYPE_NAME_instance_ITER[.ext] "
            "or CLASS_SEQ###_SHOT###_instance_ITER[.ext]"
        )
    return None

