# model.py — the Flow v2 YAML schema (01_ARCHITECTURE §2, ADR 0057 / 0058).
#
# Design choices:
#   * Strict pydantic schema (``extra="forbid"``): a typo fails loudly with the
#     field path, as in flux_core/loader.py.
#   * ``scope``, ``version`` and ``active`` are written by the store for humans
#     reading the file, and IGNORED on read: the folder and state.json are the truth.
#   * The model checks the shape of a flow, not its meaning. Unknown node types,
#     dangling or incompatible links are accepted here and reported by the
#     validation (P4) so a file the editor saved always reloads (ADR 0058, 5).
#   * Our own emitter (like catalog.render_action_yaml): stable key order, flow
#     style for small records, no anchors or tags, round-trips through safe_load.

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

FORMAT_VERSION = 2
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
FIELD_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
NODE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
NODE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
PORT_REF_RE = re.compile(r"^([a-z][a-z0-9_]{0,30})\.([a-z][a-z0-9_]*)$")
DATA_TYPE_RE = re.compile(r"^[a-z_]+(\[[a-z_*]+\])?$")

# Static routes of /flows: a flow cannot take one of these names.
RESERVED_NAMES = frozenset(
    "catalog runs host nodes pages validate migrate preview events ws rights".split()
)
# Flow variable / interface ids that would shadow $FLUX or a context key.
RESERVED_VARS = frozenset("flux project asset shot seq user date time".split())
INTERFACE_TYPES = frozenset("bool int float str path dir pattern list[str] select".split())
SUBNET_TYPE = "subnet"

MAX_BYTES = 1024 * 1024
MAX_NODES = 500
LABEL_MAX = 80


class FlowSchemaError(ValueError):
    """The text or document is not a valid Flow v2. The message names the field."""


# -- schema -------------------------------------------------------------------

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Origin(_Strict):
    kind: Literal["v1"]
    name: str


class InterfaceInput(_Strict):
    id: str
    type: str
    label: str = ""
    default: Any = None
    options: Optional[List[Any]] = None

    @model_validator(mode="after")
    def _check(self) -> "InterfaceInput":
        if self.type not in INTERFACE_TYPES:
            raise ValueError(f"type '{self.type}' inconnu (attendu : {', '.join(sorted(INTERFACE_TYPES))})")
        if (self.options is not None) != (self.type == "select"):
            raise ValueError("'options' va avec le type select, et seulement lui")
        return self


class InterfaceOutput(_Strict):
    id: str
    type: str
    label: str = ""


class Interface(_Strict):
    inputs: List[InterfaceInput] = []
    outputs: List[InterfaceOutput] = []


class Variable(_Strict):
    name: str
    type: str
    default: Any = None


class Link(_Strict):
    from_: str = Field(alias="from")
    to: str

    @field_validator("from_", "to")
    @classmethod
    def _port_ref(cls, value: str) -> str:
        if not PORT_REF_RE.match(value):
            raise ValueError(f"'{value}' n'est pas de la forme <node>.<port>")
        return value


class Node(_Strict):
    type: str
    pos: Tuple[float, float] = (0, 0)
    params: Dict[str, Any] = {}
    label: Optional[str] = None
    bypass: bool = False
    # Only on a subnet (ADR 0058, 6): its inner network, stored in the same file.
    nodes: Optional[Dict[str, "Node"]] = None
    links: Optional[List[Link]] = None

    @model_validator(mode="after")
    def _check(self) -> "Node":
        if self.type != SUBNET_TYPE and not NODE_TYPE_RE.match(self.type):
            raise ValueError(f"type '{self.type}' : attendu <famille>.<nom> ou {SUBNET_TYPE}")
        if self.type != SUBNET_TYPE and (self.nodes is not None or self.links is not None):
            raise ValueError("'nodes' et 'links' sont reserves au node subnet")
        if self.type == SUBNET_TYPE:
            self.nodes = self.nodes or {}
            self.links = self.links or []
            _check_node_ids(self.nodes)
        return self


class Group(_Strict):
    id: str
    label: str = ""
    nodes: List[str] = []
    color: Optional[str] = None


class Note(_Strict):
    id: str
    pos: Tuple[float, float] = (0, 0)
    text: str = ""


