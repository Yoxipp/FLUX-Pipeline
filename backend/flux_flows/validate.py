# validate.py — the validation of a flow (01_ARCHITECTURE §8, 00_LOGIQUE §11). P4.
#
# validate.py is the truth: save (state.json ``valid``), run (refused on an error),
# activation, and POST /flows/validate (the editor calls it, debounce 300 ms).
# Saving stays possible with errors (quit = Ctrl+S). Each Issue says what, why and,
# when it is obvious, a one-click ``fix`` {kind, args} the editor applies then
# revalidates. Codes: exactly the table of 01 §8, nothing invented.
#
# Design choices:
#   * Pure function of the document + an Env (roots, project, flow loader, dry-run
#     result): no I/O of its own except the registry (team nodes reloaded once).
#   * No false positive over a clever guess: an output still typed ``any`` after
#     propagation (GetVariable, FlowInput, ForEach item, pass-through nodes) is not
#     type checked; a variable written anywhere counts as written (proposition).
#   * Only the top-level network is executed (subnets are not run yet, ADR 0058):
#     a subnet's inner network gets the node and link checks, not the exec checks.
#   * E_DESTRUCTIVE_UNCONFIRMED compares two documents, so it is its own function
#     (unconfirmed_destructive), called by PUT / increment, not by validate().

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PureWindowsPath, PurePosixPath
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from flux_flows import patterns, resolver
from flux_flows.model import SUBNET_TYPE, Flow, FlowSchemaError, Link, Node, parse_flow, v1_limit_issues
from flux_flows.nodes import registry
from flux_flows.nodes.data import VALUE_TYPES, cast_literal
from flux_flows.nodes.registry import NodeSpec, Port, flag_on
from flux_flows.types import can_connect

ERROR, WARNING = "error", "warning"
MIN_EVERY_S = 5          # hard minimum of a scan (01 §8, E_PARAM_INVALID below)
FAST_EVERY_S = 10        # W_SCAN_TOO_FAST below
MIN_SCENE_EVERY_S = 2    # event.scene_opened polls a local DCC
SCHEDULE, SCENE_OPENED = "event.schedule", "event.scene_opened"
MAX_SUBFLOW_DEPTH = 8

FOREACH_BEGIN, FOREACH_END = "operator.foreach_begin", "operator.foreach_end"
FOR_BEGIN, FOR_END = "operator.for_begin", "operator.for_end"
WHILE_BEGIN, WHILE_END = "operator.while_begin", "operator.while_end"
BLOCKS = {FOREACH_BEGIN: FOREACH_END, FOR_BEGIN: FOR_END, WHILE_BEGIN: WHILE_END}
ENDS = {end: begin for begin, end in BLOCKS.items()}
FLOW_CALL = "subflow.flow_call"
LEGACY = "flux.legacy_command"
DYNAMIC = (FLOW_CALL, LEGACY)         # ports declared in params.ports (+ any name for FlowCall)
LOOP_RISKY = ("action.delete", "action.move")
INSTANCE_RE = re.compile(r"^session\.[a-z0-9]+_instance$")
_LIST_RE = re.compile(r"^list\[(.+)\]$")
_FLUX_HEAD_RE = re.compile(r"^(\$FLUX|\$\{FLUX\})(?=$|[/\\])")
_PASS = {  # (type, output) -> input whose type the output takes
    ("operator.null", "value"): "value", ("logic.select", "value"): "a",
    ("operator.list_filter", "items"): "list", ("operator.list_filter", "rejected"): "list",
    ("operator.list_sort", "items"): "list", ("operator.list_unique", "items"): "list",
    ("operator.list_append", "items"): "list",
}


@dataclass
class Issue:
    level: str
    code: str
    node: Optional[str]
    port: Optional[str]
    message_fr: str
    message_en: str
    why_fr: str = ""
    why_en: str = ""
    fix: Optional[Dict[str, Any]] = None
    link: Optional[Dict[str, str]] = None     # the faulty link, when there is one (marked in the editor)

    def to_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "code": self.code, "node": self.node, "port": self.port,
                "message_fr": self.message_fr, "message_en": self.message_en, "why_fr": self.why_fr,
                "why_en": self.why_en, "fix": self.fix, "link": self.link}


@dataclass
class Env:
    """What the validation needs beyond the document. Every field is optional."""
    project: Optional[str] = None                  # project of the flow (scope project)
    flux_root: Optional[str] = None
    projects_dir: Optional[str] = None
    flow_loader: Optional[Callable[[str], Optional[Flow]]] = None   # name -> Flow (FlowCall cycles)
    tested: Optional[Iterable[str]] = None         # node ids the dry run of this version simulated
    shipped_changed: bool = False                  # team copy older than the shipped flow
    page_links: Optional[List[Dict[str, Any]]] = None   # links of the TOOL pages to this flow (P7, page_links)


def default_env(project: Optional[str] = None, **extra: Any) -> Env:
    """Env with this machine's FLUX_ROOT and projects folder (None without config)."""
    root = projects = None
    try:
        from core.paths import get_flux_root, get_projects_dir

        found = get_flux_root()
        if found:
            root, projects = str(found), str(get_projects_dir())
    except Exception:   # no config (tests, first launch)
        pass
    return Env(project=project, flux_root=root, projects_dir=projects, **extra)


# -- messages -----------------------------------------------------------------

