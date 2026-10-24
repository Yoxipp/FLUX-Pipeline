# page_links.py — links between TOOL pages and flows, by readable id (04_PAGES_TOOL §4).
#
# A page points to flows three ways: a button (on_click: flow + button_id, the flow
# holds an event.button node with that button_id), a field (bind: flow + param of the
# interface) and a data widget (source: flow + output). Nothing points back from the
# flow: the reverse index is rebuilt from the page files (they are small and few).
#
# Renaming keeps both sides in step in one operation (plan, then apply):
#   * a button widget id = its button_id: the page and the event.button nodes change;
#     the flow side is a new frozen version (the active one keeps the old id until the
#     TD activates the new one, P_BUTTON_MISSING_IN_FLOW says so meanwhile);
#   * an interface param of a flow: every bind.param of every page changes (the flow
#     editor writes the flow itself).
# Rights are checked by the router; this module only plans and writes.

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from flux_flows import page_store, store
from flux_flows.model import NODE_ID_RE, Flow, Node, iter_nodes
from flux_flows.pages import (FEEDS, FIELD_ID_RE, VALUE_KINDS, Page, PageIssue, _issue, iter_widgets, parse_page,
                              to_document)
from flux_flows.store import FlowStoreError

Roots = Mapping[str, Optional[Path]]


# -- index --------------------------------------------------------------------

def page_links(page: Page) -> List[Dict[str, Any]]:
    """Every link of *page* to a flow: {widget, label, kind, role, flow, button_id | param | output}."""
    out: List[Dict[str, Any]] = []
    for w in iter_widgets(page):
        base = {"widget": w.id, "label": w.label or w.id, "kind": w.kind}
        if w.kind == "button" and w.on_click is not None:
            out.append({**base, "role": "button", "flow": w.on_click.flow, "button_id": w.on_click.button_id})
        elif w.kind in VALUE_KINDS and w.bind is not None:
            out.append({**base, "role": "bind", "flow": w.bind.flow, "param": w.bind.param})
        elif w.source is not None and w.source.flow is not None:
            out.append({**base, "role": "source", "flow": w.source.flow, "output": w.source.output})
    return out


def all_links(page_roots: Roots) -> List[Dict[str, Any]]:
    """Links of every readable page of team and project (shadowed pages included:
    they still exist and a TD may un-hide them)."""
    out: List[Dict[str, Any]] = []
    for entry in page_store.list_pages(page_roots):
        if entry["error"]:
            continue
        try:
            page = page_store.read_page(page_roots, entry["scope"], entry["id"])["page"]
        except FlowStoreError:
            continue
        for link in page_links(page):
            out.append({"page": entry["id"], "page_label": entry["label"], "scope": entry["scope"],
                        "shadowed": entry["shadowed"], **link})
    return out


def index(page_roots: Roots) -> Dict[str, List[Dict[str, Any]]]:
    """GET /flows/pages/links: {flow: [{page, scope, widget, kind, role, ...}]}."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for link in all_links(page_roots):
        out.setdefault(link["flow"], []).append({k: v for k, v in link.items() if k != "flow"})
    return out


def buttons(page_roots: Roots) -> List[Dict[str, Any]]:
    """Page buttons for the "Bouton" list of the event.button node: <page> / <label> (id)."""
    return [{"page": l["page"], "page_label": l["page_label"], "scope": l["scope"], "widget": l["widget"],
             "label": l["label"], "flow": l["flow"], "button_id": l["button_id"]}
            for l in all_links(page_roots) if l["role"] == "button"]


def button_ids(flow: Flow) -> List[str]:
    return [str(n.params.get("button_id")) for _, n in iter_nodes(flow)
            if n.type == "event.button" and n.params.get("button_id")]


# -- checks -------------------------------------------------------------------

def orphan_issues(page: Page, lookup: Callable[[str], Any], links: List[Dict[str, Any]]) -> List[PageIssue]:
    """P_BUTTON_ORPHAN: a flow this page launches waits for a button no page shows."""
    shown = {(l["flow"], l["button_id"]) for l in links if l["role"] == "button"}
    shown |= {(l["flow"], l["button_id"]) for l in page_links(page) if l["role"] == "button"}
    issues: List[PageIssue] = []
    for flow_name in sorted({l["flow"] for l in page_links(page) if l["role"] == "button"}):
        info = lookup(flow_name)
        if info is None:
            continue
        for bid in button_ids(info.flow):
            if (flow_name, bid) not in shown:
                issues.append(_issue("P_BUTTON_ORPHAN", None,
                                     f"Le flow `{flow_name}` attend un bouton `{bid}` qu'aucune page ne montre : "
                                     "il ne se lance que depuis l'editeur.",
                                     f"The flow `{flow_name}` waits for a button `{bid}` no page shows: "
                                     "it only starts from the editor.",
                                     {"kind": "add_button", "args": {"flow": flow_name, "button_id": bid}}))
    return issues


def broken_by(flow: Flow, links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Links of the pages to *flow* that this version of the flow breaks (W_PAGE_LINK_BROKEN)."""
    inputs = {i.id: i.type for i in flow.interface.inputs}
    outputs = {o.id for o in flow.interface.outputs}
    ids = set(button_ids(flow))
    out = []
    for l in links:
        if l.get("flow", flow.name) != flow.name:
            continue
        if l["role"] == "button" and l["button_id"] not in ids:
            out.append({**l, "reason_fr": f"bouton `{l['button_id']}` sans node Bouton",
                        "reason_en": f"button `{l['button_id']}` without a Button node"})
        elif l["role"] == "bind" and l["param"] not in inputs:
            out.append({**l, "reason_fr": f"parametre `{l['param']}` disparu", "reason_en": f"parameter `{l['param']}` gone"})
        elif l["role"] == "bind" and inputs[l["param"]] not in FEEDS.get(l["kind"], ()):
            out.append({**l, "reason_fr": f"parametre `{l['param']}` de type {inputs[l['param']]}",
                        "reason_en": f"parameter `{l['param']}` of type {inputs[l['param']]}"})
        elif l["role"] == "source" and l["output"] not in outputs:
            out.append({**l, "reason_fr": f"sortie `{l['output']}` disparue", "reason_en": f"output `{l['output']}` gone"})
    return out


