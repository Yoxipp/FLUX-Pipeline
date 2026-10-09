"""
FLUX Work RENDER <-> Production Timeline (2026-10-10, ADR 0051 addendum).

The render Work holds one block per shot (FLUX_RENDER_SHOTnnn: shot + frame range, the
range edited on FLUX Render). Each saved version keeps its blocks in its manifest
(``render_blocks``): that is the common base of a three-way compare

    scene (Houdini now)   base (manifest of the loaded version)   Production (Timeline)

* scene changed, Production not          -> push    (Save writes Production)
* Production changed, scene not          -> pull    (the scene takes the Timeline)
* both changed to different values       -> conflict (the artist chooses, shot by shot)
* shot of a block unknown to Production  -> create  (Save creates it, after confirmation)
* shot of the sequence without a block   -> missing (opening adds a block)

A block without a valid range (end < start: FLUX Shot Import not resolved) never
pushes. A version saved before this existed has no base: Production wins (pull).
Pure functions, no IO: the router loads / saves production.json.
"""

from __future__ import annotations

from features.production import production_store as store


def _range(value) -> tuple[int, int] | None:
    try:
        start, end = int(value[0]), int(value[1])
    except (TypeError, ValueError, IndexError):
        return None
    return (start, end) if end >= start else None


def production_ranges(production: dict, seq: str) -> dict[str, tuple[int, int] | None]:
    """{SHOT: (start, end) | None} of the sequence's shots, Timeline order."""
    seq_entry = store.find_sequence(production, seq)
    if seq_entry is None:
        return {}
    shots = sorted((s for s in production.get("shots", []) if s.get("seq_id") == seq_entry.get("id")),
                   key=lambda s: (s.get("order", 0), s.get("name", "")))
    return {str(s.get("name", "")).upper(): _range((s.get("frame_start"), s.get("frame_end")))
            for s in shots}


def plan(blocks: list[dict], base_blocks: list[dict] | None, production: dict, seq: str) -> dict:
    """What a Save (or an opening) must do. *blocks* / *base_blocks*: [{block, shot, range}]."""
    prod = production_ranges(production, seq)
    base = {str(b.get("shot", "")).upper(): _range(b.get("range")) for b in (base_blocks or [])
            if b.get("shot")}
    has_base = base_blocks is not None
    out = {"push": [], "pull": [], "conflicts": [], "create": [], "missing": []}
    seen = set()
    for block in blocks:
        shot = str(block.get("shot") or "").upper()
        if not shot:
            continue
        seen.add(shot)
        scene = _range(block.get("range"))
        if shot not in prod:
            if scene is not None:
                out["create"].append({"block": block.get("block"), "shot": shot, "range": list(scene)})
            continue
        current = prod[shot]
        if scene == current:
            continue
        if not has_base:
            if current is not None:
                out["pull"].append({"block": block.get("block"), "shot": shot, "range": list(current)})
            continue
        before = base.get(shot)
        scene_changed = scene is not None and scene != before
        prod_changed = current != before
        if scene_changed and not prod_changed:
            out["push"].append({"block": block.get("block"), "shot": shot, "range": list(scene)})
        elif prod_changed and not scene_changed:
            if current is not None:
                out["pull"].append({"block": block.get("block"), "shot": shot, "range": list(current)})
        elif scene_changed and prod_changed:
            out["conflicts"].append({"block": block.get("block"), "shot": shot, "houdini": list(scene),
                                     "flux": list(current) if current else None})
    for shot, rng in prod.items():
        if shot not in seen:
            out["missing"].append({"shot": shot, "range": list(rng) if rng else None})
    return out


def apply(production: dict, seq: str, push: list[dict], create: list[dict]) -> dict:
    """Write *push* ranges and *create* shots into *production* (in place). Returns
    {"updated": [...], "created": [...], "locked": [...]}: a locked shot is never changed."""
    seq_entry = store.find_sequence(production, seq)
    if seq_entry is None:
        raise ValueError(f"Sequence inconnue dans Production : {seq}")
    done = {"updated": [], "created": [], "locked": []}
    for item in push:
        shot = store.find_shot(production, seq_entry["id"], item["shot"])
        rng = _range(item.get("range"))
        if shot is None or rng is None:
            continue
        if shot.get("locked") or seq_entry.get("locked"):
            done["locked"].append(shot["name"])
            continue
        shot["frame_start"], shot["frame_end"] = rng
        done["updated"].append(shot["name"])
    for item in create:
        rng = _range(item.get("range"))
        name = str(item.get("shot") or "").upper()
        if not name or rng is None or store.find_shot(production, seq_entry["id"], name) is not None:
            continue
        if seq_entry.get("locked"):
            done["locked"].append(name)
            continue
        shot = store.add_shot(production, seq_entry["id"], name, origin="houdini")
        shot["frame_start"], shot["frame_end"] = rng
        done["created"].append(name)
    return done
