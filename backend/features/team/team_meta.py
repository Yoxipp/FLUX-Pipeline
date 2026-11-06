# team_meta.py — what the Team page adds around the existing team chat (ADR 0077):
# channels (a lead creates / archives them, each with an optional call link), reactions on
# a message (one record per author) and pinned messages (a lead pins). Zero server: the
# same per author journals as the board (flux_flows/page_data.py), in
#   DOSSIER_PROJETS/<project>/_flux_setup/team/<AUTHOR>.jsonl
# The messages themselves stay in the team chat (features/activity/chat_manager.py).
#
# Who sees a channel (2026-10-30): a channel may carry `access` (JSON text, the shape of
# a TOOL page's access, ADR 0078: people, roles). Empty = everyone; #general is
# always everyone; leads and supervisors see every channel (they manage them). This is what
# FLUX shows and notifies, not secrecy: the chat file stays readable on the share.
#
# Groups and voice channels (P4 lot 1, ADR 0084): a lead makes groups (`kind: group`, a free
# label, like a Discord category); a channel carries `group` (the group's rid, so a rename
# keeps it), `type` text | voice (a voice channel's call link is its Join button) and
# `order` (a float, a drop between two channels takes the middle). Works without Discord.
#
# Archive (2026-10-31): an archived channel comes back only from the project's archives
# (Projects > Archived). A new channel with the name of an archived one starts empty: its
# key (`name`, what the messages carry) gets a suffix (lighting-2) and `title` keeps the
# name shown. Two live channels never show the same name.
#
# Discord-like options (P5, 2026-10-31): a lead renames a channel (`title`, the key
# stays), writes its `topic`, makes it `read_only` (only leads / supervisors post, the others
# read and react). A group may carry `access`: its channels without their own inherit it (like
# "synced" on Discord). Types: text, voice (`user_limit`, `voice_status`), forum (each root
# message is a post with a title), announcement (read only, its own icon).

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from flux_flows import page_data
from flux_flows.pages import Access, DataSpec, page_for
from flux_flows.store import FlowStoreError

GENERAL = "general"
EMOJIS = ("like", "love", "laugh", "question", "check")
CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_LINK = 500
MAX_GROUP = 40
CHANNEL_TYPES = ("text", "voice", "forum", "announcement")
MAX_STATUS = 120
MAX_USER_LIMIT = 99

SPEC = DataSpec.model_validate({
    "id": "team",
    "fields": [
        {"id": "kind", "type": "select", "required": True,
         "options": [{"value": "channel"}, {"value": "group"}, {"value": "reaction"}, {"value": "pin"}]},
        {"id": "name", "type": "str"},           # channel key (messages carry it), group label
        {"id": "title", "type": "str"},          # channel: name shown when the key has a suffix
        {"id": "topic", "type": "text"},         # channel description
        {"id": "call_link", "type": "str"},      # https link of the channel's call (Discord, Teams, Meet, Jitsi)
        {"id": "archived", "type": "bool"},
        {"id": "access", "type": "text"},        # who sees the channel / group: JSON {users, roles}
        {"id": "type", "type": "select", "options": [{"value": t} for t in CHANNEL_TYPES]},  # channel type
        {"id": "read_only", "type": "bool"},     # channel: only leads / supervisors post
        {"id": "user_limit", "type": "int"},     # voice channel: people at most (0 / empty = no limit)
        {"id": "voice_status", "type": "str"},   # voice channel: what is going on, one line
        {"id": "group", "type": "str"},          # channel: rid of its group record
        {"id": "order", "type": "float"},        # channel / group: position, lower first
        {"id": "target", "type": "str"},         # message id (reaction, pin)
        {"id": "emoji", "type": "select", "options": [{"value": e} for e in EMOJIS]},
    ],
})
LEAD_KINDS = ("channel", "group", "pin")