_WHY = {
    "E_SCHEMA": ("format strict : le fichier doit se relire tel quel", "strict format: the file must reload as is"),
    "E_UNKNOWN_NODE": ("rien ne peut tourner", "nothing can run"),
    "E_PARAM_INVALID": ("valeur inexecutable", "the value cannot run"),
    "E_LINK_INVALID": ("ordre ou valeur ambigus", "ambiguous order or value"),
    "E_TYPE_MISMATCH": ("pas de conversion sourde", "no silent conversion"),
    "E_REQUIRED_EMPTY": ("le node echouerait", "the node would fail"),
    "E_NO_EVENT": ("rien ne le declenche", "nothing triggers it"),
    "E_EXEC_CYCLE": ("boucle infinie", "endless loop"),
    "E_BLOCK_UNBALANCED": ("corps de boucle non delimite", "loop body not delimited"),
    "E_NO_SESSION": ("rien a qui parler", "nothing to talk to"),
    "E_LIVE_ONLY": ("pas d'interface en headless", "no interface in headless"),
    "E_VAR_NEVER_SET": ("valeur indefinie", "undefined value"),
    "E_DATA_BEFORE_PRODUCED": ("valeur absente", "missing value"),
    "E_UNKNOWN_TOKEN": ("resultat vide", "empty result"),
    "E_SUBFLOW_CYCLE": ("recursion infinie", "endless recursion"),
    "E_DESTRUCTIVE_UNCONFIRMED": ("l'API ne contourne pas la validation au curseur",
                                  "the API does not bypass the slide to confirm"),
    "W_DESTRUCTIVE_UNTESTED": ("effet irreversible", "irreversible effect"),
    "W_DESTRUCTIVE_IN_LOOP": ("multiplie l'effet", "multiplies the effect"),
    "W_ABSOLUTE_PATH": ("echoue sur un autre poste", "fails on another computer"),
    "W_OTHER_PROJECT": ("effet hors perimetre", "effect out of scope"),
    "W_SCAN_TOO_FAST": ("charge reseau (ADR 0056)", "network load (ADR 0056)"),
    "W_WHILE_NO_EXIT": ("boucle jusqu'au plafond", "loops up to the ceiling"),
    "W_ISOLATED_NODE": ("aucun effet", "no effect"),
    "W_LICENCE": ("ADR 0007 : FLUX ne prend aucune licence lui-meme", "ADR 0007: FLUX itself takes no licence"),
    "W_SHIPPED_CHANGED": ("reprise de l'ADR 0039", "from ADR 0039"),
    "W_PAGE_LINK_BROKEN": ("la page n'est pas ouverte a ce moment-la", "the page is not open at that moment"),
}


def _issue(code: str, node: Optional[str], fr: str, en: str, *, port: Optional[str] = None,
           fix: Optional[Dict[str, Any]] = None, link: Optional[Link] = None) -> Issue:
    why_fr, why_en = _WHY[code]
    return Issue(ERROR if code.startswith("E_") else WARNING, code, node, port, fr, en, why_fr, why_en, fix,
                 {"from": link.from_, "to": link.to} if link is not None else None)


def _fix(kind: str, **args: Any) -> Dict[str, Any]:
    return {"kind": kind, "args": args}


def _split(ref: str) -> Tuple[str, str]:
    node, _, port = ref.partition(".")
    return node, port


# -- one network ----------------------------------------------------------------

class _Net:
    """One network (the flow, or the inside of a subnet) with its ports resolved."""

    def __init__(self, flow: Flow, nodes: Dict[str, Node], links: List[Link]) -> None:
        self.flow, self.nodes, self.links = flow, nodes, links
        self.specs: Dict[str, Optional[NodeSpec]] = {
            nid: (None if n.type == SUBNET_TYPE else registry.get_node(n.type)) for nid, n in nodes.items()}
        self.var_types = {v.name: v.type for v in flow.variables}
        self.iface_types = {i.id: i.type for i in flow.interface.inputs}
        self.data_in: Dict[Tuple[str, str], Link] = {}
        self.exec_out: Dict[Tuple[str, str], str] = {}
        self.exec_preds: Dict[str, Set[str]] = {nid: set() for nid in nodes}
        self.exec_succ: Dict[str, List[Tuple[str, str]]] = {nid: [] for nid in nodes}
        self.data_succ: Dict[str, Set[str]] = {nid: set() for nid in nodes}
        self.linked: Set[str] = set()
        self.good_links: List[Link] = []

    def name(self, nid: str) -> str:
        node, spec = self.nodes.get(nid), self.specs.get(nid)
        label = (node.label if node and node.label else None) or (spec.label if spec else None) \
            or (node.type if node else "?")
        return f"{label} {nid}"

    def inputs(self, nid: str) -> Dict[str, Port]:
        spec, node = self.specs.get(nid), self.nodes[nid]
        if spec is None:
            return {}
        out = {p.name: p for p in spec.params}      # every param is promotable to an input (02 §1)
        out.update({p.name: p for p in spec.inputs})
        if node.type in DYNAMIC:
            for pname, ptype in ((node.params.get("ports") or {}).get("inputs") or {}).items():
                out.setdefault(pname, Port(pname, str(ptype)))
        return out

    def outputs(self, nid: str) -> Dict[str, str]:
        spec, node = self.specs.get(nid), self.nodes[nid]
        if spec is None:
            return {}
        out = {p.name: p.type for p in spec.outputs}
        if node.type in DYNAMIC:
            for pname, ptype in ((node.params.get("ports") or {}).get("outputs") or {}).items():
                out.setdefault(pname, str(ptype))
        return out

    def is_event(self, nid: str) -> bool:
        return self.nodes[nid].type.startswith("event.")

    def runs_in_chain(self, nid: str) -> bool:
        """Executed by the exec cursor (event, exec node, linked exec? reader); else pure."""
        if self.is_event(nid):
            return True
        port = self.inputs(nid).get("exec")
        if port is None or port.type != "exec":
            return False
        return port.required or bool(self.exec_preds.get(nid))

    # -- types --

    def in_type(self, nid: str, port: str, depth: int) -> Optional[str]:
        link = self.data_in.get((nid, port))
        if link is None:
            return None
        src, sport = _split(link.from_)
        return self.out_type(src, sport, depth + 1)

    def out_type(self, nid: str, port: str, depth: int = 0) -> str:
        declared = self.outputs(nid).get(port, "any")
        if "any" not in declared or depth > 30:
            return declared
        node = self.nodes[nid]
        kind, params = node.type, node.params
        if kind == "data.value" and port == "value":
            typed = str(params.get("type") or "str")
            return "list[any]" if typed == "list" else (typed if typed in VALUE_TYPES else declared)
        if kind in ("data.get_variable", "data.set_variable") and port == "value":
            return self.var_types.get(str(params.get("name") or ""), declared)
        if kind == "data.flow_input" and port == "value":
            found = self.iface_types.get(str(params.get("id") or ""))
            return "str" if found == "select" else (found or declared)
        if kind == FOREACH_BEGIN and port == "item":
            inner = _LIST_RE.match(self.in_type(nid, "list", depth) or "")
            return inner.group(1) if inner else declared
        if kind == FOREACH_END and port == "results":
            got = self.in_type(nid, "collect", depth)
            return f"list[{got}]" if got and got != "exec" else declared
        if kind == "operator.list_get" and port == "item":
            inner = _LIST_RE.match(self.in_type(nid, "list", depth) or "")
            return inner.group(1) if inner else declared
        source = _PASS.get((kind, port))
        if source:
            return self.in_type(nid, source, depth) or declared
        return declared


