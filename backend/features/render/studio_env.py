# studio_env.py - the studio's farm environment file (ADR 0063).
#
# CONFIG/studio.json "environment" links to a JSON file holding everything the render code
# must know about THIS studio's farm (engine, blade paths, tags, room naming...). FLUX ships
# with nothing: every value is empty or neutral, so no school or studio is written in the code.
#
#   {"schema_version": 1, "name": "", "farm": {...see FARM_DEFAULTS...}}
#
# Precedence of a render setting (team_settings.effective_settings):
#   value stored in the project's render.json > this environment > empty.
# Keys are stable (ADR 0004): only add new ones.
from __future__ import annotations

import copy
import re
from pathlib import Path

from core import studio_config
from core.json_manager import read_json, write_json

SCHEMA_VERSION = 1
# Tractor's implicit limit tag of a husk command is the application name; "default" is the Share
# name FLUX has always read for projects the engine does not list (observed on a real engine).
NEUTRAL_RENDER_TAG = "husk"
NEUTRAL_DEFAULT_SHARE = "default"
RENDERERS = ("karma", "renderman")

FARM_DEFAULTS: dict = {
    "engine": "",                # host:port of the Tractor engine (empty => TRACTOR_ENGINE of the machine)
    "engine_user": "",           # engine login (empty => the FLUX user name, see tractor_bridge)
    "engine_config_dir": "",     # folder of the engine's limits.config (UNC)
    "bridge_python": "",         # Tractor's Python 2.7 on the workstations (runs the bridge)
    "blade_tractor_python": "",  # the same Python as seen from the blades (runs the freeze-at-start script)
    "houdini_path": "",          # Houdini install folder on the blades
    "denoise_path": "",          # denoise_batch on the blades
    "husk_path": "",             # husk on the blades (empty => "husk" from the blade PATH)
    "renderer": "",              # "" = choose at launch, or karma | renderman
    "priority": 1,               # default job priority (Tractor: higher goes first)
    "render_tag": NEUTRAL_RENDER_TAG,
    "default_share": NEUTRAL_DEFAULT_SHARE,
    "denoise_tag": "",           # limit tag added to denoise commands ("" = no -tags)
    "room_pattern": "",          # regex with groups: blade name -> room ("" = no room grouping)
    "forbid_drive_letters": False,
    "service_karma": "",
    "service_renderman": "",
    "envkeys": [],
}
DEFAULTS: dict = {"schema_version": SCHEMA_VERSION, "name": "", "farm": FARM_DEFAULTS}

_ENGINE = re.compile(r"^[A-Za-z0-9_.-]+(:\d{1,5})?$")
_USER = re.compile(r"^[A-Za-z0-9_.@\\-]{1,64}$")
_TAG = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_PATH_KEYS = ("bridge_python", "blade_tractor_python", "houdini_path", "denoise_path", "husk_path")
_SLASH_KEYS = ("blade_tractor_python", "houdini_path", "denoise_path", "husk_path")  # written in job scripts
_TEXT_KEYS = ("service_karma", "service_renderman")
_LABELS = {
    "engine": "Moteur Tractor", "engine_user": "Compte du moteur", "engine_config_dir": "Dossier de config du moteur",
    "bridge_python": "Python de Tractor (postes)", "blade_tractor_python": "Python de Tractor (blades)",
    "houdini_path": "Dossier Houdini des blades", "denoise_path": "denoise_batch des blades",
    "husk_path": "husk des blades", "renderer": "Moteur de rendu par defaut", "priority": "Priorite par defaut",
    "render_tag": "Tag de limite des rendus", "default_share": "Part par defaut",
    "denoise_tag": "Tag de limite du denoise", "room_pattern": "Motif des salles",
    "forbid_drive_letters": "Refuser les lettres de lecteur", "service_karma": "Service Karma",
    "service_renderman": "Service RenderMan", "envkeys": "Cles d'environnement",
}


class StudioEnvError(ValueError):
    """Readable French message: nothing was written."""


def check_room_pattern(pattern: str) -> re.Pattern:
    """Compile a room pattern: it needs at least one group (the room name is built from the groups)."""
    if len(pattern) > 200:
        raise StudioEnvError(f"{_LABELS['room_pattern']} : 200 caracteres au plus")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise StudioEnvError(f"{_LABELS['room_pattern']} : expression invalide ({exc})") from None
    if regex.groups < 1:
        raise StudioEnvError(f"{_LABELS['room_pattern']} : au moins un groupe entre parentheses est attendu, "
                             "par exemple ^([A-Za-z]+)(\\d{2})")
    return regex