def folder(project: str) -> Path:
    from core.paths import get_project_path
    from core.project_setup import setup_path

    return setup_path(get_project_path(project), "team")


def check_link(value: Any) -> None:
    """A call link opens in the system browser: https only, no spaces."""
    if value in (None, ""):
        return
    if not isinstance(value, str) or len(value) > MAX_LINK or not value.startswith("https://") or any(c.isspace() for c in value):
        raise FlowStoreError("lien d'appel : une adresse https:// (Discord, Teams, Meet, Jitsi)", 422)


def _check_op(op: Dict[str, Any], records: Dict[str, Dict[str, Any]]) -> str:
    """The kind of record *op* touches; raises on a malformed channel / link."""
    fields = op.get("fields") or {}
    current = records.get(str(op.get("rid") or ""), {})
    kind = fields.get("kind") or current.get("kind")
    if op.get("op") == "put":
        if "call_link" in fields:
            check_link(fields["call_link"])
        if fields.get("access") not in (None, ""):
            if kind == "channel" and (fields.get("name") or current.get("name")) == GENERAL:
                raise FlowStoreError("#general est vu par toute l'equipe", 422)
            parse_access(fields["access"], strict=True)
        name = fields.get("name")
        if kind == "channel" and (fields.get("name") or current.get("name")) == GENERAL:
            if fields.get("title") not in (None, "", GENERAL) or fields.get("read_only") or                     fields.get("type") not in (None, "", "text"):
                raise FlowStoreError("#general garde son nom et reste un canal texte ouvert", 422)
        if "user_limit" in fields and fields["user_limit"] is not None:
            limit = fields["user_limit"]
            if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit <= MAX_USER_LIMIT:
                raise FlowStoreError(f"limite de personnes : 0 a {MAX_USER_LIMIT}", 422)
        if "voice_status" in fields and fields["voice_status"] is not None:
            if not isinstance(fields["voice_status"], str) or len(fields["voice_status"]) > MAX_STATUS:
                raise FlowStoreError(f"statut du vocal : {MAX_STATUS} caracteres au plus", 422)
        if kind == "channel" and op.get("rid") is None:
            if not isinstance(name, str) or not CHANNEL_RE.match(name):
                raise FlowStoreError("canal : minuscules, chiffres, - ou _ (32 max)", 422)
            if any(r.get("kind") == "channel" and r.get("name") == name for r in records.values()):
                raise FlowStoreError(f"le canal #{name} existe deja", 409)
        if kind == "channel" and fields.get("title") not in (None, ""):
            if not isinstance(fields["title"], str) or not CHANNEL_RE.match(fields["title"]):
                raise FlowStoreError("canal : minuscules, chiffres, - ou _ (32 max)", 422)
        if kind == "channel" and (op.get("rid") is None or fields.get("archived") is None and "archived" in fields
                                  or "title" in fields):
            merged = {**current, **fields}
            if not merged.get("archived"):
                shown = shown_name(merged)
                rid = str(op.get("rid") or "")
                if shown == GENERAL and merged.get("name") != GENERAL or                         any(r.get("kind") == "channel" and not r.get("archived") and r["rid"] != rid
                            and shown_name(r) == shown for r in records.values()):
                    raise FlowStoreError(f"un canal #{shown} est deja actif : archive-le avant", 409)
        if fields.get("group") not in (None, ""):
            target = records.get(str(fields["group"]))
            if kind != "channel" or not target or target.get("kind") != "group":
                raise FlowStoreError("groupe inconnu", 422)
        if kind == "group" and (op.get("rid") is None or "name" in fields):
            label = name.strip() if isinstance(name, str) else ""
            if not label or len(label) > MAX_GROUP:
                raise FlowStoreError(f"groupe : un nom de 1 a {MAX_GROUP} caracteres", 422)
            rid = str(op.get("rid") or "")
            if any(r.get("kind") == "group" and not r.get("archived") and r["rid"] != rid
                   and str(r.get("name") or "").strip().lower() == label.lower() for r in records.values()):
                raise FlowStoreError(f"le groupe {label} existe deja", 409)
        if kind in ("reaction", "pin") and op.get("rid") is None and not fields.get("target"):
            raise FlowStoreError(f"{kind} : message cible manquant", 422)
    return str(kind or "")


