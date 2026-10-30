# page_data.py — shared data collections of the TOOL pages (ADR 0066 n°3, n°4).
#
# Zero server: every writer appends to ITS OWN journal, nobody rewrites a shared file,
# so OneDrive or a share never sees two machines on one file:
#   <base>/pages_data/<page>/<collection>/<AUTHOR>.jsonl     one line per operation
#   <base>/pages_data/<page>/<collection>/media/<hash>.<ext>  images copied by the backend
# <base> = <project>/_flux_setup (a project page, or a collection `per: project` of a team
# page) or CONFIG/extensions (`per: team`).
#
# An operation: {op: put | del, rid, fields, at, user, seq}. put merges its fields into
# the record (per field: the latest operation wins, so two people moving and retyping
# the same card both keep their change); del removes the record. Reading merges every
# journal, ordered by (at, user, seq): `at` is each machine's clock (same limit as the
# team chat). etag = sizes + dates of the journals: a reader that has it gets
# {unchanged: true} without parsing anything (cheap 5 s refresh, ADR 0066 n°4).
#
# put with restore: true brings back a deleted record under its rid (the board undo of a
# delete, ADR 0071 n°4): the op carries every field. A plain put on a deleted rid stays a 404.
# Compaction (ADR 0071 n°3): past COMPACT_BYTES, the author rewrites ITS OWN journal,
# keeping only its operations that still decide something, with their original at / seq,
# so the merge of every journal gives exactly the same records.
#
# Bytes never go through the API (ADR 0005): an image is COPIED from a local path the
# user picked; the page shows it through a read route, like production/ref.

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from flux_flows.model import FIELD_ID_RE
from flux_flows.pages import BOARD_FIELDS, DataField, DataSpec
from flux_flows.store import FlowStoreError

SUFFIX = ".jsonl"
MEDIA = "media"
RID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
AUTHOR_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_TEXT = 10_000
MAX_OPS = 200                       # per request
MAX_RECORDS = 20_000
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MAX_IMAGE = 20 * 1024 * 1024
COMPACT_BYTES = 256 * 1024
BOARD_TYPES = ("card", "note", "image", "link", "shape", "text")
BOARD_TYPED = {"x": "float", "y": "float", "w": "float", "h": "float", "z": "float", "text": "text", "color": "str",
               "image": "image", "from": "str", "to": "str", "type": "str", "shape": "str", "stroke": "str",
               "font_size": "float", "bold": "bool", "label": "text", "dash": "str", "arrow_start": "bool",
               "arrow_end": "bool", "group": "str", "locked": "bool"}
BOARD_CHOICES = {"type": BOARD_TYPES, "shape": ("rect", "round", "ellipse", "diamond"),
                 "dash": ("solid", "dashed", "dotted")}


# -- where --------------------------------------------------------------------

def data_base(page_roots: Mapping[str, Optional[Path]], page_scope: str, per: str) -> Path:
    """Folder that holds pages_data/: next to the pages folder of the right scope."""
    target = "project" if page_scope == "project" or per == "project" else "team"
    root = page_roots.get(target)
    if root is None:
        what = "ouvre un projet : ces donnees sont rangees par projet" if target == "project" else "FLUX_ROOT inconnu"
        raise FlowStoreError(f"donnees indisponibles ({what})", 409)
    return Path(root).parent


def collection_dir(page_roots: Mapping[str, Optional[Path]], page_scope: str, page_id: str,
                   spec: DataSpec) -> Path:
    if not FIELD_ID_RE.match(spec.id) or not FIELD_ID_RE.match(page_id):
        raise FlowStoreError("id de page ou de collection invalide")
    return data_base(page_roots, page_scope, spec.per) / "pages_data" / page_id / spec.id


def _author_file(folder: Path, user: str) -> Path:
    if not AUTHOR_RE.match(user or ""):
        raise FlowStoreError("utilisateur inconnu : choisis ton nom dans Parametres > User", 403)
    return folder / f"{user}{SUFFIX}"


