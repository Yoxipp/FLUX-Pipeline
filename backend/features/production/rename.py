# rename.py — rename a sequence / shot in Production AND on disk (2026-09-27).
#
# Renaming used to change production.json only: the folder kept its old name, the
# create-only sync made a second, empty folder under the new name.
#
# SAFETY CONTRACT
# * Only an entity WITHOUT artist files is renamed. Publishes carry the name in their
#   file names and in the USD paths they reference (LAST pointers, stages): renaming
#   them would break every reference. Such an entity is refused with the files found.
# * FLUX-generated content (``<shot>/usd/``, ``<SEQ>/usd/``: stages, light templates,
#   logs) is regenerated under the new name; the old folder goes to ARCHIVE (never a
#   delete). The empty department / sub-task folders are recreated as they were.
# * A sequence keeps its render scene (``<SEQ>_render.hip`` + backups), renamed: the
#   artist's lighting work is not regenerated. Its FLUX nodes still name the old
#   sequence (reported).
# * A tombstone on the old name (no ids) keeps reconcile from re-creating it from old
#   activity events.

from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.logger import get_logger
from core.paths import ensure_dir, path_exists_safe
from features.production.archive import (
    ARCHIVED_KEY, MAX_TOMBSTONES, _norm, _stamp_now, archive_folder, drop_tokens_under,
    resolve_entity_rel, satellite_rels,
)

log = get_logger(__name__)

GENERATED_DIR = "usd"
_SEQ_RE = re.compile(r"^SEQ\d+$")
_SHOT_RE = re.compile(r"^SHOT\d+$")


def _artist_files(root: Path, generated: set[Path]) -> list[Path]:
    """Files under *root* that FLUX did not generate (outside the *generated* dirs)."""
    if not path_exists_safe(root):
        return []
    out = []
    for f in root.rglob("*"):
        if f.is_file() and not any(g == f or g in f.parents for g in generated):
            out.append(f)
    return out


def _dirs_of(root: Path, skip: set[Path]) -> list[str]:
    """Relative folders under *root* (not inside *skip*), to recreate after the rename."""
    if not path_exists_safe(root):
        return []
    return sorted(str(d.relative_to(root)).replace("\\", "/") for d in root.rglob("*")
                  if d.is_dir() and not any(s == d or s in d.parents for s in skip))


def _tombstone(production: dict, kind: str, seq: str, shot: str, entity_id: str, new: str) -> None:
    """Old name tombstone (no ids: nothing dropped). ``renamed`` lets a stale save that
    still holds the old name be corrected (archive.keep_archived_out)."""
    tombs = production.setdefault(ARCHIVED_KEY, [])
    tombs.append({"kind": kind, "seq": seq, "shot": shot, "ids": [], "at": _stamp_now(),
                  "renamed": {"id": entity_id, "to": new}})
    del tombs[:-MAX_TOMBSTONES]


def blockers(project_path: Path, kind: str, seq: str, shot: str = "") -> list[str]:
    """Artist files that forbid the rename (project-relative), empty when it is safe."""
    project_path = Path(project_path)
    main = resolve_entity_rel(project_path, kind, seq=seq, shot=shot)
    if main is None:
        return []
    root = project_path / main
    generated = {root / GENERATED_DIR}
    if kind == "seq" and path_exists_safe(root):
        generated |= {d / GENERATED_DIR for d in root.iterdir() if d.is_dir()}
    files = _artist_files(root, generated)
    for rel in satellite_rels(project_path, kind, seq, shot):
        files += _artist_files(project_path / rel, set())
    return [str(f.relative_to(project_path)).replace("\\", "/") for f in files]


def _check(production: dict, kind: str, seq: str, shot: str, new: str) -> dict:
    seqs = {s.get("name"): s for s in production.get("sequences", [])}
    entry = seqs.get(seq)
    if entry is None:
        raise ValueError(f"Sequence inconnue : {seq}")
    if kind == "seq":
        if not _SEQ_RE.match(new):
            raise ValueError(f"Nom de sequence invalide : {new}")
        if new in seqs:
            raise ValueError(f"{new} existe deja")
        return entry
    if not _SHOT_RE.match(new):
        raise ValueError(f"Nom de shot invalide : {new}")
    shots = [s for s in production.get("shots", []) if s.get("seq_id") == entry.get("id")]
    if any(s.get("name") == new for s in shots):
        raise ValueError(f"{new} existe deja dans {seq}")
    target = next((s for s in shots if s.get("name") == shot), None)
    if target is None:
        raise ValueError(f"Shot inconnu : {seq} {shot}")
    return target