# -- writes on the flow side --------------------------------------------------

def _writable_flow(flow_roots: Roots, name: str) -> str:
    scope = store.resolve(flow_roots, name)
    if scope is None:
        raise FlowStoreError(f"flow {name} introuvable", 404)
    if scope == "shipped":
        raise FlowStoreError(f"le flow {name} est livre (lecture seule) : fais-en une copie d'equipe d'abord", 409)
    return scope


def _free_node_id(flow: Flow, button_id: str) -> str:
    taken = {nid for nid, _ in iter_nodes(flow)}
    base = f"btn_{button_id}"[:31].rstrip("_")
    candidate, n = base, 2
    while candidate in taken or not NODE_ID_RE.match(candidate):
        suffix = f"_{n}"
        candidate, n = base[:31 - len(suffix)] + suffix, n + 1
    return candidate


def _write_flow(flow_roots: Roots, scope: str, flow: Flow, revision: int, user: str, note: str,
                validator: Optional[Callable[[str, Flow], Optional[bool]]]) -> Dict[str, Any]:
    valid = validator(scope, flow) if validator else None
    done = store.increment_flow(flow_roots, scope, flow.name, user=user, flow=flow, base_revision=revision,
                                note=note, valid=valid)
    return {"flow": flow.name, "scope": scope, "version": done["created"] or done["state"]["current"],
            "revision": done["state"]["revision"]}


def ensure_button_node(flow_roots: Roots, name: str, button_id: str, *, user: str,
                       validator: Optional[Callable[[str, Flow], Optional[bool]]] = None) -> Dict[str, Any]:
    """"Au clic": add an event.button node with *button_id* to the flow (new frozen
    version), or take the one that exists. {flow, scope, node, created, version}."""
    if not FIELD_ID_RE.match(button_id or ""):
        raise FlowStoreError(f"id de bouton invalide '{button_id}'")
    scope = _writable_flow(flow_roots, name)
    got = store.read_flow(flow_roots, scope, name)
    flow = got["flow"]
    for nid, node in flow.nodes.items():
        if node.type == "event.button" and node.params.get("button_id") == button_id:
            return {"flow": name, "scope": scope, "node": nid, "created": False, "version": None}
    nid = _free_node_id(flow, button_id)
    xs = [n.pos[0] for n in flow.nodes.values()] or [0.0]
    ys = [n.pos[1] for n in flow.nodes.values() if n.type.startswith("event.")] or [-160.0]
    flow.nodes[nid] = Node(type="event.button", pos=(min(xs), max(ys) + 160), params={"button_id": button_id})
    done = _write_flow(flow_roots, scope, flow, got["state"]["revision"], user,
                       f"bouton de page {button_id}", validator)
    return {**done, "node": nid, "created": True}


# -- rename -------------------------------------------------------------------

def _file(roots: Roots, scope: str, page_id: str) -> str:
    return str(Path(roots[scope]) / f"{page_id}{page_store.SUFFIX}") if roots.get(scope) else page_id


