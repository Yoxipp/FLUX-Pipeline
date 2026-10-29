# page_store.py — TOOL pages by scope (04_PAGES_TOOL §2, A16).
#
# Layout of a pages folder P (locations.page_roots):
#   P/<id>.yml                       the page (one file, no numbered versions)
#   P/_history/<id>_<stamp>.yml      the previous file, copied before each overwrite (last 20)
#   P/_trash/<id>_<stamp>.yml        deleted pages
# shipped/pages/ holds the read-only templates (menu "Modele"), never listed in TOOL.
#
# rev = hash of the file text. A save sends the rev it loaded: another write since
# then = 409 "page modifiee par <artiste>". No rev = a new page: 409 if the id exists.
# Writes: append_lock on the page file (safe across machines), temp file + os.replace.
# The scope history.jsonl (the one of the flows) gets a page_save / page_delete line.
# Rights are checked by the router (rights.ADMIN), never here.

from __future__ import annotations

import hashlib
import socket
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional

from flux_flows.model import NAME_RE
from flux_flows.pages import SCOPES, Page, PageSchemaError, dump_page, load_page_text
from flux_flows.store import FlowStoreError, _write_text

SUFFIX = ".yml"
RESOLVE_ORDER = ("project", "team")      # project > team (04 §2)
HISTORY_KEEP = 20


def _root(roots: Mapping[str, Optional[Path]], scope: str) -> Path:
    if scope not in SCOPES + ("shipped",):
        raise FlowStoreError(f"portee de page inconnue '{scope}' (team ou project)")
    root = roots.get(scope)
    if root is None:
        raise FlowStoreError(f"portee {scope} indisponible (pas de projet ouvert)")
    return Path(root)


def _check_id(page_id: str) -> str:
    if not NAME_RE.match(page_id or ""):
        raise FlowStoreError(f"id de page invalide '{page_id}'")
    return page_id


def page_file(root: Path, page_id: str) -> Path:
    path = Path(root) / f"{_check_id(page_id)}{SUFFIX}"
    resolved, base = path.resolve(), Path(root).resolve()
    if base not in resolved.parents:
        raise FlowStoreError("chemin hors du dossier des pages", 400)
    return path


