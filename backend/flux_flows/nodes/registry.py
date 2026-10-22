# registry.py — the @flow_node registry (01_ARCHITECTURE §1, 02_NODES §1).
#
# A node type is "<family>.<name>" with documented ports (doc_fr / doc_en /
# example), a Shelf rank and Tab-search aliases. FLUX ships no node type in P1
# (02 §1 "Phases"); team nodes come from CONFIG/extensions/nodes/*.py. The loader
# only imports a file that contains "@flow_node": the v1 CONFIG/nodes files copied
# there stay inert (they belong to flux_core).
#
# Team nodes run with FLUX's own rights (gap to ADR 0014, assumed by ADR 0057).

from __future__ import annotations

import importlib.util
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from flux_flows.model import NODE_TYPE_RE
from flux_flows.types import catalog_types, is_valid_type

FAMILIES: Tuple[str, ...] = (
    "event", "data", "logic", "operator", "action", "flux", "session", "dcc", "bridge", "subflow",
)
MARKER = "@flow_node"
_TEAM_MODULE_PREFIX = "flux_flows_team_nodes."


class NodeDefinitionError(ValueError):
    """A @flow_node declaration is wrong. The message names the node type."""


@dataclass(frozen=True)
class Port:
    name: str
    type: str
    doc_fr: str = ""
    doc_en: str = ""
    example: Any = None
    required: bool = False
    default: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "type": self.type, "doc_fr": self.doc_fr, "doc_en": self.doc_en,
                "example": self.example, "required": self.required, "default": self.default}


def port(name: str, type: str, doc_fr: str = "", doc_en: str = "", example: Any = None,
         required: bool = False, default: Any = None) -> Port:
    return Port(name, type, doc_fr, doc_en, example, required, default)