def plan_widget_rename(page_roots: Roots, flow_roots: Roots, scope: str, page_id: str, old: str,
                       new: str) -> Dict[str, Any]:
    """What renaming widget *old* to *new* changes: {files: [{kind, scope, id, path}], flows: [...]}."""
    if not FIELD_ID_RE.match(new or ""):
        raise FlowStoreError(f"`{new}` n'est pas un id valide : minuscules, chiffres et _", 400)
    page = page_store.read_page(page_roots, scope, page_id)["page"]
    ids = [w.id for w in iter_widgets(page)]
    if old not in ids:
        raise FlowStoreError(f"la page {page_id} n'a pas de widget `{old}`", 404)
    if new != old and new in ids:
        raise FlowStoreError(f"l'id `{new}` existe deja dans cette page", 409)
    files = [{"kind": "page", "scope": scope, "id": page_id, "path": _file(page_roots, scope, page_id)}]
    flows = []
    for w in iter_widgets(page):
        if w.id == old and w.kind == "button" and w.on_click is not None and w.on_click.button_id == old:
            fscope = store.resolve(flow_roots, w.on_click.flow)
            if fscope is not None:
                got = store.read_flow(flow_roots, fscope, w.on_click.flow)
                if old in button_ids(got["flow"]):
                    flows.append({"kind": "flow", "scope": fscope, "id": w.on_click.flow,
                                  "next_version": (got["state"].get("current") or 0) + 1})
    return {"files": files + flows, "flows": flows}


def apply_widget_rename(page_roots: Roots, flow_roots: Roots, scope: str, page_id: str, old: str, new: str, *,
                        user: str, base_rev: Optional[str] = None,
                        validator: Optional[Callable[[str, Flow], Optional[bool]]] = None) -> Dict[str, Any]:
    """Flow first, page second (04 §4: a failed page write leaves an orphan node, P_BUTTON_ORPHAN, nothing lost)."""
    plan = plan_widget_rename(page_roots, flow_roots, scope, page_id, old, new)
    written = []
    for f in plan["flows"]:
        got = store.read_flow(flow_roots, f["scope"], f["id"])
        flow = got["flow"]
        for _, node in iter_nodes(flow):
            if node.type == "event.button" and node.params.get("button_id") == old:
                node.params = {**node.params, "button_id": new}
        written.append(_write_flow(flow_roots, f["scope"], flow, got["state"]["revision"], user,
                                   f"bouton renomme {old} -> {new}", validator))
    got = page_store.read_page(page_roots, scope, page_id)
    doc = to_document(got["page"])
    _rename_in_doc(doc.get("layout") or [], old, new)
    saved = page_store.save_page(page_roots, scope, parse_page(doc), user=user,
                                 base_rev=base_rev or got["rev"])
    return {"page": {"scope": scope, "id": page_id, **saved}, "flows": written}


def _rename_in_doc(items: List[Dict[str, Any]], old: str, new: str) -> None:
    for item in items:
        if "row" in item:
            for w in item["row"]:
                if w.get("id") == old:
                    w["id"] = new
                    click = w.get("on_click")
                    if w.get("kind") == "button" and click and click.get("button_id") == old:
                        click["button_id"] = new
        _rename_in_doc(item.get("children") or [], old, new)


def plan_param_rename(page_roots: Roots, flow: str, old: str, new: str) -> Dict[str, Any]:
    """Pages whose fields are bound to *flow*.*old*: {files: [{kind, scope, id, path, widgets}]}."""
    if not FIELD_ID_RE.match(new or ""):
        raise FlowStoreError(f"`{new}` n'est pas un id valide : minuscules, chiffres et _", 400)
    by_page: Dict[tuple, List[str]] = {}
    for l in all_links(page_roots):
        if l["role"] == "bind" and l["flow"] == flow and l["param"] == old:
            by_page.setdefault((l["scope"], l["page"]), []).append(l["widget"])
    return {"files": [{"kind": "page", "scope": s, "id": p, "path": _file(page_roots, s, p), "widgets": ws}
                      for (s, p), ws in sorted(by_page.items())]}


def apply_param_rename(page_roots: Roots, flow: str, old: str, new: str, *, user: str,
                       scopes_allowed: Optional[Callable[[str], bool]] = None) -> Dict[str, Any]:
    plan = plan_param_rename(page_roots, flow, old, new)
    refused = [f for f in plan["files"] if scopes_allowed and not scopes_allowed(f["scope"])]
    if refused:
        raise FlowStoreError("Case Team TD requise pour modifier la page "
                             + ", ".join(f["id"] for f in refused), 403, {"required": "team_td"})
    done = []
    for f in plan["files"]:
        got = page_store.read_page(page_roots, f["scope"], f["id"])
        doc = to_document(got["page"])
        _rebind_in_doc(doc.get("layout") or [], flow, old, new)
        saved = page_store.save_page(page_roots, f["scope"], parse_page(doc), user=user, base_rev=got["rev"])
        done.append({"scope": f["scope"], "id": f["id"], **saved})
    return {"pages": done}


def _rebind_in_doc(items: List[Dict[str, Any]], flow: str, old: str, new: str) -> None:
    for item in items:
        for w in item.get("row") or []:
            bind = w.get("bind")
            if bind and bind.get("flow") == flow and bind.get("param") == old:
                bind["param"] = new
        _rebind_in_doc(item.get("children") or [], flow, old, new)
