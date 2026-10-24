# registry.py — the @flow_node registry (01_ARCHITECTURE §1, 02_NODES §1).
#
# A node type is "<family>.<name>" with documented ports (doc_fr / doc_en /
# example), a Shelf rank and Tab-search aliases. FLUX's own node types live in
# one module per family (BUILTIN_MODULES, imported by ensure_builtin); team nodes
# come from CONFIG/extensions/nodes/*.py. The loader
# only imports a file that contains "@flow_node": the v1 CONFIG/nodes files copied
# there stay inert (they belong to flux_core).
#
# Team nodes run with FLUX's own rights (gap to ADR 0014, assumed by ADR 0057).
#
# Body contract (nodes/contract.py): ``func(ctx, inputs, params) -> outputs``; a
# node with an effect (``effect=True`` or destructive) must give ``simulate``
# with the same signature returning ``{lines, outputs}`` (dry run, 01 §5).

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
BUILTIN_MODULES: Tuple[str, ...] = (
    "flux_flows.nodes.event", "flux_flows.nodes.data", "flux_flows.nodes.logic",
    "flux_flows.nodes.operator", "flux_flows.nodes.action", "flux_flows.nodes.flux",
    "flux_flows.nodes.subflow", "flux_flows.nodes.bridge", "flux_flows.nodes.dcc_houdini",
    "flux_flows.nodes.dcc_maya", "flux_flows.nodes.headless", "flux_flows.nodes.dcc_publish", "flux_flows.nodes.dcc_softs",
    "flux_flows.nodes.page_nodes",
    "flux_flows.nodes.dcc_extension",
)
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
    # Editor hints (params): the allowed values of a choice param, in menu order;
    # wirable=False = a constant (never promoted to an input, no link into it);
    # tokens = a project token section (CLASS, NAME, TYPE, SEQ...) offered in a menu.
    choices: Optional[Tuple[Any, ...]] = None
    wirable: bool = True
    tokens: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "type": self.type, "doc_fr": self.doc_fr, "doc_en": self.doc_en,
                "example": self.example, "required": self.required, "default": self.default,
                "choices": list(self.choices) if self.choices is not None else None,
                "wirable": self.wirable, "tokens": self.tokens}


def port(name: str, type: str, doc_fr: str = "", doc_en: str = "", example: Any = None,
         required: bool = False, default: Any = None, *, choices: Optional[Iterable[Any]] = None,
         wirable: bool = True, tokens: Optional[str] = None) -> Port:
    return Port(name, type, doc_fr, doc_en, example, required, default,
                tuple(choices) if choices is not None else None, bool(wirable), tokens or None)


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
    effect: bool = False                # acts on the world: simulated in a dry run
    # DCC flags (02 §1), read by the validation (P4); the nodes using them come in P6.
    session: Optional[str] = None       # S:<soft>: the "session" input must be linked (E_NO_SESSION)
    live_only: bool = False             # L: refused on a headless session (E_LIVE_ONLY)
    licence: Any = None                 # $: True, or {"param": .., "equals": ..} like destructive (W_LICENCE)
    raw: Tuple[str, ...] = ()           # params the engine does not resolve ({token}, $FLUX, ${var})
    source: str = "flux"                # flux | team
    file: str = ""
    func: Optional[Callable[..., Any]] = None
    simulate: Optional[Callable[..., Any]] = None
    # P6a: internal = the core leaf of a DCC subflow node, hidden from Tab / Shelf;
    # subflow = {name, scope, locked, shipped} of a node shipped as a locked subflow (dcc_nodes.py).
    internal: bool = False
    subflow: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type, "label": self.label, "family": self.family, "icon": self.icon,
            "inputs": [p.to_dict() for p in self.inputs], "outputs": [p.to_dict() for p in self.outputs],
            "params": [p.to_dict() for p in self.params], "shelf": self.shelf, "aliases": list(self.aliases),
            "doc_fr": self.doc_fr, "doc_en": self.doc_en, "destructive": self.destructive,
            "effect": self.effect, "raw": list(self.raw), "source": self.source, "file": self.file,
            "session": self.session, "live_only": self.live_only, "licence": self.licence,
            "internal": self.internal, "subflow": self.subflow,
        }