@dataclass
class NodeSpec:
    type: str
    label: str
    family: str
    icon: str = ""
    inputs: List[Port] = field(default_factory=list)
    outputs: List[Port] = field(default_factory=list)
    params: List[Port] = field(default_factory=list)
    shelf: Optional[int] = None
    aliases: List[str] = field(default_factory=list)
    doc_fr: str = ""
    doc_en: str = ""
    destructive: Any = None             # True, or {"param": .., "equals": ..}
    source: str = "flux"                # flux | team
    file: str = ""
    func: Optional[Callable[..., Any]] = None
    simulate: Optional[Callable[..., Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type, "label": self.label, "family": self.family, "icon": self.icon,
            "inputs": [p.to_dict() for p in self.inputs], "outputs": [p.to_dict() for p in self.outputs],
            "params": [p.to_dict() for p in self.params], "shelf": self.shelf, "aliases": list(self.aliases),
            "doc_fr": self.doc_fr, "doc_en": self.doc_en, "destructive": self.destructive,
            "source": self.source, "file": self.file,
        }


_REGISTRY: Dict[str, NodeSpec] = {}
_LOCK = threading.RLock()
# Set while a team file is imported, so its nodes are tagged with it.
_LOADING: Dict[str, str] = {}


def _check_ports(node_type: str, kind: str, ports: Iterable[Port]) -> List[Port]:
    out, names = [], set()
    for p in ports:
        if not isinstance(p, Port):
            raise NodeDefinitionError(f"{node_type} : {kind} doit etre declare avec port()")
        if p.name in names:
            raise NodeDefinitionError(f"{node_type} : {kind} '{p.name}' en double")
        if not is_valid_type(p.type):
            raise NodeDefinitionError(f"{node_type} : {kind} '{p.name}' a un type inconnu '{p.type}'")
        names.add(p.name)
        out.append(p)
    return out


def flow_node(type: str, label: str, *, icon: str = "", inputs: Iterable[Port] = (),
              outputs: Iterable[Port] = (), params: Iterable[Port] = (), shelf: Optional[int] = None,
              aliases: Iterable[str] = (), doc_fr: str = "", doc_en: str = "", destructive: Any = None,
              simulate: Optional[Callable[..., Any]] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare a node type. The decorated function is its body (run by the engine, P2)."""
    if not NODE_TYPE_RE.match(type):
        raise NodeDefinitionError(f"type '{type}' : attendu <famille>.<nom>")
    family = type.split(".", 1)[0]
    if family not in FAMILIES:
        raise NodeDefinitionError(f"{type} : famille '{family}' inconnue ({', '.join(FAMILIES)})")
    spec = NodeSpec(
        type=type, label=label, family=family, icon=icon,
        inputs=_check_ports(type, "entree", inputs), outputs=_check_ports(type, "sortie", outputs),
        params=_check_ports(type, "parametre", params), shelf=shelf, aliases=list(aliases),
        doc_fr=doc_fr, doc_en=doc_en, destructive=destructive, simulate=simulate,
    )

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        spec.func = func
        loading = _LOADING.get("file")
        if loading:
            spec.source, spec.file = "team", loading
        with _LOCK:
            if type in _REGISTRY:
                raise NodeDefinitionError(f"{type} : deja declare ({_REGISTRY[type].file or 'FLUX'})")
            _REGISTRY[type] = spec
        return func

    return decorate


def get_node(node_type: str) -> Optional[NodeSpec]:
    with _LOCK:
        return _REGISTRY.get(node_type)


def all_nodes() -> List[NodeSpec]:
    with _LOCK:
        return sorted(_REGISTRY.values(), key=lambda s: (FAMILIES.index(s.family), s.type))


def _drop_team_nodes() -> None:
    for node_type in [t for t, s in _REGISTRY.items() if s.source == "team"]:
        del _REGISTRY[node_type]
    for mod in [m for m in sys.modules if m.startswith(_TEAM_MODULE_PREFIX)]:
        del sys.modules[mod]


_TEAM_SIG: Optional[Tuple[Tuple[str, float, int], ...]] = None
_TEAM_ERRORS: List[Dict[str, str]] = []


def _signature(files: List[Path]) -> Tuple[Tuple[str, float, int], ...]:
    out = []
    for f in files:
        try:
            st = f.stat()
            out.append((f.name, st.st_mtime, st.st_size))
        except OSError:
            continue
    return tuple(out)


def load_team_nodes(folder: Optional[Path]) -> List[Dict[str, str]]:
    """(Re)import the team node files of *folder* when they changed.

    Returns ``node_errors``: one ``{file, error}`` per file that failed; the other
    files still load. A file without the "@flow_node" marker is never imported.
    """
    global _TEAM_SIG, _TEAM_ERRORS
    files = sorted(folder.glob("*.py")) if folder and folder.is_dir() else []
    sig = _signature(files)
    with _LOCK:
        if sig == _TEAM_SIG:
            return list(_TEAM_ERRORS)
        _drop_team_nodes()
        errors: List[Dict[str, str]] = []
        for path in files:
            try:
                if MARKER not in path.read_text(encoding="utf-8", errors="replace"):
                    continue
            except OSError as exc:
                errors.append({"file": path.name, "error": str(exc)})
                continue
            before = set(_REGISTRY)
            mod_name = _TEAM_MODULE_PREFIX + path.stem
            _LOADING["file"] = path.name
            try:
                spec = importlib.util.spec_from_file_location(mod_name, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
            except Exception as exc:  # a broken team file must not break the catalog
                for node_type in set(_REGISTRY) - before:
                    del _REGISTRY[node_type]
                sys.modules.pop(mod_name, None)
                errors.append({"file": path.name, "error": f"{type(exc).__name__}: {exc}"})
            finally:
                _LOADING.pop("file", None)
        _TEAM_SIG, _TEAM_ERRORS = sig, errors
        return list(errors)


def catalog(team_folder: Optional[Path]) -> Dict[str, Any]:
    """Body of GET /flows/catalog."""
    errors = load_team_nodes(team_folder)
    return {
        "nodes": [s.to_dict() for s in all_nodes()],
        "families": list(FAMILIES),
        "types": catalog_types(),
        "node_errors": errors,
    }