def rev_of(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _history_path(roots: Mapping[str, Optional[Path]], scope: str) -> Optional[Path]:
    # Same file as the flows of the scope: CONFIG/extensions/history.jsonl, _flux_setup/flows/history.jsonl.
    root = roots.get(scope)
    if root is None or scope not in SCOPES:
        return None
    return Path(root).parent / "history.jsonl" if scope == "team" else Path(root).parent / "flows" / "history.jsonl"


def _history(roots: Mapping[str, Optional[Path]], scope: str, kind: str, page_id: str, user: str,
             **extra: Any) -> None:
    path = _history_path(roots, scope)
    if path is None:
        return
    from core.json_manager import append_jsonl

    append_jsonl(path, [{"at": _now(), "user": user, "host": socket.gethostname(), "kind": kind,
                         "scope": scope, "page": page_id, **extra}])


def last_writer(roots: Mapping[str, Optional[Path]], scope: str, page_id: str) -> Dict[str, Any]:
    """{by, at} of the last page_save of *page_id* (the 409 message)."""
    path = _history_path(roots, scope)
    if path is None or not path.is_file():
        return {"by": None, "at": None}
    from core.json_manager import read_jsonl

    for line in reversed(read_jsonl(path)):
        if line.get("page") == page_id and str(line.get("kind", "")).startswith("page_"):
            return {"by": line.get("user"), "at": line.get("at")}
    return {"by": None, "at": None}


@contextmanager
def _lock(root: Path, page_id: str) -> Iterator[None]:
    from core.json_manager import append_lock

    root.mkdir(parents=True, exist_ok=True)
    with append_lock(page_file(root, page_id)):
        yield


# -- read ---------------------------------------------------------------------

def _read(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        page: Optional[Page] = load_page_text(text)
        error = None
    except PageSchemaError as exc:   # listed with its error so a TD can fix the file
        page, error = None, str(exc)
    return {"page": page, "rev": rev_of(text), "error": error}


def resolve(roots: Mapping[str, Optional[Path]], page_id: str) -> Optional[str]:
    """Scope that wins for *page_id*: project > team."""
    _check_id(page_id)
    for scope in RESOLVE_ORDER:
        root = roots.get(scope)
        if root is not None and page_file(Path(root), page_id).is_file():
            return scope
    return None


def _entry(scope: str, path: Path) -> Dict[str, Any]:
    got = _read(path)
    page = got["page"]
    return {"id": path.stem, "scope": scope, "rev": got["rev"], "error": got["error"],
            "label": page.label if page else path.stem, "icon": page.icon if page else "wrench",
            "description": page.description if page else ""}


def _files(root: Optional[Path]) -> List[Path]:
    if root is None or not Path(root).is_dir():
        return []
    return sorted(p for p in Path(root).iterdir()
                  if p.is_file() and p.suffix == SUFFIX and NAME_RE.match(p.stem))


def list_pages(roots: Mapping[str, Optional[Path]]) -> List[Dict[str, Any]]:
    """Pages of team and project; a team page hidden by a project page of the same id
    is kept with ``shadowed`` (the editor shows it tagged)."""
    out: List[Dict[str, Any]] = []
    winners: set = set()
    for scope in RESOLVE_ORDER:
        for path in _files(roots.get(scope)):
            entry = _entry(scope, path)
            entry["shadowed"] = path.stem in winners
            winners.add(path.stem)
            out.append(entry)
    return out


def list_templates(roots: Mapping[str, Optional[Path]]) -> List[Dict[str, Any]]:
    return [_entry("shipped", p) for p in _files(roots.get("shipped"))]


def read_page(roots: Mapping[str, Optional[Path]], scope: str, page_id: str) -> Dict[str, Any]:
    path = page_file(_root(roots, scope), page_id)
    if not path.is_file():
        raise FlowStoreError(f"page {page_id} introuvable ({scope})", 404)
    got = _read(path)
    if got["page"] is None:
        raise FlowStoreError(f"page {page_id} illisible : {got['error']}", 422, {"rev": got["rev"]})
    return got


# -- write --------------------------------------------------------------------

def _require_writable(scope: str) -> None:
    if scope not in SCOPES:
        raise FlowStoreError("les modeles livres sont en lecture seule : cree une page depuis le modele", 403)


def _history_files(folder: Path, page_id: str) -> List[Path]:
    # <id>_<stamp>: the stamp starts with a digit, so "team" never takes "team_board_...".
    if not folder.is_dir():
        return []
    return sorted(f for f in folder.glob(f"{page_id}_*{SUFFIX}") if f.stem[len(page_id) + 1:][:1].isdigit())


def _keep_history(root: Path, page_id: str, path: Path) -> None:
    folder = root / "_history"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    _write_text(folder / f"{page_id}_{stamp}{SUFFIX}", path.read_text(encoding="utf-8"))
    old = _history_files(folder, page_id)
    for extra in old[:-HISTORY_KEEP]:
        try:
            extra.unlink()
        except OSError:
            pass


def save_page(roots: Mapping[str, Optional[Path]], scope: str, page: Page, *, user: str,
              base_rev: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Write *page*; returns {rev, changed}. 409 on a conflicting rev (unless force)."""
    _require_writable(scope)
    root = _root(roots, scope)
    text = dump_page(page, scope=scope)
    with _lock(root, page.id):
        path = page_file(root, page.id)
        exists = path.is_file()
        if exists and not force:
            current = rev_of(path.read_text(encoding="utf-8"))
            if base_rev is None:
                raise FlowStoreError(f"la page {page.id} existe deja ({scope})", 409, {"rev": current, "exists": True})
            if base_rev != current:
                who = last_writer(roots, scope, page.id)
                raise FlowStoreError(f"page modifiee par {who['by'] or 'un autre poste'}", 409,
                                     {"rev": current, **who})
        if exists:
            old = path.read_text(encoding="utf-8")
            if old == text:
                return {"rev": rev_of(text), "changed": False}
            _keep_history(root, page.id, path)
        _write_text(path, text)
    _history(roots, scope, "page_save", page.id, user, rev=rev_of(text))
    return {"rev": rev_of(text), "changed": True}


def delete_page(roots: Mapping[str, Optional[Path]], scope: str, page_id: str, *, user: str) -> Dict[str, Any]:
    _require_writable(scope)
    root = _root(roots, scope)
    with _lock(root, page_id):
        path = page_file(root, page_id)
        if not path.is_file():
            raise FlowStoreError(f"page {page_id} introuvable ({scope})", 404)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        trash = root / "_trash" / f"{page_id}_{stamp}{SUFFIX}"
        trash.parent.mkdir(parents=True, exist_ok=True)
        path.replace(trash)
    _history(roots, scope, "page_delete", page_id, user)
    return {"trash": str(trash)}


def list_history(roots: Mapping[str, Optional[Path]], scope: str, page_id: str) -> List[Dict[str, Any]]:
    """Copies kept in _history/, recent first: {file, at}."""
    files = reversed(_history_files(_root(roots, scope) / "_history", _check_id(page_id)))
    return [{"file": f.name, "at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")}
            for f in files]


def flow_lookup(flow_roots: Mapping[str, Optional[Path]]):
    """name -> FlowInfo for validate_page: the winning scope, the active version when the
    flow is active (what a button runs, A7), else its working file."""
    from flux_flows import store
    from flux_flows.pages import FlowInfo

    def lookup(name: str) -> Optional[FlowInfo]:
        try:
            scope = store.resolve(flow_roots, name)
            if scope is None:
                return None
            got = store.read_flow(flow_roots, scope, name)
            state = got["state"]
            active = bool(state.get("active") and state.get("active_version"))
            flow = got["flow"]
            if active and scope != "shipped":
                flow = store.read_flow(flow_roots, scope, name, state["active_version"])["flow"]
            return FlowInfo(scope=scope, flow=flow, active=active, valid=state.get("valid"))
        except (FlowStoreError, ValueError):
            return None

    return lookup