def _check(key: str, value):
    label = _LABELS.get(key, key)
    if key == "priority":
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 10000:
            raise StudioEnvError(f"{label} : nombre entier entre 1 et 10000")
        return value
    if key == "forbid_drive_letters":
        if not isinstance(value, bool):
            raise StudioEnvError(f"{label} : oui ou non")
        return value
    if key == "envkeys":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise StudioEnvError(f"{label} : liste de textes")
        return [v.strip() for v in value if v.strip()]
    if not isinstance(value, str):
        raise StudioEnvError(f"{label} : texte attendu")
    value = value.strip()
    if "\n" in value or "\r" in value or "\0" in value:
        raise StudioEnvError(f"{label} : une seule ligne attendue")
    if not value:
        return ""
    if key == "engine":
        if not _ENGINE.match(value):
            raise StudioEnvError(f"{label} : forme attendue hote ou hote:port")
        return value
    if key == "engine_user":
        if not _USER.match(value):
            raise StudioEnvError(f"{label} : lettres, chiffres et _ . @ - seulement (64 au plus)")
        return value
    if key == "renderer":
        if value not in RENDERERS:
            raise StudioEnvError(f"{label} : vide, karma ou renderman")
        return value
    if key in ("render_tag", "default_share", "denoise_tag"):
        if not _TAG.match(value):
            raise StudioEnvError(f"{label} : lettres, chiffres et _ . - seulement (64 au plus)")
        return value
    if key == "room_pattern":
        check_room_pattern(value)
        return value
    if key in _SLASH_KEYS:
        value = value.replace("\\", "/")
        return value.rstrip("/") if key == "houdini_path" else value
    return value  # bridge_python, engine_config_dir, service_*: kept as typed


def check_farm(farm: dict) -> dict:
    """Validated copy of *farm* (known keys only). Raises StudioEnvError."""
    if not isinstance(farm, dict):
        raise StudioEnvError("Environnement : objet 'farm' attendu")
    unknown = sorted(set(farm) - set(FARM_DEFAULTS))
    if unknown:
        raise StudioEnvError(f"Reglage d'environnement inconnu : {', '.join(unknown)}")
    return {key: _check(key, value) for key, value in farm.items()}


def _merge(raw) -> dict:
    out = copy.deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return out
    if isinstance(raw.get("name"), str):
        out["name"] = raw["name"].strip()
    farm = raw.get("farm")
    for key, value in (farm.items() if isinstance(farm, dict) else ()):
        if key in FARM_DEFAULTS:
            try:
                out["farm"][key] = _check(key, value)
            except StudioEnvError:
                pass  # a bad value reads as the neutral default
    for key, default in (("render_tag", NEUTRAL_RENDER_TAG), ("default_share", NEUTRAL_DEFAULT_SHARE)):
        out["farm"][key] = out["farm"][key] or default
    return out


def environment_file() -> Path | None:
    """The linked environment file, None when the studio has no link (or no FLUX_ROOT)."""
    try:
        return studio_config.environment_path()
    except RuntimeError:
        return None


def read_environment(path: Path | None = None) -> dict:
    """The studio environment. Never raises: no link, missing or unreadable file = all neutral."""
    target = path if path is not None else environment_file()
    if target is None:
        return _merge(None)
    try:
        return _merge(read_json(target))
    except Exception:  # unreachable share, bad permissions: the farm settings stay empty
        return _merge(None)


def farm() -> dict:
    return read_environment()["farm"]


def write_environment(patch: dict, path: Path | None = None) -> dict:
    """Validate and merge *patch* ({"name"?, "farm"?}) into the linked file. Raises StudioEnvError."""
    if not isinstance(patch, dict):
        raise StudioEnvError("Environnement : objet attendu")
    target = path if path is not None else environment_file()
    if target is None:
        raise StudioEnvError("Aucun fichier d'environnement lie : renseigner le lien du studio d'abord")
    unknown = sorted(set(patch) - {"name", "farm", "schema_version"})
    if unknown:
        raise StudioEnvError(f"Champ inconnu : {', '.join(unknown)}")
    merged = read_environment(target)
    if "name" in patch:
        if not isinstance(patch["name"], str):
            raise StudioEnvError("Nom de l'environnement : texte attendu")
        merged["name"] = patch["name"].strip()
    if "farm" in patch:
        merged["farm"].update(check_farm(patch["farm"]))
    merged["schema_version"] = SCHEMA_VERSION
    if not write_json(target, merged):
        raise StudioEnvError(f"Ecriture impossible : {target}")
    return read_environment(target)


def room_of(name: str, pattern: str) -> str | None:
    """Room of a blade from the studio pattern: the groups joined, upper case. None = no room."""
    if not pattern:
        return None
    try:
        match = check_room_pattern(pattern).match(name or "")
    except StudioEnvError:
        return None
    if not match:
        return None
    room = "".join(g for g in match.groups() if g)
    return room.upper() or None
