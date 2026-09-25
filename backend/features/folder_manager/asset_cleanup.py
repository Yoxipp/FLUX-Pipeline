# asset_cleanup.py - bring an asset folder back to the current FLUX layout (2026-09-25:
# "clean tout l'asset OGRE, qu'il n'y ait plus de dossier ou de hierarchie qui ne sont
# plus censes exister").
#
# scan_asset() lists what does not belong to the current layout, apply_cleanup() moves
# the picked items to <project>/_backup_flux/<date>/<same relative path> (never a hard
# delete) and removes the empty folders left behind.
#
# Current layout of an asset (ADR 0017, 0018, 0019):
#   <NAME>/<type folder>/<instance>/<base>_vNNN.ext, <base>_LAST.ext(.link|.flux.json)
#   <NAME>/<type folder>/<instance>/<base>_vNNN/            sequence / UDIM version folder
#   <NAME>/usd/<NAME>_vNNN/, <NAME>/usd/<NAME>_LAST.usda     component (ADR 0018)
# A publish file sits in ONE folder, computed from its own name (resolve_publish_path).
#
# Kinds of findings (default = picked for the move or not):
#   temp          in-flight temp file of a publish that died                  yes
#   old_layout    older layout under the right folder (<ext>/, versions/,
#                 <FMT>/<base>_<FMT>_Vnnn/, <base>_LAST/)                     yes if superseded
#   wrong_place   publish of this asset outside its folder (old hierarchy)    yes if superseded
#   old_map_name  texture instance with an older map name (COL, BASECOLOR)
#                 when the canonical one (BCOL) exists                        yes
#   empty_dir     empty folder                                                yes
# "superseded": the right folder holds a LAST of the same base and format. Anything a
# USD layer of the asset still uses is never picked by default, and files FLUX does not
# recognise (work scenes, references...) are only listed, never moved.

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL
from core.logger import get_logger
from features.folder_manager.naming_validator import get_base_name, parse_filename
from features.folder_manager.tokens import get_path_for_token, load_tokens
from features.publisher import last_pointer as lp

log = get_logger(__name__)

BACKUP_DIR = "_backup_flux"
_USD_EXTS = (".usd", ".usda", ".usdc")
_SEQ_DIR_RE = re.compile(r"^(?P<base>.+)_v\d+$")
_COMPONENT_VER_RE = r"^{name}_v\d+$"
_SIDE_FILES = {"modif_logs.json"}


