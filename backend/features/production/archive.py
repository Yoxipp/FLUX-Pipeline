# archive.py — resolve, inspect and ARCHIVE a Production entity's on-disk folder.
#
# Deleting a sequence / shot / asset in the Production Tab must never hard-delete
# data. Instead the entity's folder is MOVED into a per-project archive:
#
#   <project>/ARCHIVE/<YYYY-MM-DD>_<ARTIST>/<original rel path>/…   (2026-09-28)
#
# so it stays recoverable (and versions/syncs with the rest of the project). The
# logical entity is removed from production.json by the caller AFTER a successful
# archive, so the create-only Production→Disk sync cannot recreate the folder from
# a still-present entity.
#
# ── SAFEGUARD CONTRACT ────────────────────────────────────────────────────────
# The only destructive call here is a single shutil.move of a resolved entity
# folder into <project>/ARCHIVE. Guards refuse to move the project root, the
# ARCHIVE dir itself, anything outside the project, or a non-existent path. A
# move is never a delete: the bytes survive under ARCHIVE.

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from core.constants import DEFAULT_CLASS_TOKENS, DEFAULT_TYPE_TOKENS
from core.logger import get_logger
from core.paths import ensure_dir, is_subpath, path_exists_safe
from features.folder_manager.tokens import load_tokens

log = get_logger(__name__)

# Project-level archive root (distinct from CONFIG/archive used for activity logs).
ARCHIVE_ROOT = "ARCHIVE"


def _norm(rel: str) -> str:
    return (rel or "").replace("\\", "/").strip("/")


def resolve_entity_rel(
    project_path: Path,
    kind: str,
    class_token: str = "",
    name: str = "",
    seq: str = "",
    shot: str = "",
) -> str | None:
    """Project-relative folder of a Production entity, or None if unresolvable.

    * asset : NAME token value, else <CLASS token>/<NAME>.
    * seq   : SEQ token value, else shot/<SEQ###>.
    * shot  : SHOT token value (key "SEQ###/SHOT###"), else shot/<SEQ###>/<SHOT###>.
    """
    tokens = load_tokens(project_path)
    class_map = {**DEFAULT_CLASS_TOKENS, **(tokens.get("CLASS") or {})}
    name_map  = tokens.get("NAME") or {}
    seq_map   = tokens.get("SEQ")  or {}
    shot_map  = tokens.get("SHOT") or {}

    if kind == "asset":
        cls  = (class_token or "").upper()
        nm   = (name or "").upper()
        if not nm:
            return None
        rel = name_map.get(nm)
        if rel:
            return _norm(rel)
        class_rel = class_map.get(cls)
        if class_rel and "{" not in class_rel:
            return _norm(f"{class_rel}/{nm}")
        return None

    if kind == "seq":
        sq = (seq or "").upper()
        if not sq:
            return None
        return _norm(seq_map.get(sq) or f"shot/{sq}")

    if kind == "shot":
        sq = (seq or "").upper()
        sh = (shot or "").upper()
        if not sq or not sh:
            return None
        key = f"{sq}/{sh}"
        return _norm(shot_map.get(key) or f"shot/{sq}/{sh}")

    return None


def _safe_entity_dir(project_path: Path, rel: str) -> Path | None:
    """Resolve <project>/<rel> and refuse anything that is not a real, in-project
    subfolder (never the project root, never the ARCHIVE tree)."""
    rel = _norm(rel)
    if not rel:
        return None
    proj = project_path.resolve()
    target = (project_path / rel).resolve()
    if target == proj:
        return None
    if not is_subpath(target, proj):
        return None
    # Never touch the archive tree itself.
    if target == (proj / ARCHIVE_ROOT) or is_subpath(target, proj / ARCHIVE_ROOT):
        return None
    return target


def _count_files(folder: Path) -> int:
    """Recursive file count under *folder* (0 when missing). Best-effort."""
    if not path_exists_safe(folder):
        return 0
    n = 0
    try:
        for p in folder.rglob("*"):
            if p.is_file():
                n += 1
    except OSError:
        pass
    return n


