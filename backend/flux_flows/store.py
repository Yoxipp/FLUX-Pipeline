# store.py — flows by scope, working file and frozen versions (01_ARCHITECTURE §6, ADR 0058).
#
# Layout of a scope folder D (see locations.py):
#   D/<name>.flow.yml                          working file: Save overwrites it
#   D/<name>/versions/<name>_vNNN.flow.yml     frozen: Save and increment, only if the content changed
#   D/<name>/state.json                        {current, active_version, active, revision, saved_by, saved_at}
#   D/_trash/<name>_<date>/                    deleted flows (working file + folder)
# shipped is read only and has no versions.
#
# Writes: one critical section per flow (append_lock on state.json, safe across
# machines), temp file + os.replace, the YAML first and state.json last; a crash in
# between leaves an orphan vNNN that the next increment skips (max + 1).
# Conflict: the editor sends the revision it loaded; another save since then = 409.
# history.jsonl (team, project) is appended after the lock is released:
# append_jsonl takes the same non reentrant process lock.

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from flux_flows.model import NAME_RE, Flow, FlowSchemaError, dump_flow, load_flow_text

SUFFIX = ".flow.yml"
SCOPE_ORDER = ("perso", "project", "team", "shipped")
LEGACY_PREFIX = "legacy_"
EXAMPLE_PREFIX = "example_"   # shipped example_*: the Exemples category, duplicated to be used (ADR 0069)


class FlowStoreError(ValueError):
    """A store operation failed. ``status`` is the HTTP code the router answers."""

    def __init__(self, message: str, status: int = 400, detail: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail or {}


# -- paths --------------------------------------------------------------------

def _root(roots: Mapping[str, Optional[Path]], scope: str) -> Path:
    if scope not in SCOPE_ORDER:
        raise FlowStoreError(f"portee inconnue '{scope}'")
    root = roots.get(scope)
    if root is None:
        raise FlowStoreError(f"portee {scope} indisponible (pas de projet ou d'utilisateur)")
    return Path(root)


def _check_name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise FlowStoreError(f"nom de flow invalide '{name}'")
    return name


def _contained(path: Path, root: Path) -> Path:
    # Names are already checked by NAME_RE; this guards against a symlinked or odd root.
    resolved, base = path.resolve(), root.resolve()
    if resolved != base and base not in resolved.parents:
        raise FlowStoreError("chemin hors du dossier des flows", 400)
    return path


def working_file(root: Path, name: str) -> Path:
    return _contained(root / f"{_check_name(name)}{SUFFIX}", root)


def shipped_file(root: Path, name: str) -> Path:
    """A shipped flow: top level, else a DCC node flow of shipped/dcc/<soft>/ (P6a)."""
    path = working_file(root, name)
    if path.is_file():
        return path
    from flux_flows import dcc_nodes

    if Path(root).resolve() == dcc_nodes.shipped_dcc_dir().parent.resolve():
        found = dcc_nodes.shipped_file(name)
        if found is not None:
            return found
    return path


def flow_folder(root: Path, name: str) -> Path:
    return _contained(root / _check_name(name), root)


def version_file(root: Path, name: str, version: int) -> Path:
    return flow_folder(root, name) / "versions" / f"{name}_v{version:03d}{SUFFIX}"


def _version_numbers(root: Path, name: str) -> List[int]:
    folder = flow_folder(root, name) / "versions"
    pattern = re.compile(rf"^{re.escape(name)}_v(\d{{3,}}){re.escape(SUFFIX)}$")
    if not folder.is_dir():
        return []
    return sorted(int(m.group(1)) for f in folder.iterdir() if (m := pattern.match(f.name)))


def history_path(roots: Mapping[str, Optional[Path]], scope: str) -> Optional[Path]:
    if scope == "team":
        return _root(roots, scope).parent / "history.jsonl"
    if scope == "project":
        return _root(roots, scope) / "history.jsonl"
    return None


# -- low level ----------------------------------------------------------------

def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".flux_tmp_", suffix=SUFFIX)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _default_state() -> Dict[str, Any]:
    # valid: validation of the working file at its last write (P4, None = never validated).
    return {"current": 0, "active_version": None, "active": False, "revision": 0,
            "saved_by": None, "saved_at": None, "valid": None}


def read_state(root: Path, name: str) -> Dict[str, Any]:
    state = _default_state()
    try:
        data = json.loads((flow_folder(root, name) / "state.json").read_text(encoding="utf-8"))
        if isinstance(data, dict):
            state.update(data)
    except (OSError, ValueError):
        pass
    return state