def _norm(p: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def asset_root(project_path: Path, name: str) -> Path:
    tokens = load_tokens(project_path) or {}
    rel = get_path_for_token(tokens, "NAME", name)
    if rel is None:
        raise ValueError(f"asset inconnu : {name}")
    return project_path / str(rel).replace("\\", "/")


def clone_project(project_path: str | Path, new_name: str) -> dict:
    """Copy the project under *new_name* (next to it), without what the project scan
    picks by default: the clone starts on the current FLUX layout, the original is left
    untouched. The clone gets its own project_id (ADR 0004, 0016)."""
    import json

    from features.folder_manager.naming_validator import format_token
    from features.folder_manager.project_config import default_project_config, project_config_path

    src = Path(project_path)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", new_name.strip())
    if not safe:
        raise ValueError("nom de projet vide")
    dest = src.parent / safe
    if dest.exists():
        raise ValueError(f"le projet {safe} existe deja")
    skip = {_norm(src / i["path"]) for i in scan_project(src)["items"] if i.get("safe")}
    copied, skipped = 0, 0

    def _ignore(folder: str, names: list[str]) -> list[str]:
        nonlocal skipped
        out = []
        for n in names:
            full = _norm(Path(folder) / n)
            if n == BACKUP_DIR or full in skip:
                out.append(n)
                skipped += 1
        return out

    def _copy(s: str, d: str) -> str:
        nonlocal copied
        copied += 1
        return shutil.copy2(s, d)

    shutil.copytree(src, dest, ignore=_ignore, copy_function=_copy)
    cfg_path = project_config_path(dest)
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    except (OSError, ValueError):
        cfg = {}
    cfg["project_id"] = default_project_config()["project_id"]
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _ = format_token  # naming kept aligned with project creation
    log.info("Project %s cloned to %s: %d file(s), %d item(s) left out", src.name, dest.name, copied, skipped)
    return {"project": dest.name, "files": copied, "left_out": skipped}


def asset_of_path(project_path: Path, rel_path: str) -> str | None:
    """NAME token whose folder is *rel_path* (a path relative to the project)."""
    want = _norm(project_path / rel_path.replace("\\", "/"))
    for name, rel in ((load_tokens(project_path) or {}).get("NAME") or {}).items():
        if _norm(project_path / str(rel).replace("\\", "/")) == want:
            return name
    return None


def _expected_dir(project_path: Path, base: str, ext: str) -> Path | None:
    from features.publisher.publish_core import resolve_publish_path

    try:
        return resolve_publish_path(project_path, f"{base}{ext}")
    except Exception:  # noqa: BLE001 - unparseable name: not a FLUX publish
        return None


def _has_current_last(folder: Path, base: str, ext: str) -> bool:
    last = folder / f"{base}_{ACTIVE_VERSION_LABEL}{ext}"
    return last.is_file() or Path(str(last) + lp.LINK_SUFFIX).is_file()


def _identify(path: Path) -> tuple[str, str] | None:
    """(base, ext) of a FLUX publish file, None when the name is not one."""
    stem, ext, _role = lp.parse_published_name(path.name)
    if not ext:
        return None
    # A UDIM / frame tile: "<base>_v003.1001.exr" -> ext ".exr".
    m = re.match(r"^(?P<stem>.+?)\.(\d{4})$", stem)
    if m:
        stem = m.group("stem")
    base = get_base_name(f"{stem}{ext}")
    if not base or parse_filename(f"{base}{ext}") is None:
        return None
    # Only publish products: a version / LAST in the name, or a file inside a version /
    # LAST folder. "<base>.ext" alone is a work file (crowd preview, artist export).
    versioned = stem != base
    in_version_dir = re.search(r"_(LAST|[vV]\d+)$", path.parent.name) is not None
    if not (versioned or in_version_dir):
        return None
    return base, ext


def _used_by_usd(root: Path) -> dict[str, str]:
    """{normalised path: layer} of every file a USD layer of the asset points to
    (sublayers, references, payloads, texture paths). A UDIM pattern marks its folder."""
    used: dict[str, str] = {}
    try:
        from pxr import UsdUtils
    except Exception:  # noqa: BLE001 - no pxr: nothing is marked as used
        return used
    for layer in root.rglob("*"):
        if layer.suffix.lower() not in _USD_EXTS or not layer.is_file() or BACKUP_DIR in layer.parts:
            continue
        try:
            subs, refs, payloads = UsdUtils.ExtractExternalReferences(str(layer))
        except Exception:  # noqa: BLE001 - unreadable layer: skipped
            continue
        for dep in (*subs, *refs, *payloads):
            if not dep or dep.startswith(("$", "@")):
                continue
            target = Path(dep) if os.path.isabs(dep) else layer.parent / dep
            if "<UDIM>" in dep or "<udim>" in dep:
                used.setdefault(_norm(target.parent), layer.name)
            else:
                used.setdefault(_norm(target), layer.name)
    return used


def _canonical_instance(instance: str) -> str | None:
    from dcc.texture_publish import MAP_ALIASES

    low = re.sub(r"[^a-z0-9]", "", instance.lower())
    for token, aliases in MAP_ALIASES.items():
        if low in aliases and low != token.lower():
            return token
    return None


def scan_asset(project_path: str | Path, name: str) -> dict:
    """What in the asset folder does not match the current FLUX layout.

    Returns {"scope", "root", "items": [{"path", "kind", "reason", "files", "bytes",
    "default", "used_by"}], "unknown": [paths]} with paths relative to the project."""
    project = Path(project_path)
    root = asset_root(project, name)
    if not root.is_dir():
        raise ValueError(f"dossier de l'asset introuvable : {root}")
    return _scan(project, root, name=name)


def scan_project(project_path: str | Path) -> dict:
    """Same scan over the whole project (every asset and shot). Empty folders are only
    reported inside asset folders: shots keep an empty department skeleton on purpose
    (addendum ADR 0020)."""
    project = Path(project_path)
    return _scan(project, project, name=None)


def _asset_roots(project: Path) -> list[Path]:
    return [project / str(rel).replace("\\", "/")
            for rel in ((load_tokens(project) or {}).get("NAME") or {}).values()]


def _scan(project: Path, root: Path, name: str | None) -> dict:
    """The rules come from the running FLUX code (resolve_publish_path, the name parser,
    the layout readers, the map table), never from a list of old layouts: a cleaner that
    follows FLUX when its logic changes (2026-09-25)."""
    # Anything of the whole project (shots, assemblies) may point to a file of the asset.
    used = _used_by_usd(project)
    names = [name] if name else list(((load_tokens(project) or {}).get("NAME") or {}).keys())
    component_ver = {n: re.compile(_COMPONENT_VER_RE.format(name=re.escape(n))) for n in names}

    found: dict[Path, dict] = {}       # file -> finding
    unknown: list[Path] = []
    canon_dirs: set[str] = set()
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        rel_parts = f.relative_to(root).parts
        if BACKUP_DIR in rel_parts or any(p.startswith(".") for p in rel_parts):
            continue
        if len(rel_parts) == 1 and root == project:
            continue                   # project files: tokens.json, project.json, production.json
        if lp.is_temp_name(f.name):
            found[f] = {"kind": "temp", "reason": "fichier temporaire d'un publish interrompu", "superseded": True}
            continue
        if f.name in _SIDE_FILES:
            continue
        # Component (ADR 0018): <NAME>/usd/<NAME>_LAST.usda and <NAME>/usd/<NAME>_vNNN/...
        if "usd" in f.parts and any(
                f.name.startswith(f"{n}_{ACTIVE_VERSION_LABEL}") or any(rx.match(p) for p in f.parts)
                for n, rx in component_ver.items()):
            continue
        ident = _identify(f)
        if ident is None:
            unknown.append(f)
            continue
        base, ext = ident
        expected = _expected_dir(project, base, ext)
        parsed = parse_filename(f"{base}{ext}") or {}
        if expected is None or (name and parsed.get("NAME", "").upper() != name.upper()):
            unknown.append(f)
            continue
        here = f.parent
        # Current: flat in its folder, or inside its own <base>_vNNN/ sequence folder.
        if _norm(here) == _norm(expected):
            if not parsed.get("is_shot"):
                canon_dirs.add(_norm(expected))
            continue
        seq = _SEQ_DIR_RE.match(here.name)
        if seq and seq.group("base") == base and _norm(here.parent) == _norm(expected):
            continue
        superseded = _has_current_last(expected, base, ext)
        inside = _norm(here).startswith(_norm(expected) + os.sep)
        found[f] = {
            "kind": "old_layout" if inside else "wrong_place",
            "reason": ("ancien rangement" if inside else "hors de son dossier FLUX ("
                       + _rel(project, expected) + ")")
                      + (" ; une version actuelle existe" if superseded else " ; seule copie, pas de version actuelle"),
            "superseded": superseded,
        }

    # Older map names (COL, BASECOLOR...) next to the canonical one (BCOL).
    for folder in sorted(canon_dirs):
        d = Path(folder)
        canon = _canonical_instance(d.name)
        if canon is None:
            continue
        twin = d.parent / canon.lower()
        if not twin.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if f.is_file() and f not in found:
                found[f] = {"kind": "old_map_name",
                            "reason": f"ancien nom de map : {d.name.upper()} remplace par {canon}",
                            "superseded": True}

    items = _collapse(root, found, used, project)
    _mark_scene_refs(project, items)
    for i in items:
        # Only what is certain can be moved; the rest is a warning (2026-09-25:
        # "le cleaning ne doit jamais casser un projet ou un fichier").
        i["safe"] = bool(i["default"])
        if not i["safe"]:
            i["warning"] = ("utilise par " + i["used_by"]) if i["used_by"] else \
                "garde, a verifier a la main"
    empty_roots = [root] if name else [r for r in _asset_roots(project) if r.is_dir()]
    for er in empty_roots:
        for d in (p for p in er.rglob("*") if p.is_dir() and BACKUP_DIR not in p.parts):
            if not any(True for x in d.rglob("*") if x.is_file()):
                items.append({"path": _rel(project, d), "kind": "empty_dir", "reason": "dossier vide",
                              "files": 0, "bytes": 0, "default": True, "safe": True, "used_by": ""})
    # Keep only the outermost empty folder of a chain.
    empties = [i for i in items if i["kind"] == "empty_dir"]
    for i in empties:
        if any(j is not i and (i["path"] + "/").startswith(j["path"] + "/") for j in empties):
            items.remove(i)
    items.sort(key=lambda i: i["path"].lower())
    return {"scope": name or "", "root": _rel(project, root) if root != project else "", "items": items,
            "unknown": [_rel(project, u) for u in unknown]}


_SCENE_EXTS = (".hip", ".hipnc", ".hiplc", ".ma", ".nk", ".usda", ".json", ".link")
_SCENE_MAX_BYTES = 300 * 1024 * 1024


def _mark_scene_refs(project: Path, items: list[dict]) -> None:
    """A scene (.hip, .ma, .nk), a text USD or a LAST pointer that names an item's path
    (its last two path parts, / or \\) makes it unsafe: moving it could break that scene."""
    needles: dict[int, tuple[str, ...]] = {}
    for n, i in enumerate(items):
        if i["kind"] in ("temp", "empty_dir") or not i["default"]:
            continue
        parts = i["path"].lower().split("/")
        tail = parts[-2:] if len(parts) >= 2 else parts
        needles[n] = ("/".join(tail), "\\".join(tail), "\\\\".join(tail))
    if not needles:
        return
    moving = [project / items[n]["path"] for n in needles]
    for f in project.rglob("*"):
        if f.suffix.lower() not in _SCENE_EXTS or not f.is_file() or BACKUP_DIR in f.parts:
            continue
        if any(f == m or m in f.parents for m in moving):
            continue                   # a file being moved does not protect itself
        try:
            if f.stat().st_size > _SCENE_MAX_BYTES:
                continue
            text = f.read_bytes().decode("utf-8", errors="ignore").lower()
        except OSError:
            continue
        for n, keys in list(needles.items()):
            if any(k in text for k in keys):
                items[n]["default"] = False
                items[n]["used_by"] = _rel(project, f)
                del needles[n]
        if not needles:
            return


def _rel(project: Path, p: Path) -> str:
    return str(p.relative_to(project)).replace("\\", "/")


def _collapse(root: Path, found: dict[Path, dict], used: dict[str, str], project: Path) -> list[dict]:
    """One item per folder whose files are ALL findings of one kind, else per file."""
    def used_by(p: Path) -> str:
        n = _norm(p)
        for key in (n, _norm(p.parent)):
            if key in used:
                return used[key]
        return ""

    items: list[dict] = []
    done: set[Path] = set()
    dirs = sorted({f.parent for f in found}, key=lambda p: len(p.parts))
    for d in dirs:
        if d == root or any(x in done for x in (d, *d.parents)):
            continue
        # climb to the highest folder still made only of findings of one kind
        top = None
        cur = d
        while cur != root:
            files = [f for f in cur.rglob("*") if f.is_file()]
            kinds = {found[f]["kind"] for f in files if f in found}
            if files and all(f in found for f in files) and len(kinds) == 1:
                top = cur
                cur = cur.parent
            else:
                break
        if top is None:
            continue
        files = [f for f in top.rglob("*") if f.is_file()]
        user = next((u for u in (used_by(f) for f in files) if u), "")
        first = found[files[0]]
        superseded = all(found[f]["superseded"] for f in files)
        items.append({"path": _rel(project, top), "kind": first["kind"], "reason": first["reason"],
                      "files": len(files), "bytes": sum(f.stat().st_size for f in files),
                      "default": superseded and not user, "used_by": user, "dir": True})
        done.add(top)
    for f, info in sorted(found.items()):
        if any(x in done for x in f.parents):
            continue
        user = used_by(f)
        items.append({"path": _rel(project, f), "kind": info["kind"], "reason": info["reason"],
                      "files": 1, "bytes": f.stat().st_size,
                      "default": info["superseded"] and not user, "used_by": user})
    return items


def apply_cleanup(project_path: str | Path, name: str | None, paths: list[str]) -> dict:
    """Move the picked *paths* (from scan_asset / scan_project when *name* is None) to
    _backup_flux/<date>/, then remove the empty folders left in the asset(s). Only paths
    the scan proposes are accepted."""
    project = Path(project_path)
    scan = scan_asset(project, name) if name else scan_project(project)
    allowed = {i["path"]: i for i in scan["items"]}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = project / BACKUP_DIR / stamp
    moved: list[str] = []
    errors: list[str] = []
    for rel in paths:
        item = allowed.get(rel)
        if item is None or not item.get("safe"):
            errors.append(f"{rel} : pas sur, garde (avertissement seulement)")
            continue
        src = project / rel
        if not src.exists():
            continue
        if item["kind"] == "empty_dir":
            try:
                shutil.rmtree(src) if not any(p.is_file() for p in src.rglob("*")) else None
                moved.append(rel)
            except OSError as exc:
                errors.append(f"{rel} : {exc}")
            continue
        dest = backup / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            moved.append(rel)
        except OSError as exc:
            errors.append(f"{rel} : {exc}")
    # Folders emptied by the moves (inside the asset folders only).
    for root in ([asset_root(project, name)] if name else _asset_roots(project)):
        if not root.is_dir():
            continue
        for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass
    log.info("Cleanup %s: %d moved to %s, %d error(s)", name or project.name, len(moved), backup, len(errors))
    return {"moved": moved, "errors": errors,
            "backup": _rel(project, backup) if backup.exists() else ""}


def list_backups(project_path: str | Path) -> list[dict]:
    """Cleanups that can be undone: [{"id": <date folder>, "files"}], newest first."""
    root = Path(project_path) / BACKUP_DIR
    if not root.is_dir():
        return []
    out = []
    for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        out.append({"id": d.name, "files": sum(1 for f in d.rglob("*") if f.is_file())})
    return out


def restore_cleanup(project_path: str | Path, backup_id: str) -> dict:
    """Put a cleanup back: every file of _backup_flux/<id>/ returns to its path. A path
    taken since then is left alone (reported), never overwritten."""
    project = Path(project_path)
    if not re.fullmatch(r"[\w-]+", backup_id or ""):
        raise ValueError(f"sauvegarde invalide : {backup_id!r}")
    src = project / BACKUP_DIR / backup_id
    if not src.is_dir():
        raise ValueError(f"sauvegarde introuvable : {backup_id}")
    restored, kept = 0, []
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        dest = project / f.relative_to(src)
        if dest.exists():
            kept.append(_rel(project, dest))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dest))
        restored += 1
    for d in sorted((p for p in src.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        src.rmdir()
    except OSError:
        pass
    return {"restored": restored, "already_there": kept}