def _literal(node: Node, name: str) -> Any:
    value = node.params.get(name)
    return None if value == "" else value


def _in_choices(value: Any, choices: Iterable[Any]) -> bool:
    """A literal against the choices of its param (exact value, the editor offers them in a menu)."""
    return any(value == c and type(value) is type(c) for c in choices)


def _templated(value: Any) -> bool:
    return isinstance(value, str) and any(c in value for c in "{$")


# -- the checks -------------------------------------------------------------------

def _check_links(net: _Net, issues: List[Issue]) -> None:
    """E_LINK_INVALID, E_TYPE_MISMATCH; fills the graph of the good links."""
    seen_data: Set[Tuple[str, str]] = set()
    for link in net.links:
        src, sport = _split(link.from_)
        dst, dport = _split(link.to)
        if src not in net.nodes or dst not in net.nodes:
            missing = src if src not in net.nodes else dst
            issues.append(_issue("E_LINK_INVALID", dst if dst in net.nodes else src,
                                 f"Le lien {link.from_} -> {link.to} vise le node `{missing}` qui n'existe pas",
                                 f"The link {link.from_} -> {link.to} targets node `{missing}`, which does not exist",
                                 fix=_fix("remove_link", **{"from": link.from_, "to": link.to}), link=link))
            continue
        if net.specs[src] is None or net.specs[dst] is None:
            continue   # unknown node: E_UNKNOWN_NODE says it
        net.linked.update((src, dst))
        outs, ins = net.outputs(src), net.inputs(dst)
        dyn_src, dyn_dst = net.nodes[src].type == FLOW_CALL, net.nodes[dst].type == FLOW_CALL
        remove = _fix("remove_link", **{"from": link.from_, "to": link.to})
        if sport not in outs and not dyn_src:
            if sport in net.inputs(src):
                fr, en = f"Le lien part de l'entree `{sport}` de {net.name(src)} : un lien va d'une sortie vers une entree", \
                         f"The link starts from input `{sport}` of {net.name(src)}: a link goes from an output to an input"
            else:
                fr, en = f"{net.name(src)} n'a pas de sortie `{sport}`", f"{net.name(src)} has no output `{sport}`"
            issues.append(_issue("E_LINK_INVALID", src, fr, en, port=sport, fix=remove, link=link))
            continue
        if dport not in ins and not dyn_dst:
            if net.is_event(dst) and dport == "exec":
                fr, en = f"{net.name(dst)} est un evenement : rien ne s'execute avant lui", \
                         f"{net.name(dst)} is an event: nothing runs before it"
            elif dport in net.outputs(dst):
                fr, en = f"Le lien arrive sur la sortie `{dport}` de {net.name(dst)} : un lien va d'une sortie vers une entree", \
                         f"The link ends on output `{dport}` of {net.name(dst)}: a link goes from an output to an input"
            else:
                fr, en = f"{net.name(dst)} n'a pas d'entree `{dport}`", f"{net.name(dst)} has no input `{dport}`"
            issues.append(_issue("E_LINK_INVALID", dst, fr, en, port=dport, fix=remove, link=link))
            continue
        if dport in ins and not ins[dport].wirable:
            issues.append(_issue("E_LINK_INVALID", dst,
                                 f"`{dport}` de {net.name(dst)} est une constante : saisis sa valeur, pas de lien",
                                 f"`{dport}` of {net.name(dst)} is a constant: type its value, no link",
                                 port=dport, fix=remove, link=link))
            continue
        src_type = outs.get(sport, "any")
        dst_type = ins[dport].type if dport in ins else "any"
        if (src_type == "exec") != (dst_type == "exec"):
            issues.append(_issue("E_TYPE_MISMATCH", dst,
                                 "Un lien d'execution relie seulement deux ports d'execution",
                                 "An execution link only joins two execution ports", port=dport, fix=remove, link=link))
            continue
        if src_type == "exec":
            if (src, sport) in net.exec_out:
                issues.append(_issue("E_LINK_INVALID", src,
                                     f"La sortie `{sport}` de {net.name(src)} a deja une suite : plusieurs suites, utilise Sequence",
                                     f"Output `{sport}` of {net.name(src)} already has a next node: for several, use Sequence",
                                     port=sport, fix=remove, link=link))
                continue
            net.exec_out[(src, sport)] = dst
            net.exec_succ[src].append((sport, dst))
            net.exec_preds[dst].add(src)
            net.good_links.append(link)
            continue
        if (dst, dport) in seen_data:
            issues.append(_issue("E_LINK_INVALID", dst, "Une entree donnee n'accepte qu'un lien",
                                 "A data input takes one link only", port=dport, fix=remove, link=link))
            continue
        seen_data.add((dst, dport))
        net.data_in[(dst, dport)] = link
        net.data_succ[src].add(dst)
        net.good_links.append(link)
    # Types once every data link is known (propagation follows the links).
    for (dst, dport), link in net.data_in.items():
        src, sport = _split(link.from_)
        src_type = net.out_type(src, sport)
        ins = net.inputs(dst)
        dst_type = ins[dport].type if dport in ins else "any"
        if "any" in src_type:
            continue   # unknown until run time (see the header)
        conn = can_connect(src_type, dst_type)
        if conn.status == "incompatible":
            fix = _fix(conn.fix, **{"from": link.from_, "to": link.to}) if conn.fix else None
            issues.append(_issue("E_TYPE_MISMATCH", dst, conn.reason_fr, conn.reason_en,
                                 port=dport, fix=fix, link=link))


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _check_nodes(net: _Net, issues: List[Issue], env: Env) -> None:
    """E_UNKNOWN_NODE, E_PARAM_INVALID, E_REQUIRED_EMPTY, E_UNKNOWN_TOKEN, sessions, paths."""
    names = set(net.var_types) | set(net.iface_types)
    for nid, node in net.nodes.items():
        spec = net.specs[nid]
        if node.type == SUBNET_TYPE:
            continue
        if spec is None:
            issues.append(_issue("E_UNKNOWN_NODE", nid, f"Le node `{node.type}` est introuvable ou casse",
                                 f"Node `{node.type}` is missing or broken"))
            continue
        ports = net.inputs(nid)
        # Literal types, patterns, per-node rules.
        for pname, value in node.params.items():
            port = ports.get(pname)
            if port is None or value in (None, "") or port.type == "exec":
                continue
            if _templated(value) and port.type not in ("str", "path", "dir", "pattern", "any"):
                continue
            try:
                cast_literal(port.type, value)
            except Exception:
                issues.append(_issue("E_PARAM_INVALID", nid,
                                     f"{net.name(nid)} : `{pname}` attend {port.type}, recu {value!r}",
                                     f"{net.name(nid)}: `{pname}` expects {port.type}, got {value!r}", port=pname))
                continue
            if port.choices and not _templated(value) and not _in_choices(value, port.choices):
                shown = ", ".join(str(c) for c in port.choices)
                issues.append(_issue("E_PARAM_INVALID", nid,
                                     f"{net.name(nid)} : `{pname}` vaut {value!r}, attendu : {shown}",
                                     f"{net.name(nid)}: `{pname}` is {value!r}, expected: {shown}", port=pname))
                continue
            if port.reserved and not _templated(value) and _in_choices(value, port.reserved):
                issues.append(_issue("E_PARAM_INVALID", nid,
                                     f"{net.name(nid)} : `{pname}` = {value!r} n'est pas encore disponible, choisis "
                                     f"une autre option du menu",
                                     f"{net.name(nid)}: `{pname}` = {value!r} is not available yet, pick another "
                                     f"option of the menu", port=pname))
                continue
            if port.type == "pattern" and isinstance(value, str) and not _templated(value):
                bad = patterns.check_pattern(value)
                if bad:
                    issues.append(_issue("E_PARAM_INVALID", nid, f"{net.name(nid)} : motif `{pname}` : {bad}",
                                         f"{net.name(nid)}: pattern `{pname}` is malformed", port=pname))
        _check_node_rules(net, nid, node, issues)
        # Required inputs and params.
        for port in ports.values():
            if not port.required or port.type == "exec" or (nid, port.name) in net.data_in:
                continue
            if _literal(node, port.name) is not None or port.default is not None:
                continue
            issues.append(_issue("E_REQUIRED_EMPTY", nid,
                                 f"{net.name(nid)} attend `{port.name}` : relie un lien ou saisis une valeur",
                                 f"{net.name(nid)} needs `{port.name}`: link it or type a value", port=port.name))
        # Tokens and ${variables} of the texts the engine resolves.
        for pname, value in node.params.items():
            if pname in spec.raw or not isinstance(value, str):
                continue
            for token in resolver.tokens_in(value):
                if token.startswith("$"):
                    var = token[1:]
                    if var in names:
                        continue
                    hint = resolver.suggest_token(var, sorted(names))
                    shown, wanted = "${" + var + "}", ("${" + hint + "}" if hint else None)
                else:
                    if token in resolver.CONTEXT_KEYS or token.lower() in resolver.CONTEXT_KEYS:
                        continue
                    hint = resolver.suggest_token(token, resolver.CONTEXT_KEYS)
                    shown, wanted = "{" + token + "}", ("{" + hint + "}" if hint else None)
                fr = f"Token inconnu `{shown}`" + (f" : tu voulais `{wanted}` ?" if wanted else "")
                en = f"Unknown token `{shown}`" + (f": did you mean `{wanted}`?" if wanted else "")
                fix = _fix("replace_token", node=nid, param=pname, token=shown, suggestion=wanted) if wanted else None
                issues.append(_issue("E_UNKNOWN_TOKEN", nid, fr, en, port=pname, fix=fix))
        _check_paths(net, nid, node, spec, ports, issues, env)
        _check_session(net, nid, node, spec, issues)


