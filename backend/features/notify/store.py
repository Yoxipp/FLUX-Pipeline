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
                    "include_project": False, "include_text": True,     # include_text: ADR 0072
                    "discord_bot": {},      # {"app_id", "name", "host"}: public, no token (ADR 0073)
                    "discord_sync": False,  # live bridge Team <-> Discord server (ADR 0084), opt-in
                    "discord_guild": ""}    # the project's Discord server id (one server per project)
USER_DEFAULTS = {"channel": "none", "discord_id": "", "ntfy_topic": "", "discord_linked_at": ""}

BOT_ALIVE_S = 120.0         # the host rewrites its heartbeat every 30 s
CANDIDATE_S = 600.0         # a waiting PC rewrites its line every 5 min (ADR 0082)
LINK_TTL_S = 600.0
BOT_QUEUE_TTL_S = 86400.0


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
    cfg["discord_sync"] = bool(cfg.get("discord_sync"))
    guild = str(cfg.get("discord_guild") or "").strip()
    cfg["discord_guild"] = guild if guild.isdigit() else ""
    bot = cfg.get("discord_bot")
    cfg["discord_bot"] = ({k: str(bot.get(k) or "") for k in ("app_id", "name", "host")}
                          if isinstance(bot, dict) and bot.get("app_id") else {})
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
        elif key in ("include_project", "include_text", "discord_sync"):
            value = bool(value)
        elif key == "discord_guild":
            value = str(value).strip()
            if value and not value.isdigit():
                raise ValueError("Serveur Discord : un identifiant en chiffres (clic droit sur le serveur > Copier l'identifiant)")
        elif key == "discord_bot":
            continue        # set_bot only
        cfg[key] = value
    return _write_cfg(project, cfg, by)


