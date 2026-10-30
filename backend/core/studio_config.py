# studio_config.py - the studio's own settings: FLUX_ROOT/CONFIG/studio.json (ADR 0063).
#
# A workspace (FLUX_ROOT) is one studio. studio.json holds what belongs to that studio and
# not to FLUX, so nothing of a given school or studio is written in the code:
#   * environment         link to the studio's environment file (farm engine, blade paths,
#                         tags...), FLUX_ROOT-relative or absolute (UNC). Changing the link
#                         switches the whole environment at once. Empty = no environment.
#   * legacy_supervisors  supervisors of the projects created before roles existed (no
#                         roles.json, ADR 0064).
# FLUX ships it empty. Keys are stable (ADR 0004): only add new ones.

from __future__ import annotations

import copy
from pathlib import Path

from core import paths
from core.constants import JSON_STUDIO
from core.json_manager import read_json, write_json

SCHEMA_VERSION = 1

DEFAULTS: dict = {
    "schema_version": SCHEMA_VERSION,
    "environment": "",
    "legacy_supervisors": [],
}


def studio_path() -> Path:
    """FLUX_ROOT/CONFIG/studio.json. Raises RuntimeError without a FLUX_ROOT."""
    return paths.get_config_dir() / JSON_STUDIO


def _check_names(value) -> list[str]:
    from utils.user_utils import is_valid_user_name

    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("legacy_supervisors doit etre une liste de noms d'artistes")
    names = []
    for raw in value:
        name = raw.strip().upper()
        if not is_valid_user_name(name):
            raise ValueError(f"Nom d'artiste invalide : {raw!r}")
        if name not in names:
            names.append(name)
    return names


def _check_value(key: str, value):
    if key == "environment":
        if not isinstance(value, str):
            raise ValueError("environment doit etre un chemin (texte)")
        return value.strip()
    if key == "legacy_supervisors":
        return _check_names(value)
    raise ValueError(f"Reglage du studio inconnu : {key}")


def read_studio(path: Path | None = None) -> dict:
    """Stored settings merged over DEFAULTS. Never raises (no FLUX_ROOT = defaults)."""
    out = copy.deepcopy(DEFAULTS)
    try:
        raw = read_json(path or studio_path())
    except RuntimeError:
        return out
    if not isinstance(raw, dict):
        return out
    for key in ("environment", "legacy_supervisors"):
        if key in raw:
            try:
                out[key] = _check_value(key, raw[key])
            except ValueError:
                pass  # keep the default
    return out


def write_studio(patch: dict, path: Path | None = None) -> dict:
    """Validate and merge *patch* into studio.json. Raises ValueError."""
    if not isinstance(patch, dict):
        raise ValueError("Reglages du studio : objet attendu")
    target = path or studio_path()
    merged = read_studio(target)
    for key, value in patch.items():
        if key == "schema_version":
            continue
        merged[key] = _check_value(key, value)
    merged["schema_version"] = SCHEMA_VERSION
    if not write_json(target, merged):
        raise ValueError(f"Ecriture impossible : {target}")
    return merged


def resolve_link(link: str) -> Path | None:
    """The file a studio link points to: absolute as is, relative to FLUX_ROOT. None if empty."""
    link = (link or "").strip()
    if not link:
        return None
    target = Path(link)
    if target.is_absolute() or link.startswith(("\\\\", "//")):
        return target
    root = paths.get_flux_root()
    return (Path(root) / target) if root else None


def environment_path(studio: dict | None = None) -> Path | None:
    """The environment file the studio links to, None when there is none."""
    return resolve_link((studio or read_studio())["environment"])


def legacy_supervisors(studio: dict | None = None) -> list[str]:
    return list((studio or read_studio())["legacy_supervisors"])
