# features/production/ref_media.py — reference media (/ref) storage for the
# Production Tab's task/subtask embed zone.
#
# Layout on disk, at the root of a task or subtask folder:
#
#   <task_or_subtask_root>/ref/
#     ├── v001.mp4        ← every deposit, versioned, zero-padded
#     ├── v002.png
#     └── LAST.png        ← a copy of the most recent deposit (what the UI shows)
#
# Only images and (silent) videos are accepted — no audio files. The UI shows
# LAST by default; older versions are listed from the folder's modif log
# (retake 10): every deposit appends one entry (vNNN file, author, date, the
# dropped file's name) to ref/modif_logs.json, the same publication log the
# Publisher and the Folder Manager "LOG JSON" panel use.

from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.paths import is_subpath
from features.folder_manager.tokens import get_path_for_token, load_tokens
from features.publisher.modif_log import append_log, read_logs

# Extensions the embed zone understands. Kept broad on the video side; the
# renderer plays whatever Chromium can decode (mp4/webm reliably, mov/m4v often).
# What Chromium plays / shows inline. mov and mkv often carry codecs it cannot
# decode (ProRes, DNxHD): the viewer then offers Keyframe Pro instead.
BROWSER_PLAYABLE_EXTS = {".mp4", ".webm", ".ogv", ".ogg", ".m4v",
                         ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".apng", ".avif", ".svg"}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".apng", ".avif", ".svg"}
VIDEO_EXTS = {".mp4", ".webm", ".ogv", ".ogg", ".m4v", ".mov", ".mkv"}
ALLOWED_EXTS = IMAGE_EXTS | VIDEO_EXTS

# Max deposit size (bytes) — playblasts are usually a few MB; guard against a
# stray multi-GB drop wedging the sidecar.
MAX_BYTES = 500 * 1024 * 1024

_VERSION_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)
_SAFE_NAME_RE = re.compile(r"^(?:v\d+|LAST)\.[A-Za-z0-9]+$")

REF_DIRNAME = "ref"


def _norm(rel: str) -> str:
    """Normalise separators, collapse repeats, strip leading/trailing slashes."""
    rel = (rel or "").replace("\\", "/")
    rel = re.sub(r"/+", "/", rel)
    return rel.strip("/")


def resolve_ref_root(
    project_path: Path,
    kind: str,
    class_token: str = "",
    name: str = "",
    seq: str = "",
    shot: str = "",
    task: str = "",
    subtask: str = "",
) -> str:
    """Resolve the project-relative root of a task/subtask, where /ref lives.

    Mirrors the folder creators so /ref lands beside the task's real folder:
      * shot/seq tasks resolve through the templated CLASS token
        (e.g. ANIM → shot/{seq}/{shot}/anim), with {seq}/{shot} filled in;
      * asset tasks resolve through NAME (or CLASS+name) + TYPE + INSTANCE.
    The subtask, when present, is a lowercased folder under the task root.
    """
    tokens = load_tokens(project_path)                 # already merges CLASS/TYPE/INSTANCE defaults
    class_map: dict = tokens.get("CLASS") or {}
    type_map:  dict = tokens.get("TYPE") or {}
    inst_map:  dict = tokens.get("INSTANCE") or {}

    task_u = (task or "").strip().upper()
    sub    = (subtask or "").strip()
    sub_ok = bool(sub) and sub.lower() != "null"

    if kind in ("shot", "seq"):
        seq_label  = (seq or "").strip()
        shot_label = (shot or "").strip()
        tpl = class_map.get(task_u)
        if tpl:
            rel = tpl.replace("{seq}", seq_label).replace("{shot}", shot_label)
        elif shot_label:
            rel = f"shot/{seq_label}/{shot_label}/{task_u.lower()}"
        else:
            rel = f"shot/{seq_label}/{task_u.lower()}"
        if sub_ok:
            rel = f"{rel}/{sub.lower()}"
        return _norm(rel)

    # asset
    class_rel = _norm(get_path_for_token(tokens, "CLASS", (class_token or "").upper()) or "")
    name_rel = get_path_for_token(tokens, "NAME", (name or "").upper())
    if name_rel:
        name_rel = _norm(name_rel)
    elif class_rel:
        name_rel = _norm(f"{class_rel}/{(name or '').upper()}")
    else:
        name_rel = (name or "").upper()

    parts = [name_rel]
    if task_u:
        parts.append(_norm(type_map.get(task_u) or task_u.lower()))
    if sub_ok:
        inst_sub = inst_map.get(sub.lower()) or inst_map.get(sub.upper()) or sub.lower()
        parts.append(_norm(inst_sub))
    return _norm("/".join(p for p in parts if p))