def _check_node_rules(net: _Net, nid: str, node: Node, issues: List[Issue]) -> None:
    params = node.params
    every = params.get("every_s")
    # scene_opened polls a local DCC, not the share: 2 s minimum, no network warning (01 §9).
    local_poll = node.type == SCENE_OPENED
    minimum = MIN_SCENE_EVERY_S if local_poll else MIN_EVERY_S
    if isinstance(every, (int, float)) and not isinstance(every, bool):
        if every < minimum:
            issues.append(_issue("E_PARAM_INVALID", nid, f"Frequence minimale : {minimum} secondes",
                                 f"Minimum frequency: {minimum} seconds", port="every_s"))
        elif every < FAST_EVERY_S and not local_poll:
            issues.append(_issue("W_SCAN_TOO_FAST", nid, f"Scan toutes les {every:g} s : charge reseau",
                                 f"Scan every {every:g} s: network load", port="every_s",
                                 fix=_fix("set_param", node=nid, param="every_s", value=30)))
    # data.value ``type`` is checked by its choices (VALUE_TYPES), in _check_nodes.
    if node.type == SCHEDULE:
        from flux_flows import scheduler

        for pname in ("days", "time"):   # missed: checked by its choices
            problem = scheduler.schedule_param_error(pname, params.get(pname))
            if problem:
                issues.append(_issue("E_PARAM_INVALID", nid, problem[0], problem[1], port=pname))
    if node.type == FOR_BEGIN and (nid, "step") not in net.data_in and params.get("step") in (0, 0.0, "0"):
        issues.append(_issue("E_PARAM_INVALID", nid, "step ne peut pas valoir 0", "step cannot be 0", port="step"))
    if node.type == "data.flow_input":
        ident = str(params.get("id") or "")
        if ident and ident not in net.iface_types:
            issues.append(_issue("E_PARAM_INVALID", nid,
                                 f"Le parametre `{ident}` n'est pas dans l'interface du flow",
                                 f"Parameter `{ident}` is not in the flow interface", port="id"))
    if node.type in ("data.get_variable", "data.set_variable"):
        name = str(params.get("name") or "")
        if name and name not in net.var_types:
            issues.append(_issue("E_PARAM_INVALID", nid, f"La variable `{name}` n'est pas declaree",
                                 f"Variable `{name}` is not declared", port="name"))
    if node.type == "subflow.flow_output":
        ident = str(params.get("id") or "")
        if ident and ident not in {o.id for o in net.flow.interface.outputs}:
            issues.append(_issue("E_PARAM_INVALID", nid, f"La sortie `{ident}` n'est pas dans interface.outputs",
                                 f"Output `{ident}` is not in interface.outputs", port="id"))