class Flow(_Strict):
    flux_flow: int
    name: str
    label: str = ""
    description: str = ""
    # Derived, written by the store, ignored on read (parse_flow resets them).
    scope: Optional[str] = None
    version: Optional[int] = None
    active: Optional[bool] = None
    run_policy: Literal["skip_if_running", "queue"] = "skip_if_running"
    origin: Optional[Origin] = None
    node_type: Optional[str] = None
    interface: Interface = Interface()
    variables: List[Variable] = []
    nodes: Dict[str, Node] = {}
    links: List[Link] = []
    groups: List[Group] = []
    notes: List[Note] = []

    @field_validator("flux_flow")
    @classmethod
    def _format(cls, value: int) -> int:
        if value != FORMAT_VERSION:
            raise ValueError(f"format {value} non pris en charge (attendu {FORMAT_VERSION})")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not NAME_RE.match(value):
            raise ValueError("nom invalide : minuscules, chiffres et _, 2 a 41 caracteres, commence par une lettre")
        if value in RESERVED_NAMES:
            raise ValueError(f"le nom '{value}' est reserve")
        return value

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        if len(value) > LABEL_MAX:
            raise ValueError(f"libelle trop long (max {LABEL_MAX} caracteres)")
        return value

    @field_validator("node_type")
    @classmethod
    def _node_type(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not NODE_TYPE_RE.match(value):
            raise ValueError(f"node_type '{value}' : attendu <famille>.<nom>")
        return value

    @field_validator("interface", mode="before")
    @classmethod
    def _interface_list(cls, value: Any) -> Any:
        # The list form is the inputs-only shorthand.
        return {"inputs": value} if isinstance(value, list) else value

    @model_validator(mode="after")
    def _check(self) -> "Flow":
        seen: set = set()
        named = [(i.id, "interface") for i in self.interface.inputs]
        named += [(v.name, "variables") for v in self.variables]
        for ident, where in named:
            if not FIELD_ID_RE.match(ident):
                raise ValueError(f"{where} : id '{ident}' invalide")
            if ident.lower() in RESERVED_VARS:
                raise ValueError(f"{where} : '{ident}' est reserve (FLUX et cles de contexte)")
            if ident in seen:
                raise ValueError(f"{where} : '{ident}' est deja declare (interface et variables partagent les noms)")
            seen.add(ident)
        outs = [o.id for o in self.interface.outputs]
        if len(set(outs)) != len(outs) or any(not FIELD_ID_RE.match(o) for o in outs):
            raise ValueError("interface.outputs : ids invalides ou en double")
        for var in self.variables:
            if not DATA_TYPE_RE.match(var.type):
                raise ValueError(f"variables : type '{var.type}' invalide")
        _check_node_ids(self.nodes)
        count = sum(1 for _ in iter_nodes(self))
        if count > MAX_NODES:
            raise ValueError(f"{count} nodes : maximum {MAX_NODES}")
        return self


def _check_node_ids(nodes: Dict[str, Node]) -> None:
    for node_id in nodes:
        if not NODE_ID_RE.match(node_id):
            raise ValueError(f"id de node '{node_id}' invalide")


Node.model_rebuild()


# -- read ---------------------------------------------------------------------

def _format_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err.get("loc", ()) if p != "from_") or "flow"
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        parts.append(f"{where} : {msg}")
    return " ; ".join(parts)


def parse_flow(data: Any) -> Flow:
    """Validate a decoded document. ``scope``, ``version``, ``active`` are dropped."""
    if not isinstance(data, dict):
        raise FlowSchemaError("un flow est un document YAML de type map")
    if "flux_flow" not in data and "steps" in data:
        raise FlowSchemaError("action v1, voir la migration")
    try:
        flow = Flow.model_validate(data)
    except ValidationError as exc:
        raise FlowSchemaError(_format_error(exc)) from None
    flow.scope = flow.version = flow.active = None
    # Links are an unordered set: keep them sorted so equal flows compare equal.
    flow.links = sorted(flow.links, key=lambda l: (l.from_, l.to))
    for _, node in iter_nodes(flow):
        if node.links:
            node.links = sorted(node.links, key=lambda l: (l.from_, l.to))
    return flow


