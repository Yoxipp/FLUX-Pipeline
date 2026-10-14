# project_config.py - per-project config file <project>/project.json (ADR 0006, 0011).
#
# Holds the stable project identity (project_id, base of the logical keys, ADR 0004)
# and project-wide settings (fps, resolution, USD units, OCIO, env, storage).
# Created by create_project and automatically at the first open of an existing
# project. Creation is exclusive (O_EXCL) then re-read, so two machines opening the
# same synced project at once end up with one project_id. OneDrive conflict copies
# ("project-PC.json") are detected: the oldest project_id wins and is reported.

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.constants import JSON_PROJECT
from core.project_setup import setup_path
from core.json_manager import read_json, write_json
from core.logger import get_logger

log = get_logger(__name__)

SCHEMA_VERSION = 1

# No Python expressions in the config (ADR 0006): plain JSON values only.
PROJECT_SCHEMA: dict = {
    "type": "object",
    "required": ["project_id", "schema_version", "usd"],
    "properties": {
        "project_id":     {"type": "string", "minLength": 1},
        "schema_version": {"type": "integer", "minimum": 1},
        "created_at":     {"type": "string"},
        "fps":            {"type": "number", "exclusiveMinimum": 0},
        "resolution": {
            "type": "array", "minItems": 2, "maxItems": 2,
            "items": {"type": "integer", "minimum": 1},
        },
        "usd": {
            "type": "object",
            "required": ["meters_per_unit", "up_axis"],
            "properties": {
                "meters_per_unit": {"type": "number", "exclusiveMinimum": 0},
                "up_axis":         {"enum": ["Y", "Z"]},
            },
        },
        "ocio_config": {"type": "string"},
        "env":         {"type": "object", "additionalProperties": {"type": "string"}},
        "storage":     {"type": "object"},
        # Painter export presets of the project (Publisher offers only those).
        "texturing": {
            "type": "object",
            "properties": {"painter_presets": {"type": "array", "items": {"type": "string"}}},
        },
        # Work profiles shared by the project (role presets, see sanitize_work_profiles).
        "ui": {
            "type": "object",
            "properties": {"work_profiles": {"type": "array", "items": {"type": "object"}}},
        },
    },
}

MAX_WORK_PROFILES = 20
MAX_PROFILE_NAME = 40


def is_direct_project_dir(project_path: Path, projects_root: Path) -> bool:
    """True if *project_path* is an existing direct child of *projects_root* (no '..')."""
    try:
        resolved = Path(project_path).resolve()
        return resolved.is_dir() and resolved.parent == Path(projects_root).resolve()
    except OSError:
        return False


def project_config_path(project_path: Path) -> Path:
    return setup_path(project_path, JSON_PROJECT)


def default_project_config() -> dict:
    """A fresh config: new project_id, Houdini reference units (ADR 0011)."""
    return {
        "project_id": uuid.uuid4().hex,
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fps": 24,
        "resolution": [1920, 1080],
        "usd": {"meters_per_unit": 1.0, "up_axis": "Y"},
        "ocio_config": "",
        "env": {},
        "storage": {},
    }


def validate_project_config(data: object) -> list[str]:
    """Return the schema errors of *data* (empty list = valid)."""
    if not isinstance(data, dict):
        return ["project.json must be a JSON object"]
    try:
        from jsonschema import Draft202012Validator  # type: ignore
    except Exception:  # pragma: no cover - stripped env: minimal check only
        return [] if data.get("project_id") else ["project_id missing"]
    validator = Draft202012Validator(PROJECT_SCHEMA)
    return [
        f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
        for err in validator.iter_errors(data)
    ]


def read_project_config(project_path: Path) -> dict | None:
    """Return project.json content, or None when absent or unreadable."""
    path = project_config_path(project_path)
    if not path.is_file():
        return None
    data = read_json(path)
    return data if isinstance(data, dict) and data else None


def sanitize_work_profiles(profiles: object) -> list[dict]:
    """Keep only well formed {id, name, prefs} entries with scalar pref values.

    The frontend owns the meaning of each pref and re-validates it; the backend only
    guarantees the shape so a hand-edited project.json can never break the UI.
    """
    if not isinstance(profiles, list):
        return []
    clean: list[dict] = []
    seen: set[str] = set()
    for item in profiles:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()[:MAX_PROFILE_NAME]
        if not pid or not name or pid in seen:
            continue
        prefs = item.get("prefs") if isinstance(item.get("prefs"), dict) else {}
        prefs = {str(k): v for k, v in prefs.items() if isinstance(v, (str, bool, int, float))}
        seen.add(pid)
        clean.append({"id": pid, "name": name, "prefs": prefs})
        if len(clean) >= MAX_WORK_PROFILES:
            break
    return clean