def _absolute(text: str) -> bool:
    return PureWindowsPath(text).is_absolute() or text.startswith(("/", "\\\\"))


def _under(path: str, root: Optional[str]) -> Optional[str]:
    """Relative part of *path* under *root* (case-insensitive, either slash), else None."""
    if not root:
        return None
    p, r = path.replace("\\", "/").rstrip("/").lower(), root.replace("\\", "/").rstrip("/").lower()
    if p == r:
        return ""
    return path.replace("\\", "/")[len(r) + 1:] if p.startswith(r + "/") else None


def _check_paths(net: _Net, nid: str, node: Node, spec: NodeSpec, ports: Mapping[str, Port],
                 issues: List[Issue], env: Env) -> None:
    for pname, value in node.params.items():
        port = ports.get(pname)
        if port is None or port.type not in ("path", "dir") or not isinstance(value, str) or not value:
            continue
        head = _FLUX_HEAD_RE.match(value)
        if head:
            if not env.flux_root:
                continue
            text = env.flux_root.rstrip("/\\") + "/" + value[head.end():].lstrip("/\\")
        elif not _absolute(value):
            continue   # relative, {project_path}/..., ${var}: resolved at run time
        else:
            text = value
            if _under(text, env.flux_root) is None:
                issues.append(_issue("W_ABSOLUTE_PATH", nid, f"Chemin absolu hors du pipe : pas portable ({value})",
                                     f"Absolute path outside the pipe: not portable ({value})", port=pname))
                continue
        rel = _under(text, env.projects_dir)
        if spec.effect and env.project and rel:
            other = PurePosixPath(rel).parts[0] if rel else ""
            if other and other.lower() != env.project.lower():
                issues.append(_issue("W_OTHER_PROJECT", nid, f"Ecrit dans le projet `{other}`",
                                     f"Writes into project `{other}`", port=pname))


def _check_session(net: _Net, nid: str, node: Node, spec: NodeSpec, issues: List[Issue]) -> None:
    if flag_on(spec.licence, spec, node.params):
        issues.append(_issue("W_LICENCE", nid, f"{net.name(nid)} prend une licence pendant le run",
                             f"{net.name(nid)} takes a licence during the run"))
    if not spec.session:
        return
    soft = spec.session
    link = net.data_in.get((nid, "session"))
    if link is None:
        issues.append(_issue("E_NO_SESSION", nid,
                             f"{net.name(nid)} a besoin d'une session {soft} : ajoute {soft.capitalize()}Instance",
                             f"{net.name(nid)} needs a {soft} session: add {soft.capitalize()}Instance",
                             port="session", fix=_fix("add_instance", soft=soft, node=nid)))
        return
    src, _ = _split(link.from_)
    source = net.nodes.get(src)
    if spec.live_only and source is not None and INSTANCE_RE.match(source.type) \
            and source.params.get("mode") == "headless":
        issues.append(_issue("E_LIVE_ONLY", nid, f"{net.name(nid)} demande une session Live",
                             f"{net.name(nid)} needs a Live session", port="session",
                             fix=_fix("set_instance_mode", node=src, mode="live_connect_or_open")))


