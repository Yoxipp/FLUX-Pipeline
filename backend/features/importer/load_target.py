# load_target.py — what "Ouvrir dans Maya / Houdini" loads for a USD file (V4, ADR 0019 points 5 and 7).
#
# An artist opens what the pipeline really loads: the asset (component), the decor, or
# the shot stage, not one department layer nor an old flat file. The department layer
# stays available as a second choice ("couche seule"). Old flat files of the removed
# Constructor (usd/assembly/<X>.usda, kind component or no kind) are "ancien": never
# proposed; they can be deleted, a copy goes to the project backup folder first.

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from core.logger import get_logger

log = get_logger("importer.load_target")

USD_EXTS = (".usd", ".usda", ".usdc", ".usdz")
BACKUP_DIR = "_backup_flux"
_VERSION_DIR = re.compile(r"^(?P<base>.+)_(?P<ver>v\d{3,})$")


def _rel(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def _kind(path: Path) -> str:
    from features.usd_assembler.assembly_v2 import _kind_of

    try:
        return _kind_of(path)
    except Exception:           # noqa: BLE001 - unreadable = no kind
        return ""


def is_legacy_file(project_path: str | Path, file: str | Path) -> bool:
    """A flat Constructor file right under ``usd/assembly/`` that is not a decor
    (kind component or no kind). Legacy decors (kind assembly) are still read."""
    from features.usd_assembler.assembly_v2 import assembly_root

    path = Path(file)
    if path.suffix.lower() not in USD_EXTS or not path.is_file():
        return False
    if path.parent.resolve() != assembly_root(project_path).resolve():
        return False
    return _kind(path) != "assembly"


def legacy_files(project_path: str | Path) -> list[Path]:
    from features.usd_assembler.assembly_v2 import assembly_root

    root = assembly_root(project_path)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if is_legacy_file(project_path, p))


def _publish_base(path: Path) -> tuple[str, str | None]:
    """(publish base, vNNN or None) of a published file: ``X_LAST.usd`` -> (X, None),
    ``X_v003/X.usd`` or ``X_v003/X_model.usda`` -> (X, v003), ``X_v003.usd`` -> (X, v003)."""
    from features.publisher.last_pointer import parse_published_name

    stem, _ext, _role = parse_published_name(path.name)
    stem = stem.removesuffix(".proxy")
    m = _VERSION_DIR.match(path.parent.name)
    if m and stem.startswith(m.group("base")):
        return m.group("base"), m.group("ver")
    if stem.endswith("_LAST"):
        return stem[:-5], None
    m = _VERSION_DIR.match(stem)
    if m:
        return m.group("base"), m.group("ver")
    return stem, None


def _component_version_for(parent: Path, name: str, dept: str, version: str) -> str | None:
    """Most recent component version whose *dept* slot uses publish *version*."""
    from features.usd_assembler.component_auto import COMPONENT_EXT, _entry_flux

    rx = re.compile(rf"^{re.escape(name)}_(v\d+)$")
    found = []
    for d in parent.iterdir() if parent.is_dir() else []:
        m = rx.match(d.name)
        entry = d / f"{name}{COMPONENT_EXT}"
        if not m or not entry.is_file():
            continue
        slot = ((_entry_flux(entry).get("slots") or {}).get(dept) or {})
        if slot.get("version") == version:
            found.append(m.group(1))
    return max(found, key=lambda v: int(v[1:])) if found else None


