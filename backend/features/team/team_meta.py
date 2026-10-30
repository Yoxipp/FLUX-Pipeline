# team_meta.py — what the Team page adds around the existing team chat (ADR 0077):
# channels (a lead creates / archives them, each with an optional call link), reactions on
# a message (one record per author) and pinned messages (a lead pins). Zero server: the
# same per author journals as the board (flux_flows/page_data.py), in
#   DOSSIER_PROJETS/<project>/_flux_setup/team/<AUTHOR>.jsonl
# The messages themselves stay in the team chat (features/activity/chat_manager.py).

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from flux_flows import page_data
from flux_flows.pages import DataSpec
from flux_flows.store import FlowStoreError

GENERAL = "general"
EMOJIS = ("like", "love", "laugh", "question", "check")
CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_LINK = 500

SPEC = DataSpec.model_validate({
    "id": "team",
    "fields": [
        {"id": "kind", "type": "select", "required": True,
         "options": [{"value": "channel"}, {"value": "reaction"}, {"value": "pin"}]},
        {"id": "name", "type": "str"},           # channel slug
        {"id": "topic", "type": "text"},         # channel description
        {"id": "call_link", "type": "str"},      # https link of the channel's call (Discord, Teams, Meet, Jitsi)
        {"id": "archived", "type": "bool"},
        {"id": "target", "type": "str"},         # message id (reaction, pin)
        {"id": "emoji", "type": "select", "options": [{"value": e} for e in EMOJIS]},
    ],
})
LEAD_KINDS = ("channel", "pin")


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
        name = fields.get("name")
        if kind == "channel" and op.get("rid") is None:
            if not isinstance(name, str) or not CHANNEL_RE.match(name):
                raise FlowStoreError("canal : minuscules, chiffres, - ou _ (32 max)", 422)
            if any(r.get("kind") == "channel" and r.get("name") == name for r in records.values()):
                raise FlowStoreError(f"le canal #{name} existe deja", 409)
        if kind in ("reaction", "pin") and op.get("rid") is None and not fields.get("target"):
            raise FlowStoreError(f"{kind} : message cible manquant", 422)
    return str(kind or "")


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