# -- exec structure (top level only) -------------------------------------------------

def _check_cycles(net: _Net, issues: List[Issue]) -> None:
    """E_EXEC_CYCLE: a loop of exec links (blocks loop by Begin / End, never by links) or of data links."""
    for kind, succ in (("exec", {n: [d for _, d in net.exec_succ[n]] for n in net.nodes}),
                       ("data", {n: sorted(net.data_succ[n]) for n in net.nodes})):
        state: Dict[str, int] = {}
        for root in net.nodes:
            if state.get(root):
                continue
            stack = [(root, iter(succ[root]))]
            state[root] = 1
            while stack:
                cur, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    state[cur] = 2
                    stack.pop()
                    continue
                if state.get(nxt) == 1:
                    link = _find_link(net, cur, nxt, kind)
                    fr = (f"Le lien {cur} -> {nxt} revient en arriere : utilise un bloc For ou While" if kind == "exec"
                          else f"Les donnees de {cur} et {nxt} dependent l'une de l'autre")
                    en = (f"The link {cur} -> {nxt} goes back: use a For or While block" if kind == "exec"
                          else f"The data of {cur} and {nxt} depend on each other")
                    issues.append(_issue("E_EXEC_CYCLE", nxt, fr, en, link=link,
                                         fix=_fix("remove_link", **{"from": link.from_, "to": link.to}) if link else None))
                elif not state.get(nxt):
                    state[nxt] = 1
                    stack.append((nxt, iter(succ[nxt])))


def _find_link(net: _Net, src: str, dst: str, kind: str) -> Optional[Link]:
    for link in net.good_links:
        s, sport = _split(link.from_)
        d, dport = _split(link.to)
        is_exec = net.outputs(s).get(sport) == "exec"
        if s == src and d == dst and is_exec == (kind == "exec"):
            return link
    return None


def _reach(net: _Net, starts: Iterable[str], stop: Set[str] = frozenset()) -> Set[str]:
    seen: Set[str] = set()
    todo = [s for s in starts if s not in stop]
    while todo:
        cur = todo.pop()
        if cur in seen:
            continue
        seen.add(cur)
        todo += [d for _, d in net.exec_succ.get(cur, ()) if d not in stop and d not in seen]
    return seen


def _check_blocks(net: _Net, issues: List[Issue]) -> Dict[str, Tuple[str, Set[str]]]:
    """E_BLOCK_UNBALANCED. Returns {begin: (end, body nodes)} for the sound blocks."""
    ends: Dict[str, List[str]] = {}
    for nid, node in net.nodes.items():
        if node.type in ENDS:
            begin = str(node.params.get("begin") or "")
            target = net.nodes.get(begin)
            if target is None or target.type != ENDS[node.type]:
                issues.append(_issue("E_BLOCK_UNBALANCED", nid,
                                     f"{net.name(nid)} ne pointe aucun {ENDS[node.type].split('.')[1]} (parametre begin)",
                                     f"{net.name(nid)} points to no matching Begin (begin parameter)", port="begin"))
                continue
            ends.setdefault(begin, []).append(nid)
    sound: Dict[str, Tuple[str, Set[str]]] = {}
    for nid, node in net.nodes.items():
        if node.type not in BLOCKS:
            continue
        found = ends.get(nid, [])
        if not found:
            issues.append(_issue("E_BLOCK_UNBALANCED", nid, f"{net.name(nid)} n'a pas de End",
                                 f"{net.name(nid)} has no End", fix=_fix("add_block_end", begin=nid, type=BLOCKS[node.type])))
            continue
        for extra in found[1:]:
            issues.append(_issue("E_BLOCK_UNBALANCED", extra, f"{net.name(nid)} a deja un End ({found[0]})",
                                 f"{net.name(nid)} already has an End ({found[0]})"))
        sound[nid] = (found[0], set())
    # Bodies: what the loop output reaches before the End (nested blocks included).
    for begin, (end, body) in sound.items():
        after = _reach(net, [d for _, d in net.exec_succ[end]])
        start = [d for p, d in net.exec_succ[begin] if p == "loop"]
        body.update(_reach(net, start, stop={end}))
        if begin in body:
            continue   # an exec cycle, reported by _check_cycles
        for other_end in {e for b, (e, _) in sound.items() if b != begin} & body:
            other_begin = net.nodes[other_end].params.get("begin")
            if other_begin not in body:
                issues.append(_issue("E_BLOCK_UNBALANCED", other_end,
                                     f"Les blocs {begin} et {other_begin} se croisent",
                                     f"Blocks {begin} and {other_begin} cross each other"))
        leaks = sorted((body & after) - {end})
        if leaks:
            issues.append(_issue("E_BLOCK_UNBALANCED", leaks[0],
                                 f"La chaine du corps de {net.name(begin)} sort du bloc par {leaks[0]}",
                                 f"The body chain of {net.name(begin)} leaves the block through {leaks[0]}"))
    return sound