def load_targets(project_path: str | Path, file: str | Path) -> dict:
    """What to load for *file*.

    {"what": "asset" | "decor" | "shot" | "layer" | "file", "legacy": bool, "message": str,
     "targets": [{"label", "rel_path", "primary", "what"}]} (primary first). The file itself
    is always the last target, except for an old file (never proposed).
    """
    from features.usd_assembler import shot_stage as ss
    from features.usd_assembler.component_auto import COMPONENT_EXT, component_dir
    from features.usd_export.departments import contribution

    project = Path(project_path)
    path = Path(file)
    if not path.is_absolute():
        path = project / path
    self_target = {"label": "Couche seule", "rel_path": _rel(project, path), "primary": False, "what": "layer"}
    out: dict = {"what": "file", "legacy": False, "message": "", "targets": []}
    if path.suffix.lower() not in USD_EXTS:
        out["targets"] = [{**self_target, "label": path.name, "primary": True, "what": "file"}]
        return out

    legacy = is_legacy_file(project, path)
    base, version = _publish_base(path)
    contrib = contribution(base) if base else None

    # 1. entries: a component / decor / shot stage is already what the pipeline loads.
    kind = _kind(path)
    if not legacy and not kind and path.stem.endswith("_LAST"):
        # <NAME>_LAST.usda is a pointer layer (no prim of its own): read the version it targets.
        from features.usd_assembler.assembly_v2 import _entry_in

        owner = component_dir(project, base)
        if owner is not None and owner.resolve() == path.parent.resolve():
            kind = _kind(_entry_in(owner, base))
    if not legacy and kind in ("component", "assembly"):
        out.update(what="decor" if kind == "assembly" else "asset")
        out["targets"] = [{**self_target, "label": path.name, "primary": True, "what": out["what"]}]
        return out
    try:
        from features.importer.library_import import _shot_of_file

        shot = _shot_of_file(project, Path(str(path.resolve())))
    except Exception:           # noqa: BLE001
        shot = None
    if shot:
        out["what"] = "shot"
        out["targets"] = [{**self_target, "label": f"Shot {shot[0]} {shot[1]}", "primary": True, "what": "shot"}]
        return out

    targets: list[dict] = []
    # 2. an asset department publish (or an old file named like one) -> the asset.
    name = ""
    if contrib and contrib["kind"] in ("asset", "clip") and contrib.get("name"):
        name = contrib["name"]
    if name and contrib["kind"] == "asset":
        parent = component_dir(project, name)
        last = parent / f"{name}_LAST{COMPONENT_EXT}" if parent is not None else None
        if last is not None and last.is_file():
            asset_file, asset_label = last, f"Asset {name} (LAST)"
            if version and contrib.get("department"):
                cver = _component_version_for(parent, name, contrib["department"], version)
                if cver:
                    asset_file = parent / f"{name}_{cver}" / f"{name}{COMPONENT_EXT}"
                    asset_label = f"Asset {name} {cver} (avec {contrib['department']} {version})"
            what = "decor" if _kind(last) == "assembly" else "asset"
            targets.append({"label": asset_label, "rel_path": _rel(project, asset_file),
                            "primary": True, "what": what})
            out["what"] = "layer"
    # 3. a shot department publish -> the shot stage.
    elif contrib and contrib["kind"] == "shot":
        from features.folder_manager.naming_validator import parse_filename

        parsed = parse_filename(f"{base}.usd") or {}
        seq, shot_name = parsed.get("SEQ"), parsed.get("SHOT")
        if seq and shot_name:
            last = ss.last_file(project, seq, shot_name)
            if last.is_file():
                targets.append({"label": f"Shot {seq} {shot_name} (LAST)", "rel_path": _rel(project, last),
                                "primary": True, "what": "shot"})
                out["what"] = "layer"

    if legacy:
        out["legacy"] = True
        out["message"] = ("Ancien fichier du Constructeur : il n'est plus propose a l'import"
                          + (f", ouvre l'asset {name} a la place" if targets else "")
                          + ". Tu peux le supprimer (une copie est gardee dans le dossier de backup).")
        out["targets"] = targets
        return out
    if targets:
        out["targets"] = targets + [self_target]
    else:
        out["targets"] = [{**self_target, "label": path.name, "primary": True, "what": "file"}]
    return out


def delete_legacy_file(project_path: str | Path, file: str | Path, *, user: str = "") -> Path:
    """Move an old Constructor file (and its ``.proxy.usda``) into
    ``<project>/_backup_flux/<date>/`` (same relative path). Returns the backup path.
    ValueError when *file* is not an old file."""
    project = Path(project_path)
    path = Path(file)
    if not path.is_absolute():
        path = project / path
    if not is_legacy_file(project, path):
        raise ValueError(f"{path.name} n'est pas un ancien fichier du Constructeur : rien supprime")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = project / BACKUP_DIR / stamp
    victims = [path]
    proxy = path.with_suffix(".proxy.usda")
    if proxy != path and proxy.is_file():
        victims.append(proxy)
    moved = None
    for victim in victims:
        dest = backup_root / _rel(project, victim)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(victim), str(dest))
        moved = moved or dest
    log.info("Old USD file %s moved to %s (%s)", path.name, backup_root, user or "flux")
    return moved
