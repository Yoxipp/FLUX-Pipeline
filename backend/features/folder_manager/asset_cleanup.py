# asset_cleanup.py - put an asset / a project back on the current FLUX layout (ADR 0033).
#
# 2026-09-25: "clean tout l'asset OGRE", "ca doit les remettre au bon endroit",
# "le cleaning ne doit jamais casser un projet ou un fichier ; s'il n'est pas sur, un
# warning", "il ne faut pas que ce cleaner devienne obsolete".
#
# The rules come from the running FLUX code, never from a list of old layouts: for each
# publish product it asks resolve_publish_path where it belongs and the name parser what
# it is, so the cleaner follows FLUX when its logic changes.
#
# Operations (one per file, grouped by folder for the UI):
#   move      a publish outside its folder or in an older layout goes to its folder, under
#             its current name (<base>_vNNN.ext / <base>_LAST.ext), when that place is free
#   drop_dup  the place is taken by an IDENTICAL file: the old copy is a duplicate
#   drop_tmp  in-flight temp file of a publish that died
#   rm_empty  empty folder inside an asset
# Everything else is a warning and never touched: place taken by a different file, a
# path a scene / a USD layer names, relative USD references that would not follow, a
# .link pointer, multi-file old folders. Work files (no version / LAST) are listed only.
# Each run writes a journal (<project>/.flux_cleanup/<date>.json): "Annuler" moves the
# files back and copies each dropped duplicate back from its identical twin.

from __future__ import annotations

import hashlib
import json
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
from core.project_setup import is_setup_rel

log = get_logger(__name__)

JOURNAL_DIR = ".flux_cleanup"
_SKIP_DIRS = {JOURNAL_DIR, "_backup_flux"}
_USD_EXTS = (".usd", ".usda", ".usdc")
_SEQ_DIR_RE = re.compile(r"^(?P<base>.+)_v(?P<n>\d+)$")                  # <base>_vNNN/ (current)
_NESTED_RE = re.compile(r"^(?P<base>.+)_(?P<fmt>[A-Za-z0-9]+)_(?P<label>LAST|V\d+)$")
_LABEL_RE = re.compile(r"_(LAST|[vV]\d+)$")
_SIDE_FILES = {"modif_logs.json"}
_SCENE_EXTS = (".hip", ".hipnc", ".hiplc", ".ma", ".nk", ".usda", ".json", ".link")
_SCENE_MAX_BYTES = 300 * 1024 * 1024