def _write_state(root: Path, name: str, state: Dict[str, Any]) -> None:
    _write_text(flow_folder(root, name) / "state.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def _flow_lock(root: Path, name: str) -> Iterator[None]:
    from core.json_manager import append_lock

    with append_lock(flow_folder(root, name) / "state.json"):
        yield


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _history(roots: Mapping[str, Optional[Path]], scope: str, entry: Dict[str, Any]) -> None:
    path = history_path(roots, scope)
    if path is None:
        return
    from core.json_manager import append_jsonl

    line = {"at": _now(), "user": entry.pop("user", None), "host": socket.gethostname(),
            "kind": entry.pop("kind"), "scope": scope, **entry}
    append_jsonl(path, [line])


def _canonical(text: str) -> str:
    return dump_flow(load_flow_text(text))


def shipped_hash(text: str) -> str:
    """Fingerprint of a shipped flow's canonical content (W_SHIPPED_CHANGED)."""
    return hashlib.sha1(_canonical(text).encode("utf-8")).hexdigest()[:16]


def shipped_changed(roots: Mapping[str, Optional[Path]], scope: str, name: str) -> bool:
    """A team copy (unlock) whose shipped original changed since the copy."""
    if scope != "team" or roots.get("shipped") is None or roots.get(scope) is None:
        return False
    started = read_state(Path(roots[scope]), name).get("shipped_hash")
    try:
        text = shipped_file(Path(roots["shipped"]), name).read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(started) and started != shipped_hash(text)


def _require_writable(scope: str) -> None:
    if scope == "shipped":
        raise FlowStoreError("les flows livres sont en lecture seule : fais-en une copie d'equipe", 403)


# -- read ---------------------------------------------------------------------

def resolve(roots: Mapping[str, Optional[Path]], name: str) -> Optional[str]:
    """Scope that wins for *name*: perso > project > team > shipped."""
    _check_name(name)
    for scope in SCOPE_ORDER:
        root = roots.get(scope)
        if root is None:
            continue
        path = shipped_file(Path(root), name) if scope == "shipped" else working_file(Path(root), name)
        if path.is_file():
            return scope
    return None


def list_flows(roots: Mapping[str, Optional[Path]]) -> List[Dict[str, Any]]:
    """Every flow of every available scope; ``shadowed`` = a narrower scope wins."""
    out: List[Dict[str, Any]] = []
    winners: Dict[str, str] = {}
    for scope in SCOPE_ORDER:
        root = roots.get(scope)
        if root is None or not Path(root).is_dir():
            continue
        for path in sorted(Path(root).glob(f"*{SUFFIX}")):
            name = path.name[: -len(SUFFIX)]
            if not NAME_RE.match(name):
                continue
            entry: Dict[str, Any] = {"name": name, "scope": scope, "label": "", "description": "",
                                     "legacy": name.startswith(LEGACY_PREFIX), "origin": None,
                                     "shadowed": name in winners, "error": None}
            try:
                flow = load_flow_text(path.read_text(encoding="utf-8"))
                entry.update(label=flow.label, description=flow.description,
                             origin=flow.origin.model_dump() if flow.origin else None)
            except (OSError, FlowSchemaError) as exc:
                entry["error"] = str(exc)
            if scope != "shipped":
                state = read_state(Path(root), name)
                entry.update({k: state[k] for k in ("current", "active_version", "active", "revision")})
            winners.setdefault(name, scope)
            out.append(entry)
    return out


def read_flow(roots: Mapping[str, Optional[Path]], scope: str, name: str,
              version: Optional[int] = None) -> Dict[str, Any]:
    """The working file (version None) or a frozen version, with its state."""
    root = _root(roots, scope)
    if scope == "shipped" and version is None:
        path = shipped_file(root, name)
    else:
        path = working_file(root, name) if version is None else version_file(root, name, version)
    if scope == "shipped" and version is not None:
        raise FlowStoreError("un flow livre n'a pas de versions", 404)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        what = f"version {version} de {name}" if version is not None else f"flow {name}"
        raise FlowStoreError(f"{what} introuvable ({scope})", 404) from None
    flow = load_flow_text(text)
    state = _default_state() if scope == "shipped" else read_state(root, name)
    return {"scope": scope, "name": name, "version": version, "flow": flow, "text": text, "state": state}


def list_versions(roots: Mapping[str, Optional[Path]], scope: str, name: str) -> Dict[str, Any]:
    root = _root(roots, scope)
    if not working_file(root, name).is_file():
        raise FlowStoreError(f"flow {name} introuvable ({scope})", 404)
    history = read_history(roots, scope, name)
    by_version = {h["version"]: h.get("user") for h in history if isinstance(h.get("version"), int)}
    versions = []
    for n in reversed(_version_numbers(root, name)):
        st = version_file(root, name, n).stat()
        versions.append({"version": n, "at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                         "size": st.st_size, "user": by_version.get(n)})
    return {"scope": scope, "name": name, "state": read_state(root, name), "versions": versions,
            "history": history}


def read_history(roots: Mapping[str, Optional[Path]], scope: str, name: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Last *limit* history.jsonl lines of *name* (who, when, what), newest first; [] for perso."""
    path = history_path(roots, scope)
    if path is None or not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("flow") == name:
            out.append(entry)
    return list(reversed(out[-limit:]))


# -- write --------------------------------------------------------------------

def _check_revision(state: Dict[str, Any], base_revision: Optional[int], exists: bool) -> None:
    if base_revision is None:
        if exists:
            raise FlowStoreError("un flow de ce nom existe deja", 409,
                                 {"exists": True, "revision": state["revision"],
                                  "by": state["saved_by"], "at": state["saved_at"]})
        return
    if exists and int(base_revision) != int(state["revision"]):
        raise FlowStoreError("le flow a ete enregistre entre-temps", 409,
                             {"revision": state["revision"], "by": state["saved_by"], "at": state["saved_at"]})


def _write_working(root: Path, scope: str, flow: Flow, state: Dict[str, Any], user: str,
                   valid: Optional[bool] = None) -> Dict[str, Any]:
    text = dump_flow(flow, scope=scope, version=state["current"] or None, active=bool(state["active"]))
    _write_text(working_file(root, flow.name), text)
    state.update(revision=int(state["revision"]) + 1, saved_by=user, saved_at=_now())
    if valid is not None:
        state["valid"] = bool(valid)
    _write_state(root, flow.name, state)
    return state


def save_flow(roots: Mapping[str, Optional[Path]], scope: str, flow: Flow, *, user: str,
              base_revision: Optional[int] = None, force: bool = False, note: str = "",
              valid: Optional[bool] = None, extra_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Enregistrer: overwrite the working file. ``base_revision`` None = a new flow
    (Nouveau, Enregistrer sous): refused if the name exists. ``force`` skips the
    conflict check (the user chose to overwrite after a 409). ``valid`` = result of
    the validation (P4), kept in state.json; ``extra_state`` = more state keys."""
    _require_writable(scope)
    root = _root(roots, scope)
    name = flow.name
    flow_folder(root, name).mkdir(parents=True, exist_ok=True)
    with _flow_lock(root, name):
        state = read_state(root, name)
        if not force:
            _check_revision(state, base_revision, working_file(root, name).is_file())
        state.update(extra_state or {})
        state = _write_working(root, scope, flow, state, user, valid)
    _history(roots, scope, {"kind": "save", "user": user, "flow": name, "revision": state["revision"],
                            "version": state["current"] or None, "note": note})
    return state


def _freeze(root: Path, scope: str, name: str, state: Dict[str, Any], user: str) -> Optional[int]:
    """Copy the working file to v(max+1) if it differs from the last frozen version."""
    text = working_file(root, name).read_text(encoding="utf-8")
    numbers = _version_numbers(root, name)
    if state["current"] and state["current"] in numbers:
        last = version_file(root, name, state["current"]).read_text(encoding="utf-8")
        if _canonical(last) == _canonical(text):
            return None
    new = (max(numbers) if numbers else 0) + 1
    flow = load_flow_text(text)
    _write_text(version_file(root, name, new), dump_flow(flow, scope=scope, version=new))
    state["current"] = new
    _write_working(root, scope, flow, state, user)
    return new


def increment_flow(roots: Mapping[str, Optional[Path]], scope: str, name: str, *, user: str,
                   flow: Optional[Flow] = None, base_revision: Optional[int] = None,
                   force: bool = False, note: str = "", valid: Optional[bool] = None) -> Dict[str, Any]:
    """Enregistrer et incrementer: optional save of *flow*, then freeze a version
    only if the content changed. Returns ``{state, created}``."""
    _require_writable(scope)
    root = _root(roots, scope)
    if flow is not None and flow.name != name:
        raise FlowStoreError("le nom du flow ne correspond pas a l'adresse")
    flow_folder(root, name).mkdir(parents=True, exist_ok=True)
    with _flow_lock(root, name):
        state = read_state(root, name)
        exists = working_file(root, name).is_file()
        if flow is not None:
            if not force:
                _check_revision(state, base_revision, exists)
            state = _write_working(root, scope, flow, state, user, valid)
        elif not exists:
            raise FlowStoreError(f"flow {name} introuvable ({scope})", 404)
        from_version = state["current"] or None
        created = _freeze(root, scope, name, state, user)
    if flow is not None:
        _history(roots, scope, {"kind": "save", "user": user, "flow": name,
                                "revision": state["revision"], "note": note})
    if created:
        _history(roots, scope, {"kind": "increment", "user": user, "flow": name, "version": created,
                                "from_version": from_version, "note": note})
    return {"state": state, "created": created}


def revert_flow(roots: Mapping[str, Optional[Path]], scope: str, name: str, version: int, *,
                user: str, validator: Optional[Callable[[Flow], bool]] = None) -> Dict[str, Any]:
    """Revenir a vN: the working file becomes vN and is frozen as v(max+1)
    (nothing is lost; no new version if vN is already the latest content)."""
    _require_writable(scope)
    root = _root(roots, scope)
    with _flow_lock(root, name):
        try:
            text = version_file(root, name, version).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FlowStoreError(f"version {version} de {name} introuvable", 404) from None
        state = read_state(root, name)
        from_version = state["current"] or None
        restored = load_flow_text(text)
        state = _write_working(root, scope, restored, state, user, validator(restored) if validator else None)
        created = _freeze(root, scope, name, state, user)
    _history(roots, scope, {"kind": "revert", "user": user, "flow": name, "version": created or state["current"],
                            "from_version": from_version, "to_version": version, "note": ""})
    return {"state": state, "created": created}


def delete_flow(roots: Mapping[str, Optional[Path]], scope: str, name: str, *, user: str) -> Dict[str, Any]:
    """Move the working file and the folder to <scope>/_trash/<name>_<date>/.
    On a team copy of a shipped flow this is "Revenir au defaut"."""
    _require_writable(scope)
    root = _root(roots, scope)
    if not working_file(root, name).is_file():
        raise FlowStoreError(f"flow {name} introuvable ({scope})", 404)
    trash = root / "_trash" / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    with _flow_lock(root, name):
        trash.mkdir(parents=True, exist_ok=True)
        os.replace(working_file(root, name), trash / f"{name}{SUFFIX}")
    # Outside the lock: the lock file lives in the folder being moved.
    folder = flow_folder(root, name)
    if folder.is_dir():
        shutil.move(str(folder), str(trash / name))
    _history(roots, scope, {"kind": "delete", "user": user, "flow": name, "trash": trash.name, "note": ""})
    return {"trash": str(trash)}


def copy_flow(roots: Mapping[str, Optional[Path]], name: str, from_scope: str, to_scope: str, *,
              user: str, new_name: Optional[str] = None) -> Dict[str, Any]:
    """Copy the working file of a flow to another scope (unlock of a shipped flow =
    copy to team; Enregistrer sous elsewhere). Refused if the target exists."""
    src = read_flow(roots, from_scope, name)
    flow = src["flow"].model_copy(update={"name": _check_name(new_name or name)})
    # Unlock: remember which shipped content the copy started from (W_SHIPPED_CHANGED, P4).
    extra = {"shipped_hash": shipped_hash(src["text"])} if from_scope == "shipped" and flow.name == name else None
    state = save_flow(roots, to_scope, flow, user=user, note=f"copie de {from_scope}/{name}", extra_state=extra)
    return {"state": state, "scope": to_scope, "name": flow.name}


# State keys that belong to the old place: the activation gate is passed again in the new one.
_RELOCATE_DROP = ("acked", "dry_run_ok", "shipped_hash")


def relocate_flow(roots: Mapping[str, Optional[Path]], name: str, from_scope: str, to_scope: str, *,
                  user: str, new_name: Optional[str] = None) -> Dict[str, Any]:
    """Rename (same scope) or move to another scope (ADR 0069): the working file, every
    frozen version and the state go along, renamed; the flow arrives inactive (rights and
    triggers differ, the activation gate is passed again there); the old one goes to the
    trash of its scope. Refused when the target name exists in the target scope."""
    _require_writable(from_scope)
    _require_writable(to_scope)
    src, dst = _root(roots, from_scope), _root(roots, to_scope)
    new = _check_name(new_name or name)
    if (from_scope, name) == (to_scope, new):
        raise FlowStoreError("meme nom et meme portee : rien a changer", 400)
    if not working_file(src, name).is_file():
        raise FlowStoreError(f"flow {name} introuvable ({from_scope})", 404)
    if working_file(dst, new).exists() or flow_folder(dst, new).exists():
        raise FlowStoreError(f"un flow {new} existe deja ({to_scope})", 409)
    with _flow_lock(src, name):
        flow = load_flow_text(working_file(src, name).read_text(encoding="utf-8")).model_copy(update={"name": new})
        state = read_state(src, name)
        versions = {n: version_file(src, name, n).read_text(encoding="utf-8") for n in _version_numbers(src, name)}
        extras = [p for p in flow_folder(src, name).iterdir()
                  if p.name not in ("versions", "state.json") and not p.name.startswith("state.json.")] \
            if flow_folder(src, name).is_dir() else []
    target = flow_folder(dst, new)
    target.mkdir(parents=True, exist_ok=True)
    with _flow_lock(dst, new):
        for number, text in versions.items():
            frozen = load_flow_text(text).model_copy(update={"name": new})
            _write_text(version_file(dst, new, number), dump_flow(frozen, scope=to_scope, version=number))
        for extra in extras:      # watcher memories (seen_<node>.json...) follow the flow
            (shutil.copytree if extra.is_dir() else shutil.copy2)(extra, target / extra.name)
        for key in _RELOCATE_DROP:
            state.pop(key, None)
        state.update(active=False, active_version=None)
        state = _write_working(dst, to_scope, flow, state, user)
    trash = delete_flow(roots, from_scope, name, user=user)["trash"]
    kind = "rename" if from_scope == to_scope else "move"
    _history(roots, to_scope, {"kind": kind, "user": user, "flow": new, "from": f"{from_scope}/{name}", "note": ""})
    if from_scope != to_scope:
        _history(roots, from_scope, {"kind": kind, "user": user, "flow": name, "to": f"{to_scope}/{new}", "note": ""})
    return {"state": state, "scope": to_scope, "name": new, "trash": trash}


def set_active(roots: Mapping[str, Optional[Path]], scope: str, name: str, active: bool, *,
               user: str) -> Dict[str, Any]:
    """Activate the latest frozen version, or deactivate. P1 only enforces the
    format rules (a legacy_* flow never activates: the publish still runs on v1,
    01 §16); validation and dry run come with P4 / P5."""
    _require_writable(scope)
    root = _root(roots, scope)
    if active and name.startswith(LEGACY_PREFIX):
        raise FlowStoreError("un flow legacy_* ne s'active pas : le publish tourne encore sur les actions v1", 409)
    with _flow_lock(root, name):
        if not working_file(root, name).is_file():
            raise FlowStoreError(f"flow {name} introuvable ({scope})", 404)
        state = read_state(root, name)
        if active and not state["current"]:
            raise FlowStoreError("aucune version figee : Enregistrer et incrementer d'abord", 409)
        state.update(active=bool(active), active_version=state["current"] if active else state["active_version"])
        _write_state(root, name, state)
    _history(roots, scope, {"kind": "activate" if active else "deactivate", "user": user, "flow": name,
                            "version": state["active_version"], "note": ""})
    return state


# -- P5: scheduler side (01 §9) ----------------------------------------------------

def update_state(root: Path, name: str, change) -> Optional[Dict[str, Any]]:
    """Apply ``change(state) -> bool`` to state.json under the flow lock; written only
    when it returns True. Returns the new state, or None when nothing was written."""
    with _flow_lock(root, name):
        state = read_state(root, name)
        if not change(state):
            return None
        _write_state(root, name, state)
    return state


def active_names(root: Path) -> List[Tuple[str, int]]:
    """(name, active_version) of the active flows kept in *root* (a scope folder)."""
    out: List[Tuple[str, int]] = []
    try:
        entries = sorted(root.glob(f"*{SUFFIX}"))
    except OSError:
        return out
    for path in entries:
        name = path.name[: -len(SUFFIX)]
        if not NAME_RE.match(name):
            continue
        state = read_state(root, name)
        if state.get("active") and state.get("active_version"):
            out.append((name, int(state["active_version"])))
    return out