def _write_cfg(project: str, cfg: dict, by: str) -> dict:
    doc = {"schema_version": SCHEMA_VERSION, "notify": cfg, "updated_by": by,
           "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if not write_json(collab_path(project), doc):
        raise OSError(f"Ecriture de {JSON_COLLAB} impossible")
    return cfg


def set_bot(project: str, info: dict | None, by: str) -> dict:
    """Record (or clear with None) the public bot info of *project*: app id, name, host PC."""
    cfg = read_project(project)
    cfg["discord_bot"] = {k: str(info.get(k) or "") for k in ("app_id", "name", "host")} if info else {}
    return _write_cfg(project, cfg, by)


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
        if value != prefs["discord_id"]:
            prefs["discord_linked_at"] = ""     # typed by hand: never trusted by the bot
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


def is_linked(prefs: dict) -> bool:
    """Discord id proven by /link (ADR 0073), not typed by hand."""
    return bool(prefs.get("discord_id")) and bool(prefs.get("discord_linked_at"))


def has_channel(prefs: dict, project_cfg: dict) -> bool:
    if prefs.get("channel") == "discord":
        if not prefs.get("discord_id"):
            return False
        return bool(project_cfg.get("discord_webhook")) or (bool(project_cfg.get("discord_bot")) and is_linked(prefs))
    if prefs.get("channel") == "ntfy":
        return bool(prefs.get("ntfy_topic"))
    return False


# ── Discord bot shared files (ADR 0073) ───────────────────────────────────────
# _flux_setup/discord_bot_alive.json  {"host", "at"}          written by the host PC only
# _flux_setup/discord_links.json      {"codes": {sha256: {"discord_id", "expires"}}}  host only
# _flux_setup/notify_bot/<AUTHOR>.json [{"id", "discord_id", "text", "created"}]   one file per author
# No token anywhere here. Link codes are stored hashed: reading the share gives no usable code.

def _setup_file(project: str, name: str):
    return setup_path(paths.get_project_path(project), name)


def _code_hash(code: str) -> str:
    import hashlib
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def write_alive(project: str, host: str, now: float) -> bool:
    return write_json(_setup_file(project, "discord_bot_alive.json"), {"host": host, "at": now})


def bot_alive(project: str, now: float) -> bool:
    return bool(bot_host_now(project, now))


def bot_host_now(project: str, now: float) -> str:
    """The PC whose bot answers right now (fresh heartbeat), "" when offline."""
    data = read_json(_setup_file(project, "discord_bot_alive.json")) or {}
    try:
        fresh = isinstance(data, dict) and now - float(data.get("at", 0)) < BOT_ALIVE_S
    except (TypeError, ValueError):
        return ""
    return str(data.get("host") or "?") if fresh else ""


# ADR 0082: several PCs may hold the token; one hosts, the others wait to take over.
# _flux_setup/discord_bot_host.lock        core.host_lock record, the election
# _flux_setup/discord_bot_candidates.json  {host: at}  each PC with the token, refreshed while it waits

def bot_host_lock_path(project: str):
    return _setup_file(project, "discord_bot_host.lock")


def write_candidate(project: str, host: str, now: float) -> bool:
    path = _setup_file(project, "discord_bot_candidates.json")
    data = read_json(path) or {}
    data = {h: at for h, at in data.items() if isinstance(at, (int, float)) and now - at < CANDIDATE_S} \
        if isinstance(data, dict) else {}
    data[host] = now
    return write_json(path, data)


def drop_candidate(project: str, host: str) -> bool:
    path = _setup_file(project, "discord_bot_candidates.json")
    data = read_json(path) or {}
    if not isinstance(data, dict) or host not in data:
        return True
    data.pop(host)
    return write_json(path, data)


def bot_candidates(project: str, now: float) -> list[str]:
    """PCs ready to host the bot (seen within CANDIDATE_S), sorted."""
    data = read_json(_setup_file(project, "discord_bot_candidates.json")) or {}
    if not isinstance(data, dict):
        return []
    return sorted(h for h, at in data.items() if isinstance(at, (int, float)) and now - at < CANDIDATE_S)


def add_link_code(project: str, code: str, discord_id: str, now: float) -> bool:
    path = _setup_file(project, "discord_links.json")
    data = read_json(path) or {}
    codes = {h: c for h, c in (data.get("codes") or {}).items()
             if isinstance(c, dict) and float(c.get("expires", 0)) > now} if isinstance(data, dict) else {}
    codes[_code_hash(code)] = {"discord_id": str(discord_id), "expires": now + LINK_TTL_S}
    return write_json(path, {"codes": codes})


def drop_link_codes(project: str, discord_ids: set[str], now: float) -> None:
    """Host side: remove used (linked) and expired codes, so a code works once."""
    path = _setup_file(project, "discord_links.json")
    data = read_json(path) or {}
    codes = (data.get("codes") or {}) if isinstance(data, dict) else {}
    kept = {h: c for h, c in codes.items() if isinstance(c, dict)
            and float(c.get("expires", 0)) > now and c.get("discord_id") not in discord_ids}
    if kept != codes:
        write_json(path, {"codes": kept})


def link_discord(project: str, name: str, code: str, now: float) -> dict:
    """The person's own FLUX: a /link code proves their Discord id. Returns the new prefs."""
    data = read_json(_setup_file(project, "discord_links.json")) or {}
    entry = ((data.get("codes") or {}) if isinstance(data, dict) else {}).get(_code_hash(code))
    if not isinstance(entry, dict) or float(entry.get("expires", 0)) <= now:
        raise ValueError("Code inconnu ou expire : retape /link dans Discord")
    discord_id = str(entry.get("discord_id") or "")
    for other in list_linked():
        if other[1] == discord_id and other[0].upper() != name.upper():
            raise ValueError(f"Ce compte Discord est deja lie a {other[0]}")
    user = read_user_data(name)
    prefs = read_user(name)
    prefs.update({"discord_id": discord_id, "channel": "discord",
                  "discord_linked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    user["notify"] = prefs
    if not write_user_data(name, user):
        raise OSError("Ecriture de User.json impossible")
    return prefs


def list_linked() -> list[tuple[str, str]]:
    """(FLUX name, Discord id) of every linked account."""
    from utils.user_utils import list_users
    out = []
    for name in list_users():
        prefs = read_user(name)
        if is_linked(prefs):
            out.append((name, prefs["discord_id"]))
    return out


def user_for_discord(discord_id: str) -> str | None:
    """The one FLUX account linked to *discord_id*; None when none or ambiguous."""
    names = [n for n, d in list_linked() if d == str(discord_id)]
    return names[0] if len(names) == 1 else None


def _queue_dir(project: str):
    return _setup_file(project, "notify_bot")


def bot_queue_add(project: str, author: str, item: dict, now: float) -> bool:
    """A PC without the token leaves the DM for the host (its own file only)."""
    path = _queue_dir(project) / f"{(author or 'UNKNOWN').upper()}.json"
    items = read_json(path) or []
    items = [i for i in items if isinstance(i, dict) and now - float(i.get("created", 0)) < BOT_QUEUE_TTL_S] \
        if isinstance(items, list) else []
    items.append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_json(path, items)


def bot_queue_items(project: str, now: float) -> list[dict]:
    folder = _queue_dir(project)
    out: list[dict] = []
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        return out
    for path in files:
        items = read_json(path) or []
        if isinstance(items, list):
            out += [i for i in items if isinstance(i, dict) and i.get("id")
                    and now - float(i.get("created", 0)) < BOT_QUEUE_TTL_S]
    return out
