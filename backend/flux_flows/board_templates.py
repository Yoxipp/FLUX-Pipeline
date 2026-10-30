# board_templates.py — board templates shipped with FLUX (ADR 0074): moodboard, retro,
# storyboard, planning. A template is a list of board objects with local keys; inserting
# it creates ordinary records in the viewer's own journal (the front re-points the links
# from keys to the new rids, like a paste). Read only, inside the exe (shipped/boards/).
# ADR 0083: a template may set `locked` / `text_locked` on an object; none does by default
# (2026-10-30), insertion keeps what the YAML says. The shotboard template holds one
# `shotboard` object, a grid read live from Production (sequence rows, shot columns).
#
#   board: 1
#   id: retro
#   label: Retro            label_en: Retrospective
#   description: ...        description_en: ...
#   items:
#     - {key: ok, type: frame, x: 0, y: 0, w: 360, h: 560, text: Ce qui a marche, text_en: Went well, color: green}
#     - {key: l1, type: link, from: a, to: b}

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from flux_flows import locations
from flux_flows.page_data import check_fields
from flux_flows.pages import DataSpec
from flux_flows.store import FlowStoreError

_SPEC = DataSpec(id="board", kind="board")
_META = ("key", "text_en", "label_en")


def templates_dir() -> Path:
    return locations.shipped_dir() / "boards"


def parse_template(data: Any, name: str = "?") -> Dict[str, Any]:
    """A checked template: {id, label, label_en, description, description_en, items}."""
    if not isinstance(data, dict) or data.get("board") != 1 or not isinstance(data.get("items"), list):
        raise FlowStoreError(f"modele de board {name} : 'board: 1' et 'items' attendus", 422)
    keys = set()
    items: List[Dict[str, Any]] = []
    for raw in data["items"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("key"), str) or raw["key"] in keys:
            raise FlowStoreError(f"modele de board {name} : chaque objet a une cle unique (key)", 422)
        keys.add(raw["key"])
        fields = check_fields(_SPEC, {k: v for k, v in raw.items() if k not in _META})
        item = {"key": raw["key"], **fields}
        for k in ("text_en", "label_en"):
            if isinstance(raw.get(k), str):
                item[k] = raw[k]
        items.append(item)
    for item in items:
        if item.get("type") == "link" and not (item.get("from") in keys and item.get("to") in keys):
            raise FlowStoreError(f"modele de board {name} : lien {item['key']} vers une cle inconnue", 422)
    return {"id": str(data.get("id") or name), "label": str(data.get("label") or name),
            "label_en": str(data.get("label_en") or data.get("label") or name),
            "description": str(data.get("description") or ""),
            "description_en": str(data.get("description_en") or data.get("description") or ""), "items": items}


def list_templates() -> List[Dict[str, Any]]:
    folder = templates_dir()
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.yml")):
        out.append(parse_template(yaml.safe_load(path.read_text(encoding="utf-8")), path.stem))
    return out