KIND_REASON = {
    "wrong_place": "hors de son dossier FLUX",
    "old_layout": "ancien rangement",
    "old_map_name": "ancien nom de map",
    "temp": "fichier temporaire d'un publish interrompu",
    "empty_dir": "dossier vide",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _norm(p: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _rel(project: Path, p: Path) -> str:
    return str(p.relative_to(project)).replace("\\", "/")


def asset_root(project_path: Path, name: str) -> Path:
    rel = get_path_for_token(load_tokens(project_path) or {}, "NAME", name)
    if rel is None:
        raise ValueError(f"asset inconnu : {name}")
    return project_path / str(rel).replace("\\", "/")


def _asset_roots(project: Path) -> list[Path]:
    return [project / str(rel).replace("\\", "/")
            for rel in ((load_tokens(project) or {}).get("NAME") or {}).values()]


def _expected_dir(project: Path, base: str, ext: str) -> Path | None:
    from features.publisher.publish_core import resolve_publish_path

    try:
        return resolve_publish_path(project, f"{base}{ext}")
    except Exception:  # noqa: BLE001 - unparseable: not a FLUX publish
        return None


def _same_content(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False

        def digest(p: Path) -> str:
            h = hashlib.sha1()
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()
        return digest(a) == digest(b)
    except OSError:
        return False


def _canonical_instance(instance: str) -> str | None:
    from dcc.texture_publish import MAP_ALIASES

    low = re.sub(r"[^a-z0-9]", "", instance.lower())
    for token, aliases in MAP_ALIASES.items():
        if low in aliases and low != token.lower():
            return token
    return None


def _usd_deps(layer: Path) -> list[str]:
    try:
        from pxr import UsdUtils

        subs, refs, payloads = UsdUtils.ExtractExternalReferences(str(layer))
    except Exception:  # noqa: BLE001 - no pxr / unreadable layer
        return []
    return [d for d in (*subs, *refs, *payloads) if d and not d.startswith(("$", "@"))]


def _used_by_usd(project: Path) -> dict[str, str]:
    """{normalised path: layer} of every file a USD layer of the project points to
    (sublayers, references, payloads, texture paths). A UDIM pattern marks its folder."""
    used: dict[str, str] = {}
    for layer in project.rglob("*"):
        if layer.suffix.lower() not in _USD_EXTS or not layer.is_file() \
                or _SKIP_DIRS & set(layer.relative_to(project).parts):
            continue
        for dep in _usd_deps(layer):
            target = Path(dep) if os.path.isabs(dep) else layer.parent / dep
            key = _norm(target.parent) if "<udim>" in dep.lower() else _norm(target)
            used.setdefault(key, _rel(project, layer))
    return used


# ── what a file is, where it goes ──────────────────────────────────────────────

def _identify(path: Path) -> dict | None:
    """{"base", "ext", "role", "label"} of a publish PRODUCT, None for anything else.

    A product carries a version / LAST: in its name (<base>_v003.abc, <base>_LAST.abc),
    or in its folder (<base>_ABC_V003/<inner>, <base>_LAST/<inner>, <base>_v003/<tile>).
    "<base>.ext" alone is a work file (crowd preview, artist export)."""
    stem, ext, role = lp.parse_published_name(path.name)
    if not ext:
        return None
    m = re.match(r"^(?P<stem>.+?)\.(\d{4})$", stem)          # UDIM / frame tile
    if m:
        stem = m.group("stem")
    base = get_base_name(f"{stem}{ext}")
    if not base or parse_filename(f"{base}{ext}") is None:
        return None
    label = None
    lab = _LABEL_RE.search(stem)
    if lab and stem[: lab.start()] == base:
        label = lab.group(1)
    parent = path.parent.name
    nested = _NESTED_RE.match(parent)
    if label is None and nested and nested.group("base") == base:
        label = nested.group("label")
    if label is None and parent == f"{base}_{ACTIVE_VERSION_LABEL}":
        label = ACTIVE_VERSION_LABEL
    seq = _SEQ_DIR_RE.match(parent)
    if label is None and seq and seq.group("base") == base:
        label = f"v{seq.group('n')}"
    if label is None:
        return None
    label = ACTIVE_VERSION_LABEL if label.upper() == ACTIVE_VERSION_LABEL else "v" + label[1:]
    return {"base": base, "ext": ext, "role": role, "label": label}


def _target_name(info: dict) -> str:
    suffix = {"meta": lp.META_SUFFIX, "link": lp.LINK_SUFFIX}.get(info["role"], "")
    return f"{info['base']}_{info['label']}{info['ext']}{suffix}"


# ── scan ─────────────────────────────────────────────────────────────────────

def scan_asset(project_path: str | Path, name: str) -> dict:
    project = Path(project_path)
    root = asset_root(project, name)
    if not root.is_dir():
        raise ValueError(f"dossier de l'asset introuvable : {root}")
    return _scan(project, root, name)


def scan_project(project_path: str | Path) -> dict:
    """Whole project (every asset and shot). Empty folders only inside asset folders:
    shots keep an empty department skeleton on purpose (addendum ADR 0020)."""
    project = Path(project_path)
    return _scan(project, project, None)


def _plan(project: Path, root: Path, name: str | None) -> tuple[list[dict], list[Path]]:
    """One operation per file: {"kind", "action", "src", "dst", "twin", "warning"}."""
    names = [name] if name else list(((load_tokens(project) or {}).get("NAME") or {}).keys())
    comp_ver = [re.compile(rf"^{re.escape(n)}_v\d+$") for n in names]
    ops: list[dict] = []
    unknown: list[Path] = []
    canon_dirs: set[Path] = set()
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        parts = f.relative_to(project).parts
        if _SKIP_DIRS & set(parts) or any(p.startswith(".") for p in parts):
            continue
        if len(parts) == 1 or is_setup_rel(parts[0]):
            continue                       # project files: _flux_setup/, legacy root tokens.json...
        if lp.is_temp_name(f.name):
            ops.append({"kind": "temp", "action": "drop_tmp", "src": f})
            continue
        if f.name in _SIDE_FILES:
            continue
        # Component (ADR 0018): <NAME>/usd/<NAME>_LAST.usda, <NAME>/usd/<NAME>_vNNN/...
        if "usd" in f.parts and (any(f.name.startswith(f"{n}_{ACTIVE_VERSION_LABEL}") for n in names)
                                 or any(rx.match(p) for rx in comp_ver for p in f.parts)):
            continue
        info = _identify(f)
        parsed = parse_filename(f"{info['base']}{info['ext']}") if info else None
        expected = _expected_dir(project, info["base"], info["ext"]) if info else None
        if info is None or expected is None or not parsed \
                or (name and str(parsed.get("NAME", "")).upper() != name.upper()):
            unknown.append(f)
            continue
        here = f.parent
        seq = _SEQ_DIR_RE.match(here.name)
        in_seq = bool(seq and seq.group("base") == info["base"])
        if _norm(here) == _norm(expected) or (in_seq and _norm(here.parent) == _norm(expected)):
            if not parsed.get("is_shot"):
                canon_dirs.add(expected)
            continue                       # already at its place
        inside = _norm(here).startswith(_norm(expected) + os.sep)
        kind = "old_layout" if inside else "wrong_place"
        if in_seq:
            # a <base>_vNNN/ sequence / UDIM folder in the wrong place: its tiles follow it
            ops.append({"kind": kind, "action": "move", "src": f, "dst": expected / here.name / f.name})
            continue
        if here.name == f"{info['base']}_{ACTIVE_VERSION_LABEL}":
            ops.append({"kind": kind, "action": "warn", "src": f, "warning":
                        "ancien dossier USD en couches (<base>_LAST/) : a republier, garde"})
            continue
        if _NESTED_RE.match(here.name) and sum(1 for x in here.iterdir() if x.is_file()) > 1:
            ops.append({"kind": kind, "action": "warn", "src": f, "warning":
                        "ancien dossier de version a plusieurs fichiers : garde"})
            continue
        if info["role"] == "link":
            ops.append({"kind": kind, "action": "warn", "src": f, "warning":
                        "pointeur .link : son chemin ne suivrait pas, a republier"})
            continue
        ops.append({"kind": kind, "action": "move", "src": f, "dst": expected / _target_name(info)})

    # Older map names (COL, BASECOLOR...) next to the canonical folder (BCOL).
    for d in sorted(canon_dirs):
        canon = _canonical_instance(d.name)
        twin = d.parent / canon.lower() if canon else None
        if twin is None or not twin.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file() or any(op["src"] == f for op in ops):
                continue
            info = _identify(f)
            if info is None:
                continue
            new_base = re.sub(rf"_{re.escape(d.name)}(?=$|_)", f"_{canon}", info["base"], count=1,
                              flags=re.IGNORECASE)
            dst = twin / f.relative_to(d)
            dst = dst.with_name(dst.name.replace(info["base"], new_base, 1))
            ops.append({"kind": "old_map_name", "action": "move", "src": f, "dst": dst})
    return ops, unknown


def _decide(project: Path, ops: list[dict]) -> None:
    """Turn each move into move / drop_dup / warn: never overwrite, never break a path."""
    used = _used_by_usd(project)
    claimed: dict[str, Path] = {}
    moving = {_norm(op["src"]): op.get("dst") for op in ops if op["action"] == "move"}
    for op in ops:
        if op["action"] != "move":
            continue
        src, dst = op["src"], op["dst"]
        key = _norm(dst)
        taken = claimed.get(key) or (dst if dst.exists() else None)
        if taken is not None:
            if _same_content(src, taken):
                op.update(action="drop_dup", twin=dst)
            else:
                op.update(action="warn", warning="la place est prise par un fichier different : garde")
            continue
        claimed[key] = src
        # A USD whose relative references would point elsewhere once moved.
        if src.suffix.lower() in _USD_EXTS:
            for dep in _usd_deps(src):
                if os.path.isabs(dep):
                    continue
                old_t, new_t = src.parent / dep, dst.parent / dep
                if _norm(old_t) == _norm(new_t):
                    continue
                follows = moving.get(_norm(old_t))
                if follows is not None and _norm(follows) == _norm(new_t):
                    continue
                if new_t.exists() and old_t.exists() and _same_content(old_t, new_t):
                    continue
                op.update(action="warn", warning=f"sa reference {dep} ne suivrait pas : garde")
                break
    for op in ops:
        if op["action"] in ("move", "drop_dup"):
            by = used.get(_norm(op["src"])) or used.get(_norm(op["src"].parent))
            if by:
                op.update(action="warn", warning=f"utilise par {by} : garde")
    _mark_scene_refs(project, ops)


def _mark_scene_refs(project: Path, ops: list[dict]) -> None:
    """A scene, a text USD or a LAST pointer naming a file's path (its last two parts,
    / or \\) keeps it where it is: moving it could break that scene."""
    needles: dict[int, tuple[str, ...]] = {}
    for n, op in enumerate(ops):
        if op["action"] not in ("move", "drop_dup"):
            continue
        tail = _rel(project, op["src"]).lower().split("/")[-2:]
        needles[n] = ("/".join(tail), "\\".join(tail), "\\\\".join(tail))
    if not needles:
        return
    srcs = {_norm(ops[n]["src"]) for n in needles}
    for f in project.rglob("*"):
        if f.suffix.lower() not in _SCENE_EXTS or not f.is_file() \
                or _SKIP_DIRS & set(f.relative_to(project).parts) or _norm(f) in srcs:
            continue
        try:
            if f.stat().st_size > _SCENE_MAX_BYTES:
                continue
            text = f.read_bytes().decode("utf-8", errors="ignore").lower()
        except OSError:
            continue
        for n, keys in list(needles.items()):
            if any(k in text for k in keys):
                ops[n].update(action="warn", warning=f"nomme par {_rel(project, f)} : garde")
                del needles[n]
        if not needles:
            return


def _group_key(project: Path, op: dict) -> str:
    src_dir = _rel(project, op["src"].parent)
    dst_dir = _rel(project, op["dst"].parent) if op.get("dst") is not None else ""
    return "|".join((op["kind"], op["action"], src_dir, dst_dir, op.get("warning", "")))


def _scan(project: Path, root: Path, name: str | None, ops: list[dict] | None = None,
          unknown: list[Path] | None = None) -> dict:
    if ops is None:
        ops, unknown = _plan(project, root, name)
        _decide(project, ops)
    groups: dict[str, dict] = {}
    for op in ops:
        gid = _group_key(project, op)
        g = groups.setdefault(gid, {
            "id": gid, "kind": op["kind"], "action": op["action"],
            "path": _rel(project, op["src"].parent),
            "target": _rel(project, op["dst"].parent) if op.get("dst") is not None else "",
            "reason": KIND_REASON[op["kind"]], "files": 0, "bytes": 0,
            "safe": op["action"] != "warn", "warning": op.get("warning", ""), "names": []})
        g["files"] += 1
        try:
            g["bytes"] += op["src"].stat().st_size
        except OSError:
            pass
        if len(g["names"]) < 6:
            renamed = op.get("dst") is not None and op["dst"].name != op["src"].name
            g["names"].append(op["src"].name + (f" -> {op['dst'].name}" if renamed else ""))
    items = list(groups.values())
    empty_roots = [root] if name else [r for r in _asset_roots(project) if r.is_dir()]
    for er in empty_roots:
        for d in sorted(p for p in er.rglob("*") if p.is_dir() and not (_SKIP_DIRS & set(p.parts))):
            if any(x.is_file() for x in d.rglob("*")):
                continue
            rel = _rel(project, d)
            if any(rel.startswith(i["path"] + "/") for i in items if i["kind"] == "empty_dir"):
                continue
            items.append({"id": f"empty_dir|{rel}", "kind": "empty_dir", "action": "rm_empty",
                          "path": rel, "target": "", "reason": KIND_REASON["empty_dir"],
                          "files": 0, "bytes": 0, "safe": True, "warning": "", "names": []})
    items.sort(key=lambda i: (not i["safe"], i["path"].lower()))
    return {"scope": name or "", "items": items, "unknown": [_rel(project, u) for u in unknown or []]}


# ── apply / undo ─────────────────────────────────────────────────────────────

def apply_cleanup(project_path: str | Path, name: str | None, ids: list[str]) -> dict:
    """Run the picked (safe) items of a fresh scan; write the undo journal."""
    project = Path(project_path)
    root = asset_root(project, name) if name else project
    ops, unknown = _plan(project, root, name)
    _decide(project, ops)
    scan = _scan(project, root, name, ops, unknown)
    safe_ids = {i["id"] for i in scan["items"] if i["safe"]}
    picked = set(ids) & safe_ids
    errors = [f"{i.split('|')[2] if i.count('|') >= 2 else i} : pas sur, garde" for i in ids if i not in safe_ids]
    journal: list[dict] = []
    touched: set[Path] = set()
    for op in ops:
        if op["action"] == "warn" or _group_key(project, op) not in picked:
            continue
        src = op["src"]
        try:
            if op["action"] == "move":
                if op["dst"].exists():
                    errors.append(f"{_rel(project, src)} : place prise entre-temps, garde")
                    continue
                op["dst"].parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(op["dst"]))
                journal.append({"op": "move", "from": _rel(project, src), "to": _rel(project, op["dst"])})
            elif op["action"] == "drop_dup":
                if not _same_content(src, op["twin"]):
                    errors.append(f"{_rel(project, src)} : plus identique a {op['twin'].name}, garde")
                    continue
                src.unlink()
                journal.append({"op": "drop_dup", "path": _rel(project, src), "twin": _rel(project, op["twin"])})
            elif op["action"] == "drop_tmp":
                src.unlink()
                journal.append({"op": "drop_tmp", "path": _rel(project, src)})
            touched.add(src.parent)
        except OSError as exc:
            errors.append(f"{_rel(project, src)} : {exc}")
    for item in scan["items"]:
        if item["action"] == "rm_empty" and item["id"] in picked:
            d = project / item["path"]
            if d.is_dir() and not any(x.is_file() for x in d.rglob("*")):
                shutil.rmtree(d, ignore_errors=True)
                journal.append({"op": "rm_empty", "path": item["path"]})
    # Folders emptied by the operations, up to (not including) the asset / project root.
    stops = {_norm(project), *(_norm(r) for r in _asset_roots(project))}
    for d in sorted(touched, key=lambda p: len(p.parts), reverse=True):
        while _norm(d) not in stops and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            journal.append({"op": "rm_empty", "path": _rel(project, d)})
            d = d.parent
    jid = ""
    if journal:
        jid = datetime.now().strftime("%Y%m%d-%H%M%S")
        jdir = project / JOURNAL_DIR
        jdir.mkdir(exist_ok=True)
        (jdir / f"{jid}.json").write_text(json.dumps({"scope": name or "", "ops": journal}, indent=1),
                                          encoding="utf-8")
    log.info("Cleanup %s: %d operation(s), %d error(s)", name or project.name, len(journal), len(errors))
    return {"done": len(journal), "moved": sum(1 for j in journal if j["op"] == "move"),
            "dropped": sum(1 for j in journal if j["op"] in ("drop_dup", "drop_tmp")),
            "errors": errors, "journal": jid}


def list_backups(project_path: str | Path) -> list[dict]:
    """Cleanups that can be undone, newest first: [{"id", "files"}]."""
    jdir = Path(project_path) / JOURNAL_DIR
    out = []
    for f in sorted(jdir.glob("*.json"), reverse=True) if jdir.is_dir() else []:
        try:
            ops = json.loads(f.read_text(encoding="utf-8")).get("ops", [])
        except (OSError, ValueError):
            continue
        out.append({"id": f.stem, "files": sum(1 for o in ops if o["op"] in ("move", "drop_dup"))})
    return out


def restore_cleanup(project_path: str | Path, journal_id: str) -> dict:
    """Undo a cleanup: files go back, each dropped duplicate is copied back from its twin.
    A path taken since then is left alone (reported), never overwritten."""
    project = Path(project_path)
    if not re.fullmatch(r"[\w-]+", journal_id or ""):
        raise ValueError(f"nettoyage invalide : {journal_id!r}")
    jfile = project / JOURNAL_DIR / f"{journal_id}.json"
    if not jfile.is_file():
        raise ValueError(f"nettoyage introuvable : {journal_id}")
    ops = json.loads(jfile.read_text(encoding="utf-8")).get("ops", [])
    restored, kept = 0, []
    for o in reversed(ops):
        if o["op"] == "rm_empty":
            (project / o["path"]).mkdir(parents=True, exist_ok=True)
        elif o["op"] == "move":
            src, dst = project / o["from"], project / o["to"]
            if src.exists() or not dst.exists():
                kept.append(o["from"])
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
            restored += 1
        elif o["op"] == "drop_dup":
            path, twin = project / o["path"], project / o["twin"]
            if path.exists() or not twin.exists():
                kept.append(o["path"])
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(twin, path)
            restored += 1
    # Folders the moves had created and that are empty again.
    for o in ops:
        if o["op"] == "move":
            d = (project / o["to"]).parent
            while _norm(d) != _norm(project) and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                d = d.parent
    jfile.unlink()
    return {"restored": restored, "already_there": kept}


# ── clean clone ──────────────────────────────────────────────────────────────

def clone_project(project_path: str | Path, new_name: str) -> dict:
    """Copy the project next to it, then put the copy on the current layout (same safe
    operations). The original is untouched; the copy gets its own project_id."""
    from features.folder_manager.project_config import default_project_config, project_config_path

    src = Path(project_path)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", new_name.strip())
    if not safe:
        raise ValueError("nom de projet vide")
    dest = src.parent / safe
    if dest.exists():
        raise ValueError(f"le projet {safe} existe deja")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*_SKIP_DIRS))
    cfg_path = project_config_path(dest)
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    except (OSError, ValueError):
        cfg = {}
    cfg["project_id"] = default_project_config()["project_id"]
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    scan = scan_project(dest)
    res = apply_cleanup(dest, None, [i["id"] for i in scan["items"] if i["safe"]])
    files = sum(1 for f in dest.rglob("*") if f.is_file())
    log.info("Project %s cloned to %s: %d file(s), %d operation(s)", src.name, dest.name, files, res["done"])
    return {"project": dest.name, "files": files, "moved": res["moved"], "dropped": res["dropped"],
            "warnings": sum(1 for i in scan["items"] if not i["safe"])}