def _dominators(net: _Net, nodes: Set[str], preds: Dict[str, Set[str]], roots: Set[str]) -> Dict[str, Set[str]]:
    dom = {n: ({n} if n in roots else set(nodes)) for n in nodes}
    changed = True
    while changed:
        changed = False
        for n in nodes:
            if n in roots:
                continue
            ps = [dom[p] for p in preds.get(n, ()) if p in nodes]
            new = ({n} | set.intersection(*ps)) if ps else {n}
            if new != dom[n]:
                dom[n], changed = new, True
    return dom


def _check_flow_structure(net: _Net, issues: List[Issue], sound: Dict[str, Tuple[str, Set[str]]]) -> None:
    """E_NO_EVENT, E_DATA_BEFORE_PRODUCED, E_VAR_NEVER_SET, W_ISOLATED_NODE, loop warnings."""
    events = sorted(n for n in net.nodes if net.is_event(n) and net.specs[n] is not None)
    if not events:
        issues.append(_issue("E_NO_EVENT", None, "Ce flow n'a pas de node de depart",
                             "This flow has no start node", fix=_fix("add_node", type="event.button")))
    reached = _reach(net, events)
    # Dominance over the exec graph, plus Begin -> End (an empty list skips the body).
    preds = {n: set(net.exec_preds[n]) for n in net.nodes}
    for begin, (end, _) in sound.items():
        preds[end].add(begin)
    dom = _dominators(net, reached, preds, set(events))
    in_body = {n: b for b, (_, body) in sound.items() for n in body}

    def chain_readers(nid: str, seen: Set[str]) -> Set[str]:
        if net.runs_in_chain(nid):
            return {nid}
        out: Set[str] = set()
        for nxt in net.data_succ[nid]:
            if nxt not in seen:
                seen.add(nxt)
                out |= chain_readers(nxt, seen)
        return out

    for (dst, dport), link in net.data_in.items():
        src, _ = _split(link.from_)
        if not net.runs_in_chain(src):
            continue
        for reader in sorted(chain_readers(dst, {dst})):
            if reader == src or reader not in reached:
                continue
            if net.nodes[reader].type in ENDS and in_body.get(src) == net.nodes[reader].params.get("begin"):
                continue   # End.collect reads its body
            if net.nodes[reader].type == WHILE_BEGIN and in_body.get(src) == reader:
                continue   # the While condition is read again after each turn
            if src not in dom.get(reader, set()):
                issues.append(_issue("E_DATA_BEFORE_PRODUCED", dst,
                                     f"{dst} lit {src}, qui n'est pas execute avant lui", f"{dst} reads {src}, which does not run before it",
                                     port=dport, link=link))
                break
    # Variables read but never written.
    written = {str(n.params.get("name") or "") for n in net.nodes.values() if n.type == "data.set_variable"}
    defaults = {v.name for v in net.flow.variables if v.default is not None}
    for nid, node in net.nodes.items():
        name = str(node.params.get("name") or "")
        if node.type == "data.get_variable" and name in net.var_types and name not in written | defaults:
            issues.append(_issue("E_VAR_NEVER_SET", nid, f"La variable `{name}` est lue mais jamais ecrite",
                                 f"Variable `{name}` is read but never written", port="name",
                                 fix=_fix("add_set_variable", name=name, node=nid)))
    # Isolated nodes.
    for nid in net.nodes:
        if net.specs.get(nid) is None and net.nodes[nid].type != SUBNET_TYPE:
            continue
        if nid not in net.linked:
            issues.append(_issue("W_ISOLATED_NODE", nid, f"{nid} n'est relie a rien", f"{nid} is linked to nothing",
                                 fix=_fix("remove_node", node=nid)))
        elif net.runs_in_chain(nid) and nid not in reached:
            issues.append(_issue("W_ISOLATED_NODE", nid, f"{nid} n'est jamais atteint depuis un evenement",
                                 f"{nid} is never reached from an event", fix=_fix("remove_node", node=nid)))
    # Loop warnings.
    for begin, (end, body) in sound.items():
        for nid in sorted(body):
            if net.nodes[nid].type in LOOP_RISKY:
                label = net.specs[nid].label if net.specs.get(nid) else net.nodes[nid].type
                issues.append(_issue("W_DESTRUCTIVE_IN_LOOP", nid, f"{label} s'execute a chaque tour",
                                     f"{label} runs at each turn"))
        if net.nodes[begin].type == WHILE_BEGIN and not _while_can_exit(net, begin, body):
            issues.append(_issue("W_WHILE_NO_EXIT", begin, "Ce While ne s'arretera qu'au plafond de tours",
                                 "This While only stops at the turn ceiling", port="condition"))


def _while_can_exit(net: _Net, begin: str, body: Set[str]) -> bool:
    if any(net.nodes[n].type == "operator.break_loop" for n in body):
        return True
    link = net.data_in.get((begin, "condition"))
    if link is None:
        return False
    written = {str(net.nodes[n].params.get("name") or "") for n in body if net.nodes[n].type == "data.set_variable"}
    todo, seen = [_split(link.from_)[0]], set()
    while todo:
        cur = todo.pop()
        if cur in seen:
            continue
        seen.add(cur)
        node = net.nodes[cur]
        if cur in body or (node.type == "data.get_variable" and str(node.params.get("name") or "") in written):
            return True
        if cur == begin:
            continue
        todo += [_split(l.from_)[0] for (d, _), l in net.data_in.items() if d == cur]
    return False


def _check_subflows(net: _Net, issues: List[Issue], env: Env) -> None:
    if env.flow_loader is None:
        return
    me = net.flow.name
    for nid, node in net.nodes.items():
        if node.type != FLOW_CALL:
            continue
        called = str(node.params.get("flow") or "")
        if not called:
            continue
        path = _call_chain(called, env.flow_loader, [me])
        if path:
            issues.append(_issue("E_SUBFLOW_CYCLE", nid, " appelle ".join(path), " calls ".join(path), port="flow"))