def inspect_folder(project_path: Path, rel: str) -> dict:
    """Return {rel_path, exists, file_count} for an entity folder."""
    target = _safe_entity_dir(project_path, rel)
    if target is None:
        return {"rel_path": _norm(rel), "exists": False, "file_count": 0}
    exists = path_exists_safe(target)
    return {
        "rel_path": _norm(rel),
        "exists": exists,
        "file_count": _count_files(target) if exists else 0,
    }


def archive_label(user: str | None = None, when: datetime | None = None) -> str:
    """Folder name of an archive: the day and the artist who deleted (2026-09-28),
    e.g. ``2026-09-28_ADAM``."""
    if user is None:
        try:
            from core import config
            user = config.get_current_user() or ""
        except Exception:  # noqa: BLE001 - no config: still archive
            user = ""
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", (user or "").strip()).strip("_").upper() or "INCONNU"
    return f"{(when or datetime.now()).strftime('%Y-%m-%d')}_{name}"


def archive_folder(project_path: Path, rel: str, user: str | None = None) -> str:
    """Move <project>/<rel> into <project>/ARCHIVE/<YYYY-MM-DD>_<USER>/<rel>. Return the
    archived project-relative path.

    Raises ValueError when *rel* does not resolve to an in-project entity folder,
    FileNotFoundError when the folder does not exist.
    """
    target = _safe_entity_dir(project_path, rel)
    if target is None:
        raise ValueError(f"Refus d'archiver un chemin hors périmètre : {rel!r}")
    if not path_exists_safe(target):
        raise FileNotFoundError(f"Dossier introuvable : {rel}")

    label = archive_label(user)
    dest = project_path / ARCHIVE_ROOT / label / _norm(rel)
    # The same folder archived twice the same day by the same artist: _2, _3...
    if dest.exists():
        i = 2
        while (project_path / ARCHIVE_ROOT / f"{label}_{i}" / _norm(rel)).exists():
            i += 1
        dest = project_path / ARCHIVE_ROOT / f"{label}_{i}" / _norm(rel)

    ensure_dir(dest.parent)
    shutil.move(str(target), str(dest))
    archived_rel = _norm(str(dest.relative_to(project_path)))
    log.info("Archived %s -> %s", rel, archived_rel)
    return archived_rel


def drop_tokens_under(project_path: Path, rel: str) -> list[str]:
    """Remove the NAME / SEQ / SHOT tokens pointing at *rel* or inside it, after an archive.

    Live 2026-09-19: an archived shot kept its SHOT token, so anything walking the tokens
    (Publisher menus, a later Production save, shot listings) brought it back.
    Returns the removed ``SECTION/value`` keys."""
    from features.folder_manager.tokens import save_tokens

    root = _norm(rel)
    if not root:
        return []
    tokens = load_tokens(project_path)
    removed = []
    for section in ("NAME", "SEQ", "SHOT"):
        entries = tokens.get(section) or {}
        for key in [k for k, v in entries.items()
                    if _norm(str(v)) == root or _norm(str(v)).startswith(root + "/")]:
            del entries[key]
            removed.append(f"{section}/{key}")
    if removed:
        save_tokens(project_path, tokens)
        log.info("Tokens dropped with the archive of %s: %s", root, removed)
    return removed


# ── disk -> logical prune ─────────────────────────────────────────────────────

