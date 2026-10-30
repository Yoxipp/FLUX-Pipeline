# store.py - notify settings: per project (_flux_setup/collab.json) and per person
# (User.json "notify"). Plain JSON so a flow can read them later (ADR 0062).
#
# collab.json: {"schema_version": 1, "notify": {"discord_webhook", "ntfy_server",
#               "digest_minutes", "include_project", "include_text"}, "updated_by", "updated_at"}
#   Edited by a lead / supervisor only (role "project_settings"), rarely: one document
#   is acceptable here, like roles.json.
# User.json "notify": {"channel": none | discord | ntfy, "discord_id", "ntfy_topic"}
#   Written by its owner only (one file per author).
# Secrets come out masked through public_*(); the raw values never leave the backend.

from __future__ import annotations

from datetime import datetime, timezone

from core import paths
from core.constants import JSON_COLLAB
from core.json_manager import read_json, write_json
from core.project_setup import setup_path
from features.notify.channels.ntfy import DEFAULT_SERVER
from features.notify.relay_secrets import is_masked, mask, new_topic
from utils.user_utils import read_user_data, write_user_data

SCHEMA_VERSION = 1
CHANNELS = ("none", "discord", "ntfy")
DIGEST_MIN, DIGEST_MAX = 1, 120

PROJECT_DEFAULTS = {"discord_webhook": "", "ntfy_server": DEFAULT_SERVER, "digest_minutes": 5,
                    "include_project": False, "include_text": True}     # include_text: ADR 0072
USER_DEFAULTS = {"channel": "none", "discord_id": "", "ntfy_topic": ""}


def collab_path(project: str):
    return setup_path(paths.get_project_path(project), JSON_COLLAB)


# ── project ───────────────────────────────────────────────────────────────────

def read_project(project: str) -> dict:
    raw = read_json(collab_path(project)) or {}
    stored = raw.get("notify") if isinstance(raw, dict) else None
    cfg = dict(PROJECT_DEFAULTS)
    if isinstance(stored, dict):
        cfg.update({k: stored[k] for k in PROJECT_DEFAULTS if k in stored})
    cfg["digest_minutes"] = _clamp_minutes(cfg.get("digest_minutes"))
    cfg["include_project"] = bool(cfg.get("include_project"))
    cfg["include_text"] = bool(cfg.get("include_text"))
    cfg["ntfy_server"] = str(cfg.get("ntfy_server") or DEFAULT_SERVER).rstrip("/")
    return cfg


def write_project(project: str, patch: dict, by: str) -> dict:
    """Merge *patch* (a masked webhook = unchanged) and save. Returns the raw config."""
    cfg = read_project(project)
    for key in PROJECT_DEFAULTS:
        if key not in patch or patch[key] is None:
            continue
        value = patch[key]
        if key == "discord_webhook":
            if is_masked(value):
                continue
            value = str(value).strip()
            if value and not value.startswith("https://"):
                raise ValueError("Le webhook Discord doit commencer par https://")
        elif key == "ntfy_server":
            value = str(value).strip().rstrip("/") or DEFAULT_SERVER
            if not value.startswith(("https://", "http://")):
                raise ValueError("Le serveur ntfy doit etre une URL http(s)")
        elif key == "digest_minutes":
            value = _clamp_minutes(value)
        elif key in ("include_project", "include_text"):
            value = bool(value)
        cfg[key] = value
    doc = {"schema_version": SCHEMA_VERSION, "notify": cfg, "updated_by": by,
           "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if not write_json(collab_path(project), doc):
        raise OSError(f"Ecriture de {JSON_COLLAB} impossible")
    return cfg


def public_project(cfg: dict) -> dict:
    return {**cfg, "discord_webhook": mask(cfg.get("discord_webhook")),
            "has_webhook": bool(cfg.get("discord_webhook"))}


def _clamp_minutes(value) -> int:
    try:
        return max(DIGEST_MIN, min(DIGEST_MAX, int(value)))
    except (TypeError, ValueError):
        return PROJECT_DEFAULTS["digest_minutes"]


# ── person ────────────────────────────────────────────────────────────────────

def read_user(name: str) -> dict:
    stored = read_user_data(name).get("notify")
    prefs = dict(USER_DEFAULTS)
    if isinstance(stored, dict):
        prefs.update({k: str(stored.get(k) or "") for k in USER_DEFAULTS if k in stored})
    if prefs["channel"] not in CHANNELS:
        prefs["channel"] = "none"
    return prefs


def write_user(name: str, patch: dict) -> dict:
    data = read_user_data(name)
    prefs = read_user(name)
    if "channel" in patch and patch["channel"] is not None:
        if patch["channel"] not in CHANNELS:
            raise ValueError(f"Canal inconnu : {patch['channel']}")
        prefs["channel"] = patch["channel"]
    if patch.get("discord_id") is not None:
        value = str(patch["discord_id"]).strip()
        if value and not value.isdigit():
            raise ValueError("L'identifiant Discord est un nombre (Parametres Discord > Mode developpeur)")
        prefs["discord_id"] = value
    if patch.get("regenerate_topic") or (prefs["channel"] == "ntfy" and not prefs["ntfy_topic"]):
        prefs["ntfy_topic"] = new_topic()
    data["notify"] = prefs
    if not write_user_data(name, data):
        raise OSError("Ecriture de User.json impossible")
    return prefs


def public_user(prefs: dict, server: str = DEFAULT_SERVER) -> dict:
    """The person's own view: the topic is shown in full to its owner only (QR code)."""
    topic = prefs.get("ntfy_topic", "")
    base = (server or DEFAULT_SERVER).rstrip("/")
    return {**prefs, "ntfy_url": f"{base}/{topic}" if topic else ""}


def has_channel(prefs: dict, project_cfg: dict) -> bool:
    if prefs.get("channel") == "discord":
        return bool(prefs.get("discord_id")) and bool(project_cfg.get("discord_webhook"))
    if prefs.get("channel") == "ntfy":
        return bool(prefs.get("ntfy_topic"))
    return False
