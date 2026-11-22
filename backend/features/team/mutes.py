# mutes.py — channels and groups an artist muted in the team chat (P5, 2026-10-31).
# Personal, never in the shared journal: each FLUX writes ITS OWN file
# USER/<artist>/team_mutes.json = {project: {"channels": [keys], "groups": [rids]}}
# (one file per author, ADR 0062). A muted channel (or a channel of a muted group) no
# longer rings the phone for "Prevenir l'equipe" and shows no unread count; an @mention of
# the artist still notifies (chat_manager._record_mentions is not filtered).

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

FILE = "team_mutes.json"
MAX_ITEMS = 200


def _users_dir() -> Path:
    from core.paths import get_users_dir

    return get_users_dir()


def _read_doc(user: str, root: Optional[Path] = None) -> Dict[str, Any]:
    try:
        doc = json.loads(((root or _users_dir()) / user / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def read(user: str, project: str, root: Optional[Path] = None) -> Dict[str, List[str]]:
    entry = _read_doc(user, root).get(project)
    entry = entry if isinstance(entry, dict) else {}
    return {k: [str(x) for x in entry.get(k) or [] if isinstance(x, str)][:MAX_ITEMS] for k in ("channels", "groups")}


def write(user: str, project: str, channels: List[str], groups: List[str], root: Optional[Path] = None) -> Dict[str, List[str]]:
    folder = (root or _users_dir()) / user
    if not user or not folder.is_dir():
        raise FileNotFoundError("artiste inconnu : choisis ton nom dans Parametres > User")
    doc = _read_doc(user, root)
    entry = {"channels": sorted(set(channels))[:MAX_ITEMS], "groups": sorted(set(groups))[:MAX_ITEMS]}
    if entry["channels"] or entry["groups"]:
        doc[project] = entry
    else:
        doc.pop(project, None)
    path = folder / FILE
    tmp = path.with_name(f".flux_tmp_{secrets.token_hex(4)}.json")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return entry


def is_muted(user: str, project: str, channel: Optional[str], records: List[Dict[str, Any]],
             root: Optional[Path] = None) -> bool:
    """True when *user* muted *channel* (None = #general) or its group."""
    from features.team import team_meta

    mine = read(user, project, root)
    name = channel or team_meta.GENERAL
    if name in mine["channels"]:
        return True
    rec = team_meta.channel_record(records, name)
    return bool(rec and rec.get("group") and str(rec["group"]) in mine["groups"])
