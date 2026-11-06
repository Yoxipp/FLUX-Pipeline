# alias_views.py - read-side views of stored documents with renamed artists resolved.
#
# Stored documents are never rewritten on rename (see aliases.py). These helpers return
# a NEW document with every stored artist name mapped to the current name, so cached /
# saved objects stay untouched.

from __future__ import annotations

import copy

from features.accounts.aliases import load_aliases, resolve_user


def _names(value, aliases: dict[str, str]):
    """Resolve a comma-separated list of names ("A, B"), keeping the ", " join."""
    if not isinstance(value, str) or not value.strip():
        return value
    parts = [p.strip() for p in value.split(",")]
    if all(resolve_user(p, aliases) == p for p in parts):
        return value                      # nothing renamed: keep the stored text as is
    return ", ".join(str(resolve_user(p, aliases)) for p in parts if p)


def _resolve_field(obj, key: str, aliases: dict[str, str]) -> None:
    if isinstance(obj, dict) and isinstance(obj.get(key), str):
        obj[key] = resolve_user(obj[key], aliases)


def resolve_production_doc(doc, aliases: dict[str, str] | None = None):
    """Deep copy of a production document with artist names resolved.

    Covers task_details[*].assignee, comments[].author, retakes[].author and
    entity.locked.by on every shot and asset.
    """
    table = load_aliases() if aliases is None else aliases
    out = copy.deepcopy(doc)
    if not table or not isinstance(out, dict):
        return out
    for key in ("shots", "assets"):
        for entity in out.get(key) or []:
            if not isinstance(entity, dict):
                continue
            _resolve_field(entity.get("locked"), "by", table)
            for detail in (entity.get("task_details") or {}).values():
                if not isinstance(detail, dict):
                    continue
                if "assignee" in detail:
                    detail["assignee"] = _names(detail["assignee"], table)
                for sub in ("comments", "retakes"):
                    for item in detail.get(sub) or []:
                        _resolve_field(item, "author", table)
    for retake in out.get("retakes") or []:
        _resolve_field(retake, "author", table)
    return out


def resolve_calendar_items(items, aliases: dict[str, str] | None = None) -> list:
    """Copy of calendar items with owner / created_by / history[].by resolved."""
    table = load_aliases() if aliases is None else aliases
    out = copy.deepcopy(items)
    if not table:
        return out
    for item in out:
        if not isinstance(item, dict):
            continue
        _resolve_field(item, "owner", table)
        _resolve_field(item, "created_by", table)
        for entry in item.get("history") or []:
            _resolve_field(entry, "by", table)
    return out


def alias_etag(etag: str | None) -> str | None:
    """*etag* extended with the alias table's stat, so a rename invalidates a 304."""
    from core.json_manager import sig_token, stat_sig
    from features.accounts.aliases import aliases_path

    if not etag:
        return etag
    try:
        token = sig_token(stat_sig(aliases_path()))
    except RuntimeError:
        token = None
    if not token:
        return etag
    if etag.endswith('"'):
        return f'{etag[:-1]}-a{token}"'
    return f"{etag}-a{token}"