def rename_in_production(production: dict, kind: str, seq: str, shot: str, new: str) -> None:
    """Rename the entity in *production* (mutated) and tombstone the old name."""
    seq, shot, new = seq.upper(), (shot or "").upper(), new.upper()
    entity = _check(production, kind, seq, shot, new)
    entity["name"] = new
    _tombstone(production, kind, seq, shot if kind == "shot" else "", entity.get("id", ""), new)


def _move_satellites(project_path: Path, kind: str, seq: str, shot: str, new: str) -> None:
    """comp / lighting folders (empty of files, checked before): renamed like the entity."""
    new_seq, new_shot = (new, "") if kind == "seq" else (seq, new)
    olds = satellite_rels(project_path, kind, seq, shot)
    news = satellite_rels(project_path, kind, new_seq, new_shot)
    for old, dst in zip(olds, news):
        src, target = project_path / old, project_path / dst
        if path_exists_safe(src) and not path_exists_safe(target):
            ensure_dir(target.parent)
            shutil.move(str(src), str(target))


def rename_on_disk(project_path: Path, kind: str, seq: str, shot: str, new: str) -> dict:
    """Disk half, after production.json holds the new name. Returns {"archived", "warnings"}."""
    from features.folder_manager.seq_shot_creator import create_shot, ensure_shot_base
    from features.folder_manager.tokens import add_token

    project_path = Path(project_path)
    seq, shot, new = seq.upper(), (shot or "").upper(), new.upper()
    warnings: list[str] = []
    main = resolve_entity_rel(project_path, kind, seq=seq, shot=shot)
    root = project_path / main if main else None
    archived = ""

    if kind == "shot":
        dirs = _dirs_of(root, {root / GENERATED_DIR}) if root is not None else []
        if root is not None and path_exists_safe(root):
            archived = archive_folder(project_path, main)
            drop_tokens_under(project_path, main)
        _move_satellites(project_path, kind, seq, shot, new)
        seq_num, shot_num = int(seq[3:]), int(new[4:])
        new_path = create_shot(project_path, seq_num, shot_num)
        for d in dirs:
            ensure_dir(new_path / d)
        return {"archived": archived, "path": str(new_path), "warnings": warnings}

    # Sequence: every shot is rebuilt under the new sequence; the render scene is kept.
    from features.folder_manager.houdini_render_scene import find_render_scene, render_scene_base

    shots = []
    if root is not None and path_exists_safe(root):
        for d in sorted(p for p in root.iterdir() if p.is_dir() and _SHOT_RE.match(p.name.upper())):
            shots.append((d.name.upper(), _dirs_of(d, {d / GENERATED_DIR})))
    render_old = find_render_scene(project_path, seq)
    render_old = render_old.with_suffix("") if render_old else render_scene_base(project_path, seq)
    keep = [f for f in (render_old.parent.glob(render_old.name + ".*") if render_old.parent.exists() else [])
            if f.is_file()]
    backup = render_old.parent / "backup"
    if root is not None and path_exists_safe(root):
        archived = archive_folder(project_path, main)
        drop_tokens_under(project_path, main)
    _move_satellites(project_path, kind, seq, shot, new)

    new_root = project_path / "shot" / new
    ensure_dir(new_root)
    add_token(project_path, "SEQ", new, f"shot/{new}")
    # The render scene (lighting work) comes back from the archive under the new name.
    render_new = render_scene_base(project_path, new)
    arch_lighting = project_path / archived / render_old.parent.relative_to(root) if archived else None
    for f in keep:
        src = arch_lighting / f.name if arch_lighting else f
        if path_exists_safe(src):
            ensure_dir(render_new.parent)
            shutil.copy2(src, render_new.parent / f.name.replace(seq, new, 1))
    if arch_lighting is not None and path_exists_safe(arch_lighting / backup.name):
        for f in (arch_lighting / backup.name).iterdir():
            if f.is_file():
                ensure_dir(render_new.parent / "backup")
                shutil.copy2(f, render_new.parent / "backup" / f.name.replace(seq, new, 1))
    if not keep:
        from features.folder_manager.houdini_render_scene import create_sequence_render_scene_async
        create_sequence_render_scene_async(project_path, new)
    else:
        warnings.append(f"scene de rendu gardee ({render_new.name}) : ses FLUX Shot Import / FLUX Sequence / "
                        f"FLUX Render nomment encore {seq}, change la sequence dans leurs parametres")
    for shot_name, dirs in shots:
        new_path = create_shot(project_path, int(new[3:]), int(shot_name[4:]))
        for d in dirs:
            ensure_dir(new_path / d)
        ensure_shot_base(project_path, new, shot_name)
    return {"archived": archived, "path": str(new_root), "warnings": warnings}