def prune_absent_auto(project_path: Path, production: dict) -> int:
    """Drop AUTO-origin entities whose on-disk folder no longer exists.

    Deleting a folder in the OS file manager should make its token disappear from
    the logical planning — but ONLY for entities Flux adopted from disk itself
    (``origin == 'auto'``). User-planned entities are never auto-pruned (a transient
    OneDrive/AV hiccup must not wipe someone's planning); those are removed
    explicitly via the Publisher's ghost-token cross instead.

    Mutates *production* in place. Returns the number of entities removed. No-ops
    (returns 0) when the project folder itself is not currently reachable, so a
    mount/sync hiccup can never trigger a purge.
    """
    if not path_exists_safe(project_path):
        return 0

    removed = 0

    # Assets ----------------------------------------------------------------
    kept_assets = []
    for a in production.get("assets", []):
        if (a.get("origin") or "user") == "auto":
            rel = resolve_entity_rel(project_path, "asset", a.get("class", ""), a.get("name", ""))
            if rel and not path_exists_safe((project_path / rel)):
                removed += 1
                continue
        kept_assets.append(a)
    production["assets"] = kept_assets

    # Sequences (+ orphan their shots) --------------------------------------
    kept_seqs = []
    dropped_seq_ids: set[str] = set()
    for s in production.get("sequences", []):
        if (s.get("origin") or "user") == "auto":
            rel = resolve_entity_rel(project_path, "seq", seq=s.get("name", ""))
            if rel and not path_exists_safe((project_path / rel)):
                removed += 1
                dropped_seq_ids.add(s.get("id"))
                continue
        kept_seqs.append(s)
    production["sequences"] = kept_seqs
    live_seq = {s.get("id"): s for s in kept_seqs}

    # Shots ------------------------------------------------------------------
    kept_shots = []
    for sh in production.get("shots", []):
        # A shot whose sequence was dropped is orphaned — remove it too.
        if sh.get("seq_id") in dropped_seq_ids:
            removed += 1
            continue
        if (sh.get("origin") or "user") == "auto":
            seq = live_seq.get(sh.get("seq_id"))
            seq_name = seq.get("name", "") if seq else ""
            rel = resolve_entity_rel(project_path, "shot", seq=seq_name, shot=sh.get("name", ""))
            if seq_name and rel and not path_exists_safe((project_path / rel)):
                removed += 1
                continue
        kept_shots.append(sh)
    production["shots"] = kept_shots

    if removed:
        log.info("Pruned %d auto entit%s absent from disk (%s)",
                 removed, "y" if removed == 1 else "ies", project_path.name)
    return removed


# ── delete a sequence / shot for good (2026-09-27) ─────────────────────────
# Live: a deleted shot came back a few seconds later with its folder. Two paths
# rebuilt it: reconcile re-created the entity from its old publish events (then the
# next save's create-only sync re-created the folder), and a stale client (another
# window, another machine on OneDrive) saved a planning that still held it. The
# delete now records a tombstone in production.json ("archived"): reconcile skips
# the publishes made before it, and a save cannot bring back an archived entity id.
# A shot re-created later by name gets a new id and new publishes, so it lives.

ARCHIVED_KEY = "archived"
# Tombstones kept in production.json (oldest dropped first).
MAX_TOMBSTONES = 500