def read_work_profiles(project_path: Path) -> list[dict]:
    """Work profiles shared by the project (project.json "ui.work_profiles")."""
    cfg = read_project_config(project_path) or {}
    ui = cfg.get("ui") if isinstance(cfg.get("ui"), dict) else {}
    return sanitize_work_profiles(ui.get("work_profiles"))


def write_work_profiles(project_path: Path, profiles: object) -> list[dict]:
    """Replace the project's shared work profiles, keeping every other key."""
    cfg, _warnings = ensure_project_config(project_path)
    clean = sanitize_work_profiles(profiles)
    ui = dict(cfg.get("ui")) if isinstance(cfg.get("ui"), dict) else {}
    ui["work_profiles"] = clean
    cfg["ui"] = ui
    if not write_json(project_config_path(project_path), cfg):
        raise OSError("project.json : ecriture impossible")
    return clean


def ensure_project_config(project_path: Path) -> tuple[dict, list[str]]:
    """Create or heal <project>/project.json. Returns (config, warnings).

    Idempotent: never changes an existing project_id (except to adopt the oldest
    one of a OneDrive conflict copy), only fills missing keys with defaults.
    """
    project_path = Path(project_path)
    path = project_config_path(project_path)
    warnings: list[str] = []

    created = False
    if not path.is_file():
        created = _create_exclusive(path, default_project_config())

    data = read_project_config(project_path)
    if data is None:
        # Present but empty/corrupt: keep the bad file aside, never lose it.
        backup = path.with_name(f"{path.stem}.corrupt-{_stamp()}{path.suffix}")
        try:
            os.replace(path, backup)
            warnings.append(f"project.json illisible, sauvegarde : {backup.name}")
        except OSError as exc:
            warnings.append(f"project.json illisible et non deplacable : {exc}")
            return default_project_config(), warnings
        created = _create_exclusive(path, default_project_config()) or created
        data = read_project_config(project_path) or default_project_config()

    healed = _heal(data)
    adopted = _adopt_oldest_conflict_copy(project_path, healed, warnings)
    if healed != data or adopted:
        if not write_json(path, healed):
            warnings.append("project.json : ecriture de la reparation impossible")
        else:
            log.info("project.json healed for %s", project_path.name)

    errors = validate_project_config(healed)
    warnings.extend(f"project.json invalide : {e}" for e in errors)
    for w in warnings:
        log.warning("%s (%s)", w, project_path.name)
    if created or adopted:
        _notify_identity_created()
    return healed, warnings


# ── internals ─────────────────────────────────────────────────────────────────

def _notify_identity_created() -> None:
    """New project identity: let a logical-key backend move this project's keys (U2)."""
    try:
        from core.repository_factory import on_project_identity_created
        on_project_identity_created()
    except Exception as exc:  # noqa: BLE001
        log.warning("Logical key migration after project.json creation skipped: %s", exc)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _create_exclusive(path: Path, data: dict) -> bool:
    """Write *data* only if *path* does not exist yet (O_EXCL). False if it existed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("project.json created: %s", path)
    return True


def _heal(data: dict) -> dict:
    """Fill missing keys with defaults; keep every existing value."""
    healed = dict(data)
    defaults = default_project_config()
    if not isinstance(healed.get("project_id"), str) or not healed.get("project_id"):
        healed["project_id"] = defaults["project_id"]
    for key, value in defaults.items():
        if key not in healed:
            healed[key] = value
    if isinstance(healed.get("usd"), dict):
        usd = dict(healed["usd"])
        for key, value in defaults["usd"].items():
            usd.setdefault(key, value)
        healed["usd"] = usd
    return healed


def _adopt_oldest_conflict_copy(project_path: Path, data: dict, warnings: list[str]) -> bool:
    """Look for OneDrive conflict copies (project-*.json); adopt the oldest project_id."""
    stem, suffix = Path(JSON_PROJECT).stem, Path(JSON_PROJECT).suffix
    candidates: list[dict] = []
    for copy in sorted(project_config_path(project_path).parent.glob(f"{stem}-*{suffix}")):
        other = read_json(copy)
        if isinstance(other, dict) and isinstance(other.get("project_id"), str):
            candidates.append({"file": copy.name, **other})
    if not candidates:
        return False
    names = ", ".join(c["file"] for c in candidates)
    warnings.append(f"copies de conflit project.json detectees : {names}")
    oldest = min(
        [{"file": JSON_PROJECT, **data}, *candidates],
        key=lambda c: str(c.get("created_at") or "9999"),
    )
    if oldest["project_id"] == data["project_id"]:
        return False
    warnings.append(f"project_id du plus ancien adopte ({oldest['file']})")
    data["project_id"] = oldest["project_id"]
    if oldest.get("created_at"):
        data["created_at"] = oldest["created_at"]
    return True