def _call_chain(name: str, loader: Callable[[str], Optional[Flow]], chain: List[str]) -> Optional[List[str]]:
    """The call chain when *name* loops back or goes deeper than 8, else None."""
    chain = chain + [name]
    if name in chain[:-1] or len(chain) > MAX_SUBFLOW_DEPTH + 1:
        return chain
    try:
        flow = loader(name)
    except Exception:
        flow = None
    if flow is None:
        return None
    for node in flow.nodes.values():
        if node.type == FLOW_CALL and node.params.get("flow"):
            found = _call_chain(str(node.params["flow"]), loader, chain)
            if found:
                return found
    return None


def destructive_nodes(flow: Flow) -> List[str]:
    """Top-level node ids whose `!` is on (destructive flag true for their params)."""
    out = []
    for nid, node in flow.nodes.items():
        spec = None if node.type == SUBNET_TYPE else registry.get_node(node.type)
        if spec is not None and not node.bypass and flag_on(spec.destructive, spec, node.params):
            out.append(nid)
    return out


def _check_destructive(flow: Flow, issues: List[Issue], env: Env) -> None:
    tested = set(env.tested) if env.tested is not None else set()
    for nid in destructive_nodes(flow):
        if nid not in tested:
            label = flow.nodes[nid].label or registry.get_node(flow.nodes[nid].type).label
            issues.append(_issue("W_DESTRUCTIVE_UNTESTED", nid, f"{label} {nid} n'a jamais ete teste a blanc",
                                 f"{label} {nid} was never dry run"))


# -- entry points --------------------------------------------------------------------

def validate(flow: Flow, env: Optional[Env] = None) -> List[Issue]:
    """Every issue of *flow*, errors first, then by node."""
    env = env or Env()
    _ensure_team_nodes(flow)
    issues: List[Issue] = []
    for item in v1_limit_issues(flow):
        issues.append(_issue("E_PARAM_INVALID", item["node"], _cap(item["message"]),
                             "Farm mode does not exist yet (V2)", port="mode"))
    top = _Net(flow, flow.nodes, flow.links)
    _check_links(top, issues)
    _check_nodes(top, issues, env)
    _check_cycles(top, issues)
    sound = _check_blocks(top, issues)
    _check_flow_structure(top, issues, sound)
    _check_subflows(top, issues, env)
    _check_destructive(flow, issues, env)
    for nid, node in flow.nodes.items():
        if node.type == SUBNET_TYPE:
            inner = _Net(flow, node.nodes or {}, node.links or [])
            sub: List[Issue] = []
            _check_links(inner, sub)
            _check_nodes(inner, sub, env)
            for issue in sub:
                issue.message_fr, issue.message_en = f"[{nid}] {issue.message_fr}", f"[{nid}] {issue.message_en}"
            issues += sub
    if env.page_links:
        from flux_flows import page_links

        for broken in page_links.broken_by(flow, env.page_links):
            issues.append(_issue("W_PAGE_LINK_BROKEN", None,
                                 f"Ce changement casse la page {broken['page_label']} ({broken['label']} : "
                                 f"{broken['reason_fr']})",
                                 f"This change breaks the page {broken['page_label']} ({broken['label']}: "
                                 f"{broken['reason_en']})"))
    if env.shipped_changed:
        issues.append(_issue("W_SHIPPED_CHANGED", None, "Le flow livre a change depuis ta copie",
                             "The shipped flow changed since your copy"))
    issues.sort(key=lambda i: (i.level != ERROR, i.node or "", i.code))
    return issues


def validate_document(doc: Any, env: Optional[Env] = None) -> Tuple[Optional[Flow], List[Issue]]:
    """Parse then validate an editor document; a schema error is one E_SCHEMA issue."""
    try:
        flow = parse_flow(doc)
    except FlowSchemaError as exc:
        return None, [_issue("E_SCHEMA", None, str(exc), str(exc))]
    return flow, validate(flow, env)


def errors(issues: Iterable[Issue], *, dry_run: bool = False) -> List[Issue]:
    """The issues that block a run. ADR 0058, 5: a type mismatch does not block a dry run."""
    return [i for i in issues if i.level == ERROR and not (dry_run and i.code == "E_TYPE_MISMATCH")]


def unconfirmed_destructive(flow: Flow, previous: Optional[Flow], confirmed: Iterable[str]) -> List[Issue]:
    """E_DESTRUCTIVE_UNCONFIRMED: `!` nodes added (or switched to a destructive mode)
    since *previous* (None = new file: all of them) and missing from *confirmed*."""
    before = set(destructive_nodes(previous)) if previous is not None else set()
    ok = set(confirmed)
    out = []
    for nid in destructive_nodes(flow):
        if nid in before or nid in ok:
            continue
        label = flow.nodes[nid].label or registry.get_node(flow.nodes[nid].type).label
        out.append(_issue("E_DESTRUCTIVE_UNCONFIRMED", nid, f"{label} {nid} doit etre valide au curseur",
                          f"{label} {nid} must be confirmed with the slider"))
    return out


def _ensure_team_nodes(flow: Flow) -> None:
    from flux_flows.model import iter_nodes

    if any(n.type != SUBNET_TYPE and registry.get_node(n.type) is None for _, n in iter_nodes(flow)):
        try:
            from flux_flows.locations import team_nodes_dir

            registry.load_team_nodes(team_nodes_dir())   # a team node the catalog has not loaded yet
        except Exception:
            pass
