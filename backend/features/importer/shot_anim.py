# shot_anim.py — the shot animations a FLUX Anim node can apply (2026-09-18).
#
# A shot animation is the motion of one character, published as
# SEQ_SHOT_ANIM_<NAME> (features/usd_export/departments.is_motion_only) in the shot
# task folder. The LOP "FLUX Anim" HDA lists them by tokens (sequence, shot, task,
# character, version) and references the chosen one onto the character's prim.

from __future__ import annotations

import re
from pathlib import Path

from core.logger import get_logger

log = get_logger("importer.shot_anim")

_VERSION_DIR = re.compile(r"^(?P<base>.+)_(?P<ver>v\d{3,})$")
_USD_EXTS = (".usd", ".usda", ".usdc")


def _shot_roots(project: Path) -> list[Path]:
    """Folders holding the shots: the SEQ token paths (``shot/SEQ001``...)."""
    from features.folder_manager.tokens import load_tokens

    seqs = (load_tokens(project) or {}).get("SEQ", {}) or {}
    roots = {project / Path(str(rel).replace("\\", "/")) for rel in seqs.values()}
    return sorted(r for r in roots if r.is_dir())


def _scan(roots: list[Path], project: Path, accept) -> list[dict]:
    """Published motion-only animations under *roots*: one item per base, with its
    LAST pointer and its versions. *accept(base, contrib)* -> the item fields, or None."""
    found: dict[str, dict] = {}
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix.lower() not in _USD_EXTS or ".proxy." in path.name:
                continue
            stem = path.stem
            if stem.endswith("_LAST"):
                base, version = stem[:-5], None
            else:
                m = _VERSION_DIR.match(path.parent.name)
                if not m or stem != m.group("base"):
                    continue
                base, version = m.group("base"), m.group("ver")
            if base not in found:
                fields = accept(base)
                if fields is None:
                    found[base] = {}
                    continue
                found[base] = {**fields, "base": base, "last": "", "versions": {}}
            item = found[base]
            if not item:
                continue
            if version is None:
                item["last"] = str(path)
            else:
                item["versions"][version] = str(path)
    items = [i for i in found.values() if i]
    for item in items:
        item["versions"] = dict(sorted(item["versions"].items()))
    return items


def list_shot_anims(project_path: str | Path) -> list[dict]:
    """Every published shot animation of the project.

    Returns [{"seq", "shot", "task", "character", "name", "base", "last",
    "versions": {"vNNN": root file}}], sorted by seq / shot / character.
    ``name`` is the character's NAME token (DINGO for DINGO_02), ``last`` the LAST
    pointer file ("" when only versions exist).
    """
    from features.folder_manager.naming_validator import parse_filename
    from features.usd_export.departments import character_name, contribution, is_motion_only

    project = Path(project_path)

    def _accept(base: str):
        contrib = contribution(base)
        if not is_motion_only(contrib) or contrib["kind"] != "shot" or not contrib["name"]:
            return None
        parsed = parse_filename(f"{base}.usd") or {}
        return {"kind": "shot", "seq": parsed.get("SEQ", ""), "shot": parsed.get("SHOT", ""),
                "task": contrib["type"], "character": contrib["name"] or "",
                "name": character_name(contrib, project)}

    items = _scan(_shot_roots(project), project, _accept)
    return sorted(items, key=lambda i: (i["seq"], i["shot"], i["character"]))


def list_asset_clips(project_path: str | Path) -> list[dict]:
    """Every published asset animation clip (CLASS_ANIM_NAME_CLIP, ADR 0019 A6).

    Returns [{"kind": "clip", "class", "name", "character", "clip", "base", "last",
    "versions"}], sorted by name / clip. ``character`` = ``name`` (the asset).
    """
    from features.folder_manager.tokens import load_tokens
    from features.usd_export.departments import contribution

    project = Path(project_path)
    tokens = load_tokens(project) or {}
    roots = sorted({project / Path(str(rel).replace("\\", "/")) for rel in (tokens.get("NAME") or {}).values()})

    def _accept(base: str):
        contrib = contribution(base)
        if not contrib or contrib["kind"] != "clip" or not contrib.get("name"):
            return None
        return {"kind": "clip", "class": base.split("_", 1)[0], "name": contrib["name"],
                "character": contrib["name"], "clip": contrib.get("instance") or "null"}

    items = _scan([r for r in roots if r.is_dir()], project, _accept)
    return sorted(items, key=lambda i: (i["name"], i["clip"]))