def flag_on(flag: Any, spec: "NodeSpec", params: Dict[str, Any]) -> bool:
    """Is a conditional flag (destructive, licence) true for these params?
    ``{"param": p, "equals": v}`` compares the param, or its default when unset."""
    if not flag:
        return False
    if not isinstance(flag, dict):
        return True
    name = flag.get("param")
    if name in params:
        value = params[name]
    else:
        value = next((p.default for p in (*spec.params, *spec.inputs) if p.name == name), None)
    return value == flag.get("equals")


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
              effect: bool = False, simulate: Optional[Callable[..., Any]] = None,
              raw: Iterable[str] = (), session: Optional[str] = None, live_only: bool = False,
              licence: Any = None, internal: bool = False,
              ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare a node type. The decorated function is its body (run by the engine)."""
    if not NODE_TYPE_RE.match(type):
        raise NodeDefinitionError(f"type '{type}' : attendu <famille>.<nom>")
    family = type.split(".", 1)[0]
    if family not in FAMILIES:
        raise NodeDefinitionError(f"{type} : famille '{family}' inconnue ({', '.join(FAMILIES)})")
    effect = bool(effect or destructive)
    if effect and simulate is None:
        raise NodeDefinitionError(f"{type} : un node a effet doit definir simulate (essai a blanc)")
    spec = NodeSpec(
        type=type, label=label, family=family, icon=icon,
        inputs=_check_ports(type, "entree", inputs), outputs=_check_ports(type, "sortie", outputs),
        params=_check_ports(type, "parametre", params), shelf=shelf, aliases=list(aliases),
        doc_fr=doc_fr, doc_en=doc_en, destructive=destructive, effect=effect, simulate=simulate,
        raw=tuple(raw), session=session, live_only=bool(live_only), licence=licence, internal=bool(internal),
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


_BUILTIN_SENTINEL = "event.manual"


def ensure_builtin() -> None:
    """Import FLUX's own node modules (they register on import). Re-imports them
    when a test emptied the registry behind our back."""
    if _BUILTIN_SENTINEL in _REGISTRY:
        return
    with _LOCK:
        if _BUILTIN_SENTINEL in _REGISTRY:
            return
        for node_type in [t for t, s in _REGISTRY.items() if s.func and s.func.__module__ in BUILTIN_MODULES]:
            del _REGISTRY[node_type]
        for name in BUILTIN_MODULES:
            if name in sys.modules:
                importlib.reload(sys.modules[name])
            else:
                importlib.import_module(name)


def get_core(node_type: str) -> Optional[NodeSpec]:
    """A node registered in Python (FLUX or team), never a DCC subflow node."""
    ensure_builtin()
    with _LOCK:
        return _REGISTRY.get(node_type)


def get_node(node_type: str) -> Optional[NodeSpec]:
    """Python nodes first, then the DCC nodes shipped as locked subflows (dcc_nodes.py)."""
    spec = get_core(node_type)
    if spec is not None:
        return spec
    from flux_flows import dcc_nodes

    return dcc_nodes.get_spec(node_type)


def all_nodes() -> List[NodeSpec]:
    from flux_flows import dcc_nodes

    ensure_builtin()
    with _LOCK:
        nodes = dict(_REGISTRY)
    for node_type, spec in dcc_nodes.specs().items():
        nodes.setdefault(node_type, spec)
    return sorted(nodes.values(), key=lambda s: (FAMILIES.index(s.family), s.type))


@dataclass
class _TeamFile:
    sig: Tuple[float, int]
    types: List[str]
    error: Optional[str] = None


# Loaded team files by name: a file is re-imported only when it changed (hot reload per file).
_TEAM_FILES: Dict[str, _TeamFile] = {}


def _file_sig(path: Path) -> Optional[Tuple[float, int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime, st.st_size


def _unload_team_file(name: str) -> None:
    entry = _TEAM_FILES.pop(name, None)
    for node_type in entry.types if entry else ():
        spec = _REGISTRY.get(node_type)
        if spec is not None and spec.source == "team" and spec.file == name:
            del _REGISTRY[node_type]
    sys.modules.pop(_TEAM_MODULE_PREFIX + Path(name).stem, None)


def _import_team_file(path: Path, sig: Tuple[float, int]) -> _TeamFile:
    try:
        if MARKER not in path.read_text(encoding="utf-8", errors="replace"):
            return _TeamFile(sig, [])
    except OSError as exc:
        return _TeamFile(sig, [], str(exc))
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
        return _TeamFile(sig, [], f"{type(exc).__name__}: {exc}")
    finally:
        _LOADING.pop("file", None)
    return _TeamFile(sig, sorted(set(_REGISTRY) - before))


def load_team_nodes(folder: Optional[Path]) -> List[Dict[str, str]]:
    """(Re)import the team node files of *folder* that changed, one file at a time.

    Returns ``node_errors``: one ``{file, error}`` per file that failed; the other
    files still load. A file without the "@flow_node" marker is never imported.
    """
    ensure_builtin()   # a team file can never take a FLUX node type
    files = {p.name: p for p in sorted(folder.glob("*.py"))} if folder and folder.is_dir() else {}
    with _LOCK:
        for name in [n for n in _TEAM_FILES if n not in files]:
            _unload_team_file(name)
        for name, path in files.items():
            sig = _file_sig(path)
            entry = _TEAM_FILES.get(name)
            if sig is None:
                _unload_team_file(name)
                continue
            if entry and entry.sig == sig and all(t in _REGISTRY for t in entry.types):
                continue
            _unload_team_file(name)
            _TEAM_FILES[name] = _import_team_file(path, sig)
        return [{"file": n, "error": e.error} for n, e in sorted(_TEAM_FILES.items()) if e.error]


def catalog(team_folder: Optional[Path]) -> Dict[str, Any]:
    """Body of GET /flows/catalog."""
    errors = load_team_nodes(team_folder)
    return {
        "nodes": [s.to_dict() for s in all_nodes()],
        "families": list(FAMILIES),
        "types": catalog_types(),
        "node_errors": errors,
    }