def load_flow_text(text: str) -> Flow:
    """Parse a ``.flow.yml`` text (max 1 MB)."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise FlowSchemaError(f"fichier trop gros (max {MAX_BYTES // 1024} Ko)")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise FlowSchemaError(f"YAML illisible : {exc}") from None
    return parse_flow(data)


def iter_nodes(flow: Flow) -> Iterator[Tuple[str, Node]]:
    """All nodes, subnet contents included (ids are only unique per level)."""
    stack: List[Dict[str, Node]] = [flow.nodes]
    while stack:
        for node_id, node in stack.pop().items():
            yield node_id, node
            if node.nodes:
                stack.append(node.nodes)


def v1_limit_issues(flow: Flow) -> List[Dict[str, str]]:
    """Values the schema stores for V2 but V1 refuses (01 §2 "Reserve V2").

    ForEach ``mode`` is kept and ignored; an Instance in ``farm`` mode is an
    error. Consumed by the validation (P4).
    """
    issues = []
    for node_id, node in iter_nodes(flow):
        if node.type.startswith("session.") and node.type.endswith("_instance") \
                and node.params.get("mode") == "farm":
            issues.append({"code": "E_PARAM_INVALID", "node": node_id,
                           "message": "le mode farm n'existe pas encore (V2)"})
    return issues


# -- emit ---------------------------------------------------------------------

_YAML_WORDS = frozenset("true false yes no on off null y n ~".split())
_BARE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return {"nan": ".nan", "inf": ".inf", "-inf": "-.inf"}[repr(value)]
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        text = repr(value)
        # PyYAML (YAML 1.1) reads 1e+20 as a string: it needs the dot.
        return text if "." in text or "e" not in text else text.replace("e", ".0e", 1)
    text = str(value)
    if _BARE_RE.match(text) and text.lower() not in _YAML_WORDS:
        return text
    return json.dumps(text, ensure_ascii=False)


def _flow_style(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_scalar(k)}: {_flow_style(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_flow_style(v) for v in value) + "]"
    return _scalar(value)


def _drop_none(doc: Dict[str, Any], keep: Tuple[str, ...] = ()) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if v is not None or k in keep}


def _node_doc(node: Node) -> Dict[str, Any]:
    doc: Dict[str, Any] = {"type": node.type, "pos": list(node.pos), "params": node.params}
    if node.label is not None:
        doc["label"] = node.label
    if node.bypass:
        doc["bypass"] = True
    return doc


def _link_docs(links: List[Link]) -> List[Dict[str, str]]:
    return [{"from": l.from_, "to": l.to} for l in sorted(links, key=lambda l: (l.from_, l.to))]


def _emit_network(out: List[str], nodes: Dict[str, Node], links: List[Link], indent: int) -> None:
    pad = " " * indent
    out.append(f"{pad}nodes:" + ("" if nodes else " {}"))
    for node_id, node in nodes.items():
        if node.type != SUBNET_TYPE:
            out.append(f"{pad}  {node_id}: {_flow_style(_node_doc(node))}")
            continue
        out.append(f"{pad}  {node_id}:")
        for key, value in _node_doc(node).items():
            out.append(f"{pad}    {key}: {_flow_style(value)}")
        _emit_network(out, node.nodes or {}, node.links or [], indent + 4)
    out.append(f"{pad}links:" + ("" if links else " []"))
    out += [f"{pad}  - {_flow_style(l)}" for l in _link_docs(links)]


def dump_flow(flow: Flow, *, scope: Optional[str] = None, version: Optional[int] = None,
              active: Optional[bool] = None) -> str:
    """Stable YAML text. Without the derived fields it is the canonical content
    used to decide whether an increment changes anything."""
    out = [f"flux_flow: {FORMAT_VERSION}", f"name: {flow.name}"]
    if flow.label:
        out.append(f"label: {_scalar(flow.label)}")
    if flow.description:
        out.append(f"description: {_scalar(flow.description)}")
    for key, value in (("scope", scope), ("version", version), ("active", active)):
        if value is not None:
            out.append(f"{key}: {_scalar(value)}")
    out.append(f"run_policy: {flow.run_policy}")
    if flow.origin:
        out.append(f"origin: {_flow_style(flow.origin.model_dump())}")
    if flow.node_type:
        out.append(f"node_type: {flow.node_type}")
    inputs = [_drop_none(i.model_dump(), keep=("default",)) for i in flow.interface.inputs]
    if flow.interface.outputs:
        out += ["interface:", "  inputs:"] if inputs else ["interface:", "  inputs: []"]
        out += [f"    - {_flow_style(i)}" for i in inputs]
        out.append("  outputs:")
        out += [f"    - {_flow_style(o.model_dump())}" for o in flow.interface.outputs]
    elif inputs:
        out.append("interface:")
        out += [f"  - {_flow_style(i)}" for i in inputs]
    if flow.variables:
        out.append("variables:")
        out += [f"  - {_flow_style(_drop_none(v.model_dump()))}" for v in flow.variables]
    _emit_network(out, flow.nodes, flow.links, 0)
    if flow.groups:
        out.append("groups:")
        out += [f"  - {_flow_style(_drop_none(g.model_dump()))}" for g in flow.groups]
    if flow.notes:
        out.append("notes:")
        out += [f"  - {_flow_style({'id': n.id, 'pos': list(n.pos), 'text': n.text})}" for n in flow.notes]
    return "\n".join(out) + "\n"


def to_document(flow: Flow) -> Dict[str, Any]:
    """JSON-ready document for the API (same keys as the YAML)."""
    return yaml.safe_load(dump_flow(flow))