def _journals(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix == SUFFIX and AUTHOR_RE.match(p.stem))


def etag(folder: Path) -> str:
    parts = []
    for path in _journals(folder):
        try:
            st = path.stat()
        except OSError:
            continue
        parts.append(f"{path.name}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


# -- values -------------------------------------------------------------------

def _check_value(name: str, kind: str, value: Any, field: Optional[DataField] = None) -> Any:
    if value is None:
        return None
    bad = FlowStoreError(f"champ `{name}` : valeur invalide pour le type {kind}", 422)
    if kind in ("str", "text", "user", "path", "image"):
        if not isinstance(value, str) or len(value) > MAX_TEXT:
            raise bad
        if kind == "image" and value and not re.match(rf"^{MEDIA}/[0-9a-f]{{8,64}}\.[a-z]{{3,4}}$", value):
            raise FlowStoreError(f"champ `{name}` : image a ajouter par le bouton Image", 422)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad
        return value
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            raise bad
        return float(value)
    if kind == "bool":
        if not isinstance(value, bool):
            raise bad
        return value
    if kind == "date":
        try:
            date.fromisoformat(str(value))
        except ValueError:
            raise bad from None
        return str(value)
    if kind == "datetime":
        try:
            datetime.fromisoformat(str(value))
        except ValueError:
            raise bad from None
        return str(value)
    if kind == "select":
        allowed = [o.value for o in (field.options or [])] if field else []
        if value not in allowed:
            raise FlowStoreError(f"champ `{name}` : choix `{value}` hors liste ({', '.join(allowed)})", 422)
        return value
    raise bad


def check_fields(spec: DataSpec, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Fields of a put, typed against the collection (board: its fixed fields)."""
    if not isinstance(fields, dict):
        raise FlowStoreError("fields doit etre un objet", 422)
    out: Dict[str, Any] = {}
    if spec.kind == "board":
        for name, value in fields.items():
            if name not in BOARD_FIELDS:
                raise FlowStoreError(f"un board n'a pas de champ `{name}` ({', '.join(BOARD_FIELDS)})", 422)
            out[name] = _check_value(name, BOARD_TYPED[name], value)
            allowed = BOARD_CHOICES.get(name)
            if allowed and out[name] is not None and out[name] not in allowed:
                raise FlowStoreError(f"{name} `{out[name]}` inconnu ({', '.join(allowed)})", 422)
            if name == "font_size" and out[name] is not None and not 6 <= out[name] <= 200:
                raise FlowStoreError("font_size : entre 6 et 200", 422)
        return out
    known = {f.id: f for f in spec.fields}
    for name, value in fields.items():
        field = known.get(name)
        if field is None:
            raise FlowStoreError(f"la collection `{spec.id}` n'a pas de champ `{name}`", 422)
        out[name] = _check_value(name, field.type, value, field)
    return out


# -- read ---------------------------------------------------------------------

def _op_key(op: Dict[str, Any]):
    return (str(op.get("at", "")), op["user"], int(op.get("seq", 0) or 0))


def _read_file(path: Path) -> List[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    ops = []
    for line in text.splitlines():
        try:
            op = json.loads(line)
        except ValueError:   # a line cut by a crash or a sync in progress: skipped
            continue
        if isinstance(op, dict) and op.get("op") in ("put", "del") and RID_RE.match(str(op.get("rid", ""))):
            op["user"] = path.stem           # the file names the author, not the line
            ops.append(op)
    return ops


def _read_ops(folder: Path) -> List[Dict[str, Any]]:
    ops = [op for path in _journals(folder) for op in _read_file(path)]
    ops.sort(key=_op_key)
    return ops


def merge(ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Records from ordered operations: {rid, <fields>, _created_by, _created_at, _by, _at}."""
    records: Dict[str, Dict[str, Any]] = {}
    for op in ops:
        rid = op["rid"]
        if op["op"] == "del":
            records.pop(rid, None)
            continue
        rec = records.get(rid)
        if rec is None:
            rec = records[rid] = {"rid": rid, "_created_by": op["user"], "_created_at": op.get("at")}
        for key, value in (op.get("fields") or {}).items():
            if isinstance(key, str) and not key.startswith("_") and key != "rid":
                rec[key] = value
        rec["_by"], rec["_at"] = op["user"], op.get("at")
    return sorted(records.values(), key=lambda r: (str(r.get("_created_at") or ""), r["rid"]))


def read_records(folder: Path, known_etag: Optional[str] = None) -> Dict[str, Any]:
    tag = etag(folder)
    if known_etag is not None and known_etag == tag:
        return {"etag": tag, "unchanged": True}
    records = merge(_read_ops(folder))
    return {"etag": tag, "unchanged": False, "records": records[-MAX_RECORDS:]}


# -- write --------------------------------------------------------------------

def new_rid(user: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]", "", user or "x")[:12] or "x"
    return f"{stem}_{int(time.time() * 1000):x}_{secrets.token_hex(3)}"


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def write_ops(folder: Path, spec: DataSpec, ops: List[Dict[str, Any]], *, user: str) -> Dict[str, Any]:
    """Append *ops* to the journal of *user*: {rids, etag}. A new record (put without rid)
    gets one; its required fields must be there."""
    if not ops or len(ops) > MAX_OPS:
        raise FlowStoreError(f"1 a {MAX_OPS} operations par envoi", 422)
    path = _author_file(folder, user)
    existing = None
    known: Optional[set] = None
    lines, rids = [], []
    base_seq = time.time_ns()
    for k, op in enumerate(ops):
        kind = op.get("op")
        rid = op.get("rid")
        if kind not in ("put", "del"):
            raise FlowStoreError("op : put ou del", 422)
        if rid is not None and not RID_RE.match(str(rid)):
            raise FlowStoreError("rid invalide", 422)
        if kind == "del":
            if rid is None:
                raise FlowStoreError("del sans rid", 422)
            lines.append({"op": "del", "rid": rid, "at": _now(), "seq": base_seq + k})
            rids.append(rid)
            continue
        fields = check_fields(spec, op.get("fields") or {})
        if op.get("restore"):
            if rid is None:
                raise FlowStoreError("restore sans rid", 422)
            if known is None:
                known = {o["rid"] for o in _read_ops(folder)}
            if rid not in known:
                raise FlowStoreError(f"enregistrement {rid} jamais vu : rien a restaurer", 404)
        elif rid is None:
            rid = new_rid(user)
            missing = [f.id for f in spec.fields if f.required and fields.get(f.id) in (None, "")]
            if missing:
                raise FlowStoreError(f"champ(s) obligatoire(s) : {', '.join(missing)}", 422)
        else:
            if existing is None:
                existing = {r["rid"] for r in merge(_read_ops(folder))}
            if rid not in existing:
                raise FlowStoreError(f"enregistrement {rid} introuvable (supprime entre-temps ?)", 404)
        lines.append({"op": "put", "rid": rid, "fields": fields, "at": _now(), "seq": base_seq + k})
        rids.append(rid)
    folder.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
    from core.json_manager import append_lock

    with append_lock(path):   # only this user writes this file; the lock covers two requests of this machine
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        try:
            big = path.stat().st_size > COMPACT_BYTES
        except OSError:
            big = False
        if big:
            compact_journal(path)
    return {"rids": rids, "etag": etag(folder)}


def compact_ops(ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The operations of ONE author that still decide something, unchanged (at, seq kept):
    per record, its last del, the first put after it (creation stamp) and, per field, the
    last put that sets it. Everything older than this author's last del is dead for anyone."""
    ops = sorted(ops, key=_op_key)
    by_rid: Dict[str, List[int]] = {}
    for i, op in enumerate(ops):
        by_rid.setdefault(op["rid"], []).append(i)
    keep: Dict[int, Optional[Dict[str, Any]]] = {}   # index -> trimmed fields (None for a del)
    for idx in by_rid.values():
        last_del = max((i for i in idx if ops[i]["op"] == "del"), default=None)
        live = [i for i in idx if last_del is None or i > last_del]
        if last_del is not None:
            keep[last_del] = None
        winner: Dict[str, int] = {}
        for i in live:
            for key in (ops[i].get("fields") or {}):
                winner[key] = i
        if live:   # first put = creation stamp, last one = _by / _at
            keep.setdefault(live[0], {})
            keep.setdefault(live[-1], {})
        for key, i in winner.items():
            keep.setdefault(i, {})
            keep[i][key] = ops[i]["fields"][key]
    out = []
    for i in sorted(keep):
        op = {k: v for k, v in ops[i].items() if k not in ("user", "fields")}
        if ops[i]["op"] == "put":
            op["fields"] = keep[i]
        out.append(op)
    return out


def compact_journal(path: Path) -> int:
    """Rewrite the author's own journal with compact_ops (atomic replace): lines dropped.
    Called with the append lock of *path* held."""
    ops = _read_file(path)
    kept = compact_ops(ops)
    text = "".join(json.dumps(op, ensure_ascii=False) + "\n" for op in kept)
    tmp = path.with_name(f".flux_tmp_{secrets.token_hex(4)}{SUFFIX}.part")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)
    return len(ops) - len(kept)


# -- media --------------------------------------------------------------------

def add_image(folder: Path, source: str) -> str:
    """Copy a local image into media/ (named by its content hash): 'media/<hash>.<ext>'."""
    src = Path(source)
    ext = src.suffix.lower()
    if ext not in IMAGE_EXT:
        raise FlowStoreError(f"image attendue ({', '.join(IMAGE_EXT)})", 422)
    try:
        size = src.stat().st_size
    except OSError:
        raise FlowStoreError(f"fichier introuvable : {source}", 404) from None
    if not src.is_file() or size > MAX_IMAGE:
        raise FlowStoreError(f"image trop grosse (max {MAX_IMAGE // (1024 * 1024)} Mo)", 422)
    digest = hashlib.sha1()
    with open(src, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    name = f"{digest.hexdigest()[:20]}{'.jpg' if ext == '.jpeg' else ext}"
    target = folder / MEDIA / name
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".flux_tmp_{secrets.token_hex(4)}{target.suffix}")
        shutil.copyfile(src, tmp)
        tmp.replace(target)
    return f"{MEDIA}/{name}"


def media_file(folder: Path, name: str) -> Path:
    if not re.match(r"^[0-9a-f]{8,64}\.[a-z]{3,4}$", name or ""):
        raise FlowStoreError("nom de media invalide", 400)
    path = folder / MEDIA / name
    if not path.is_file():
        raise FlowStoreError("media introuvable", 404)
    return path


def media_type(name: str) -> str:
    return {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}.get(
        Path(name).suffix.lower(), "application/octet-stream")


def locate(page_id: str, collection: str, project: Optional[str]):
    """(folder, spec, page scope) of a collection of the winning page *page_id* (project > team)."""
    from flux_flows import locations, page_store

    roots = locations.page_roots(project)
    scope = page_store.resolve(roots, page_id)
    if scope is None:
        raise FlowStoreError(f"page {page_id} introuvable", 404)
    page = page_store.read_page(roots, scope, page_id)["page"]
    spec = spec_of(page, collection)
    return collection_dir(roots, scope, page_id, spec), spec, scope


def spec_of(page, collection: str) -> DataSpec:
    spec = next((d for d in page.data if d.id == collection), None)
    if spec is None:
        raise FlowStoreError(f"la page {page.id} n'a pas de collection `{collection}`", 404)
    return spec


def can_write(spec: DataSpec, current_rights: Dict[str, Any]) -> bool:
    return spec.write == "all" or bool(current_rights.get("team_td"))