def is_read_only(record: Optional[Dict[str, Any]]) -> bool:
    """Only leads / supervisors post in it (read only flag or an announcement channel)."""
    return bool(record) and (bool(record.get("read_only")) or record.get("type") == "announcement")


def channel_record(records: List[Dict[str, Any]], channel: Optional[str]) -> Optional[Dict[str, Any]]:
    name = channel or GENERAL
    return next((r for r in records if r.get("kind") == "channel" and r.get("name") == name), None)


def effective_access(record: Dict[str, Any], groups: Dict[str, Dict[str, Any]]) -> Optional[Access]:
    """A channel's own access, else its (live) group's, None = everyone. #general: everyone."""
    if record.get("name") == GENERAL:
        return None
    own = parse_access(record.get("access"))
    if own is not None or record.get("access") not in (None, ""):
        return own
    group = groups.get(str(record.get("group") or ""))
    if group and not group.get("archived"):
        return parse_access(group.get("access"))
    return None


def shown_name(record: Dict[str, Any]) -> str:
    """Name a channel shows: its title, else its key."""
    return str(record.get("title") or record.get("name") or "")


def write(project: str, ops: List[Dict[str, Any]], *, user: str, is_lead: bool) -> Dict[str, Any]:
    """Append *ops* to the user's journal. Channels and pins: leads only. A reaction is
    removed only by its author (or a lead)."""
    where = folder(project)
    records = {r["rid"]: r for r in page_data.read_records(where)["records"]}
    for op in ops:
        kind = _check_op(op, records)
        if kind in LEAD_KINDS and not is_lead:
            raise FlowStoreError("reserve aux leads et superviseurs du projet", 403)
        if op.get("op") == "del" and kind == "reaction" and not is_lead:
            mine = records.get(str(op.get("rid")), {}).get("_created_by")
            if mine and mine != user:
                raise FlowStoreError("on ne retire que sa propre reaction", 403)
    return page_data.write_ops(where, SPEC, ops, user=user)


def read(project: str, known_etag: str | None = None) -> Dict[str, Any]:
    return page_data.read_records(folder(project), known_etag)


def parse_access(value: Any, strict: bool = False) -> Optional[Access]:
    """Access of a channel from its stored JSON text, None = everyone. *strict* raises on a
    malformed value (write); a read treats it as everyone."""
    if value in (None, ""):
        return None
    try:
        raw = json.loads(value) if isinstance(value, str) else None
        access = Access.model_validate(raw)
    except (ValueError, TypeError) as exc:
        if strict:
            raise FlowStoreError(f"acces du canal : {exc}", 422)
        return None
    return None if access.is_everyone() else access


def hidden_channels(project: str, user: str, records: Optional[List[Dict[str, Any]]] = None) -> Set[str]:
    """Channels *user* does not see on *project* (empty for a lead or a supervisor)."""
    from features.roles import project_roles

    if records is None:
        try:
            records = read(project)["records"]
        except (OSError, RuntimeError):
            return set()
    groups = {r["rid"]: r for r in records if r.get("kind") == "group"}
    restricted = {r.get("name"): effective_access(r, groups) for r in records
                  if r.get("kind") == "channel" and r.get("name") and r.get("name") != GENERAL}
    restricted = {n: a for n, a in restricted.items() if a is not None}
    if not restricted:
        return set()
    roles = project_roles.read_roles(project)
    if project_roles.can(project, "team_channels", user=user, roles=roles):
        return set()
    role = project_roles.role_of(project, user, roles)
    return {n for n, a in restricted.items() if not page_for(a, user, role)}