def _stamp_now() -> str:
    """Same shape as an activity event ``date + ' ' + time`` so they compare as text."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def satellite_rels(project_path: Path, kind: str, seq: str, shot: str = "") -> list[str]:
    """Folders of a sequence / shot living outside ``shot/<SEQ>`` (comp, lighting):
    archived with it, or the disk scan adopts the shot back from them."""
    from core.constants import DEFAULT_SHOT_TYPE_TOKENS

    sq, sh = (seq or "").upper(), (shot or "").upper()
    if not sq or (kind == "shot" and not sh):
        return []
    templates = (load_tokens(project_path) or {}).get("TYPE_SHOT") or DEFAULT_SHOT_TYPE_TOKENS
    own_root = f"shot/{sq}" if kind == "seq" else f"shot/{sq}/{sh}"
    out: list[str] = []
    for tpl in templates.values():
        rel = _norm(str(tpl))
        if kind == "seq":
            # Everything of the sequence: cut the template at {seq}.
            if "{seq}" not in rel:
                continue
            rel = rel[: rel.index("{seq}")] + sq
        else:
            if "{shot}" not in rel:
                continue      # lighting/{seq} is the whole sequence's: kept for a shot
            rel = rel[: rel.index("{shot}")].replace("{seq}", sq) + sh
        rel = _norm(rel)
        if "{" in rel or rel == own_root or rel.startswith(own_root + "/") or rel in out:
            continue
        out.append(rel)
    return out


def remove_entity(production: dict, kind: str, seq: str, shot: str = "", at: str | None = None) -> list[str]:
    """Remove a sequence (with its shots) or a shot from *production* and record the
    tombstone. Returns the removed entity ids."""
    sq, sh = (seq or "").upper(), (shot or "").upper()
    seq_ids = {s.get("id") for s in production.get("sequences", []) if (s.get("name") or "").upper() == sq}
    if kind == "seq":
        removed = set(seq_ids)
        removed |= {s.get("id") for s in production.get("shots", []) if s.get("seq_id") in seq_ids}
        production["sequences"] = [s for s in production.get("sequences", []) if s.get("id") not in removed]
    elif kind == "shot":
        removed = {s.get("id") for s in production.get("shots", [])
                   if s.get("seq_id") in seq_ids and (s.get("name") or "").upper() == sh}
    else:
        return []
    production["shots"] = [s for s in production.get("shots", []) if s.get("id") not in removed]
    tombs = production.setdefault(ARCHIVED_KEY, [])
    tombs.append({"kind": kind, "seq": sq, "shot": sh if kind == "shot" else "",
                  "ids": sorted(i for i in removed if i), "at": at or _stamp_now()})
    del tombs[:-MAX_TOMBSTONES]
    return sorted(i for i in removed if i)


def is_archived(production: dict, seq: str, shot: str, when: str) -> bool:
    """True when a publish of *seq*/*shot* dated *when* ("YYYY-MM-DD HH:MM") was made
    before that shot (or its sequence) was deleted."""
    sq, sh = (seq or "").upper(), (shot or "").upper()
    for t in production.get(ARCHIVED_KEY) or []:
        if t.get("seq") != sq or (t.get("kind") == "shot" and t.get("shot") != sh):
            continue
        if (when or "") <= (t.get("at") or ""):
            return True
    return False


def keep_archived_out(production: dict, previous: dict | None) -> int:
    """Before a save: keep the tombstones of *previous* (a stale client does not know
    them) and drop every entity an archive removed. Returns the entities dropped."""
    tombs = list(production.get(ARCHIVED_KEY) or [])
    seen = {(t.get("kind"), t.get("seq"), t.get("shot"), t.get("at")) for t in tombs}
    for t in (previous or {}).get(ARCHIVED_KEY) or []:
        key = (t.get("kind"), t.get("seq"), t.get("shot"), t.get("at"))
        if key not in seen:
            tombs.append(t)
            seen.add(key)
    tombs.sort(key=lambda t: t.get("at") or "")
    if not tombs:
        return 0
    production[ARCHIVED_KEY] = tombs[-MAX_TOMBSTONES:]
    # A rename (features/production/rename.py): an entity still under its old name in a
    # stale save takes the new one, else the create-only sync rebuilds the old folder.
    for t in tombs:
        ren = t.get("renamed") or {}
        old_name = t.get("shot") if t.get("kind") == "shot" else t.get("seq")
        key = "shots" if t.get("kind") == "shot" else "sequences"
        for e in production.get(key, []):
            if ren.get("id") and e.get("id") == ren["id"] and e.get("name") == old_name:
                e["name"] = ren.get("to") or e["name"]
    dead = {i for t in tombs for i in t.get("ids") or []}
    before = len(production.get("sequences", [])) + len(production.get("shots", []))
    production["sequences"] = [s for s in production.get("sequences", []) if s.get("id") not in dead]
    live_seq = {s.get("id") for s in production["sequences"]}
    production["shots"] = [s for s in production.get("shots", [])
                           if s.get("id") not in dead and s.get("seq_id") in live_seq]
    return before - len(production["sequences"]) - len(production["shots"])


def delete_seq_shot(project_path: Path, production: dict, kind: str, seq: str, shot: str = "") -> dict:
    """Archive the folders of a sequence / shot, drop its tokens and remove it from
    *production* (mutated, the caller saves). Missing folders are skipped."""
    main = resolve_entity_rel(project_path, kind, seq=seq, shot=shot)
    if main is None:
        raise ValueError(f"{kind} introuvable : {seq} {shot}".strip())
    archived, dropped = [], []
    for rel in [main] + satellite_rels(project_path, kind, seq, shot):
        try:
            archived.append(archive_folder(project_path, rel))
        except FileNotFoundError:
            continue
        dropped += drop_tokens_under(project_path, rel)
    ids = remove_entity(production, kind, seq, shot)
    return {"archived": archived, "tokens_dropped": dropped, "removed_ids": ids}
