# naming_validator.py — token parsing, formatting and filename validation.

from __future__ import annotations

import re
import unicodedata

from core.constants import (
    ACTIVE_VERSION_LABEL,
    DEFAULT_INSTANCE,
    DEFAULT_PADDING,
)

# Characters forbidden in any token
_FORBIDDEN = re.compile(r'[\\/:*?"<>|&\s]')
_VERSION_RE = re.compile(r'^v(\d+)$', re.IGNORECASE)
_SEQ_RE  = re.compile(r'^SEQ(\d+)$', re.IGNORECASE)


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
    variante: str = "",
    version: str = ACTIVE_VERSION_LABEL,
    extension: str = "",
) -> str:
    """Return a properly formatted asset filename.

    Format: CLASS_TYPE_NAME_INSTANCE[_VARIANTE]_ITER — VARIANTE is optional.
    """
    parts = [
        format_token(class_token),
        format_token(type_token),
        format_token(name_token),
        format_token(instance) if instance else DEFAULT_INSTANCE,
    ]
    if variante:
        parts.append(format_token(variante))
    parts.append(version.upper())
    name = "_".join(parts)
    return f"{name}.{extension.lstrip('.')}" if extension else name


# ── filename parsing ──────────────────────────────────────────────────────────

def parse_filename(filename: str) -> dict | None:
    """Parse a Flux filename into its token components.

    Returns a dict with keys matching TOKEN_TYPES / TOKEN_TYPES_SHOT,
    plus 'extension' and 'is_shot'. Returns None if unparseable.
    """
    stem = _strip_ext(filename)
    ext = filename[len(stem) + 1:]

    parts = stem.split("_")
    if not parts or not parts[0]:
        return None

    # Trailing ITER (LAST or vNNN) is optional; strip it so token slots line up
    # whether the filename is a base (CHAR_RIG_HERO_null) or active (…_LAST).
    has_iter = bool(_VERSION_RE.match(parts[-1])) or parts[-1].upper() == ACTIVE_VERSION_LABEL
    iter_val = parts[-1] if has_iter else ""
    core = parts[:-1] if has_iter else list(parts)

    # shot, current form (ADR 0019): SEQ###_SHOT###_TYPE[_VARIANTE] — the department
    # sits where an asset has its TYPE. "CLASS" repeats it so old readers still work.
    if core and _SEQ_RE.match(core[0]):
        dept = core[2] if len(core) > 2 else ""
        variante = core[3] if len(core) > 3 else DEFAULT_INSTANCE
        return {
            "CLASS":     dept,
            "TYPE":      dept,
            "SEQ":       core[0],
            "SHOT":      core[1] if len(core) > 1 else "",
            "INSTANCE":  variante,   # kept for back-compat with path resolution
            "VARIANTE":  variante,
            "ITER":      iter_val,
            "extension": ext,
            "is_shot":   True,
        }

    # shot, legacy form: CLASS_SEQ###_SHOT###[_VARIANTE]
    if len(core) >= 2 and _SEQ_RE.match(core[1]):
        variante = core[3] if len(core) > 3 else DEFAULT_INSTANCE
        return {
            "CLASS":     core[0],
            "TYPE":      core[0],
            "SEQ":       core[1],
            "SHOT":      core[2] if len(core) > 2 else "",
            "INSTANCE":  variante,   # kept for back-compat with path resolution
            "VARIANTE":  variante,
            "ITER":      iter_val,
            "extension": ext,
            "is_shot":   True,
        }

    # asset: CLASS_TYPE_NAME_INSTANCE[_VARIANTE]
    if len(core) < 3:
        return None
    return {
        "CLASS":     core[0],
        "TYPE":      core[1],
        "NAME":      core[2],
        "INSTANCE":  core[3] if len(core) > 3 else DEFAULT_INSTANCE,
        "VARIANTE":  core[4] if len(core) > 4 else "",
        "ITER":      iter_val,
        "extension": ext,
        "is_shot":   False,
    }


def build_shot_filename(
    seq: str,
    shot: str,
    type_token: str,
    variante: str = DEFAULT_INSTANCE,
    version: str = ACTIVE_VERSION_LABEL,
    extension: str = "",
) -> str:
    """Return a shot filename: SEQ###_SHOT###_TYPE[_VARIANTE]_ITER (ADR 0019).

    Unlike build_asset_filename (whose output only feeds path resolution), this keeps
    the case of *variante* and *version* so it can name a real published file.
    """
    parts = [format_token(seq), format_token(shot), format_token(type_token),
             variante or DEFAULT_INSTANCE, version]
    name = "_".join(p for p in parts if p)
    return f"{name}.{extension.lstrip('.')}" if extension else name


# Multi-dot extensions that Path.suffix / rpartition would cut in two.
_COMPOUND_EXTS = (".bgeo.sc", ".bgeo.gz", ".geo.sc", ".geo.gz")


def _strip_ext(filename: str) -> str:
    """*filename* without its extension, compound ones included ('a.bgeo.sc' -> 'a')."""
    low = filename.lower()
    for comp in _COMPOUND_EXTS:
        if low.endswith(comp) and len(filename) > len(comp):
            return filename[: -len(comp)]
    stem, _, _ = filename.rpartition(".")
    return stem or filename


def get_base_name(filename: str) -> str:
    """Return CLASS_TYPE_NAME_instance without version or extension."""
    stem = _strip_ext(filename)
    parts = stem.split("_")
    # strip last part if it looks like a version or LAST
    if parts and (parts[-1].upper() == ACTIVE_VERSION_LABEL or _VERSION_RE.match(parts[-1])):
        parts = parts[:-1]
    return "_".join(parts)


def strip_version(filename: str) -> str:
    """Return filename without the _vXXX or _LAST suffix (keeps extension)."""
    stem = _strip_ext(filename)
    ext = filename[len(stem):]
    return f"{get_base_name(stem)}{ext}"


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