def kind_for_ext(ext: str) -> str:
    e = ext.lower()
    if e in VIDEO_EXTS:
        return "video"
    if e in IMAGE_EXTS:
        return "image"
    return "other"


def _safe_ref_dir(project_path: Path, rel_path: str) -> Path:
    """Resolve <project>/<rel_path>/ref, refusing any escape from the project."""
    rel = (rel_path or "").strip().strip("/").replace("\\", "/")
    base = (project_path / rel) if rel else project_path
    ref_dir = (base / REF_DIRNAME).resolve()
    if not is_subpath(ref_dir, project_path.resolve()) and ref_dir != project_path.resolve():
        raise ValueError("Chemin non autorisé")
    return ref_dir


def _next_version(ref_dir: Path) -> int:
    """Next vNNN number (1-based) given what already exists in the ref dir."""
    if not ref_dir.exists():
        return 1
    highest = 0
    for f in ref_dir.iterdir():
        if not f.is_file():
            continue
        m = _VERSION_RE.match(f.stem)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def deposit(project_path: Path, rel_path: str, filename: str, data: bytes, user: str = "") -> dict:
    """Store *data* as the next version, refresh LAST and log it. Returns the LAST info."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"Format non supporté : {ext or '(aucune extension)'}")
    if not data:
        raise ValueError("Fichier vide")
    if len(data) > MAX_BYTES:
        raise ValueError("Fichier trop volumineux (max 500 Mo)")

    ref_dir = _safe_ref_dir(project_path, rel_path)
    ref_dir.mkdir(parents=True, exist_ok=True)

    num = _next_version(ref_dir)
    version = f"v{num:03d}"
    (ref_dir / f"{version}{ext}").write_bytes(data)

    # LAST is a single file — drop any previous LAST.* (extension may change).
    for old in ref_dir.glob("LAST.*"):
        try:
            old.unlink()
        except OSError:
            pass
    last_name = f"LAST{ext}"
    (ref_dir / last_name).write_bytes(data)

    # The publication relation the version list reads (never the file names alone).
    append_log(ref_dir, f"{version}{ext}", version, Path(filename).name, user or "unknown")

    return {"ok": True, "version": version, "file": last_name, "ext": ext, "kind": kind_for_ext(ext)}


def versions(project_path: Path, rel_path: str) -> list[dict]:
    """Every deposited version of a /ref zone, newest first.

    Source of truth = the ref folder's modif log (one entry per deposit). Each
    entry says whether its file is still on disk (`available`) and whether the
    renderer can play it (`playable`). Files on disk that predate the log (old
    deposits) are listed too, flagged `logged: False`, so nothing silently
    disappears. `latest` marks the version LAST is a copy of.
    """
    ref_dir = _safe_ref_dir(project_path, rel_path)
    if not ref_dir.exists():
        return []
    on_disk: dict[str, Path] = {}
    for f in ref_dir.iterdir():
        if f.is_file() and _VERSION_RE.match(f.stem) and f.suffix.lower() in ALLOWED_EXTS:
            on_disk[f.name.lower()] = f

    rows: dict[str, dict] = {}
    for entry in read_logs(ref_dir):
        name = str(entry.get("name") or "")
        m = _VERSION_RE.match(Path(name).stem)
        if not m or name.lower() in rows:
            continue                       # newest entry wins for a reused name
        ext = Path(name).suffix.lower()
        rows[name.lower()] = {
            "version": f"v{int(m.group(1)):03d}", "num": int(m.group(1)), "file": name,
            "ext": ext, "kind": kind_for_ext(ext),
            "user": entry.get("user", ""), "date": entry.get("date", ""), "time": entry.get("time", ""),
            "source_name": entry.get("modification", ""), "logged": True,
            "available": name.lower() in on_disk,
            "playable": ext in BROWSER_PLAYABLE_EXTS,
        }
    for key, f in on_disk.items():
        if key in rows:
            continue
        num = int(_VERSION_RE.match(f.stem).group(1))
        ext = f.suffix.lower()
        rows[key] = {
            "version": f"v{num:03d}", "num": num, "file": f.name, "ext": ext, "kind": kind_for_ext(ext),
            "user": "", "date": "", "time": "", "source_name": "", "logged": False,
            "available": True, "playable": ext in BROWSER_PLAYABLE_EXTS,
        }
    result = sorted(rows.values(), key=lambda r: r["num"], reverse=True)
    newest = next((r for r in result if r["available"]), None)
    for r in result:
        r["latest"] = r is newest
        del r["num"]
    return result


def shot_previews(project_path: Path, seq: str, shot: str, tasks: list[str]) -> list[dict]:
    """The LAST media of each task /ref zone of a shot, in the order of *tasks*.

    Used by the Production Timeline (click on a shot) and the auto edit: one
    entry per task that holds an image or a video, with its project-relative
    ref root (to stream it) and its absolute path (for Keyframe Pro).
    """
    out: list[dict] = []
    seen: set[str] = set()
    for task in tasks:
        task_u = (task or "").strip().upper()
        if not task_u or task_u in seen:
            continue
        seen.add(task_u)
        rel = resolve_ref_root(project_path, "shot", seq=seq, shot=shot, task=task_u)
        try:
            info = latest(project_path, rel)
        except ValueError:
            continue
        if not info:
            continue
        vers = versions(project_path, rel)
        top = next((v for v in vers if v["latest"]), None)
        out.append({
            "task": task_u, "rel_path": rel, **info,
            "version": top["version"] if top else "",
            "version_file": top["file"] if top else "",
            "version_count": len(vers),
            "abs_path": str(_safe_ref_dir(project_path, rel) / info["file"]),
        })
    return out


def latest(project_path: Path, rel_path: str) -> dict | None:
    """Return the current LAST file info, or None if the ref dir has none yet."""
    ref_dir = _safe_ref_dir(project_path, rel_path)
    if not ref_dir.exists():
        return None
    for f in sorted(ref_dir.glob("LAST.*")):
        if f.is_file():
            ext = f.suffix.lower()
            return {"file": f.name, "ext": ext, "kind": kind_for_ext(ext)}
    return None


def resolve_file(project_path: Path, rel_path: str, name: str) -> Path:
    """Resolve a specific ref file (LAST.* or vNNN.*) safely, for streaming/export."""
    if not name or not _SAFE_NAME_RE.match(name):
        raise ValueError("Nom de fichier invalide")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError("Format non supporté")
    ref_dir = _safe_ref_dir(project_path, rel_path)
    target = (ref_dir / name).resolve()
    if target.parent != ref_dir:
        raise ValueError("Chemin non autorisé")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(name)
    return target


def export_to(project_path: Path, rel_path: str, name: str, dest_path: str) -> Path:
    """Copy a ref file to an arbitrary user-chosen destination (download button)."""
    src = resolve_file(project_path, rel_path, name)
    dest = Path(dest_path)
    if not dest.suffix:
        dest = dest.with_suffix(src.suffix)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest
