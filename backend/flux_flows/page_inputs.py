# page_inputs.py — the Page node: a flow picks its TOOL page (ADR 0068).
#
# The link goes one way, flow -> page: an event.page_inputs node (InputsPageReader) names a page and copies its
# buttons (one exec output each) and fields (one data output each) into params.ports, the
# same way a FlowCall copies the interface of the flow it calls. The page knows nothing
# about flows; who listens to a page is found by reading the flows.
#
# A click runs every ACTIVE flow (perso of the clicker, team, project) whose active version
# has a Page node on that page with a link out of that button. Started another way
# (Schedule, editor Run, FlowCall), the data outputs of the node give the page defaults.

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from flux_flows import page_store, store
from flux_flows.model import Flow, Node
from flux_flows.pages import VALUE_KINDS, Page, iter_widgets
from flux_flows.store import FlowStoreError

PAGE_NODE = "event.page_inputs"
# Own outputs of the node, whatever the page.
OWN_OUTPUTS = ("button", "values")
# Field kind -> type of its output on the node (04 §3).
TYPE_FOR_KIND = {"float": "float", "int": "int", "text": "str", "path": "path", "dir": "dir", "toggle": "bool",
                 "select": "str", "list": "list[str]"}

Roots = Mapping[str, Optional[Path]]


def ports_of(page: Page) -> Dict[str, Any]:
    """params.ports of a Page node on *page*: {outputs: {id: type}, labels: {id: label}}."""
    outputs: Dict[str, str] = {}
    labels: Dict[str, str] = {}
    for w in iter_widgets(page):
        if w.id in OWN_OUTPUTS:
            continue
        if w.kind == "button":
            outputs[w.id] = "exec"
        elif w.kind in VALUE_KINDS:
            outputs[w.id] = TYPE_FOR_KIND[w.kind]
        else:
            continue
        labels[w.id] = w.label or w.id
    return {"outputs": outputs, "labels": labels}


def defaults_of(page: Page) -> Dict[str, Any]:
    return {w.id: w.default for w in iter_widgets(page) if w.kind in VALUE_KINDS and w.id not in OWN_OUTPUTS}


def buttons_of(page: Page) -> List[str]:
    return [w.id for w in iter_widgets(page) if w.kind == "button"]


def load_page(page_id: str, project: Optional[str]) -> Optional[Page]:
    """The winning page *page_id* (project > team), None when absent or unreadable."""
    from flux_flows import locations

    if not page_id:
        return None
    try:
        roots = locations.page_roots(project)
        scope = page_store.resolve(roots, page_id)
        if scope is None and roots.get("shipped") is not None                 and page_store.page_file(Path(roots["shipped"]), page_id).is_file():
            scope = "shipped"   # a template: its defaults stay readable (shipped example flows)
        return page_store.read_page(roots, scope, page_id)["page"] if scope else None
    except (FlowStoreError, ValueError, OSError):
        return None


def page_nodes(flow: Flow, page_id: Optional[str] = None) -> List[Tuple[str, Node]]:
    return [(nid, n) for nid, n in sorted(flow.nodes.items())
            if n.type == PAGE_NODE and (page_id is None or str(n.params.get("page") or "") == page_id)]


def linked_buttons(flow: Flow, nid: str) -> List[str]:
    """Buttons of the Page node *nid* that start something (a link out of their exec port)."""
    node = flow.nodes[nid]
    ports = ((node.params.get("ports") or {}).get("outputs") or {})
    out = {link.from_.split(".", 1)[1] for link in flow.links if link.from_.split(".", 1)[0] == nid}
    return [p for p, t in ports.items() if t == "exec" and p in out]


def node_outputs(node: Node, page: Optional[Page], payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Outputs of a Page node: the clicked button and the values of the click when the run
    was started by a click on its page, else the page defaults (no button)."""
    page_id = str(node.params.get("page") or "")
    if payload.get("page") == page_id and payload.get("button"):
        values = dict(payload.get("values") or {})
        base = defaults_of(page) if page is not None else {}
        values = {**base, **values}
        return {**values, "values": values, "button": str(payload["button"])}
    if page is not None:
        values = defaults_of(page)
    else:
        snap = (node.params.get("ports") or {}).get("defaults") or {}
        values = dict(snap)
    return {**values, "values": values, "button": ""}


def broken_links(flow: Flow, nid: str, page: Optional[Page]) -> List[Tuple[str, str]]:
    """(port, reason) for each linked output of the Page node *nid* the page no longer has."""
    if page is None:
        return []
    have = ports_of(page)["outputs"]
    out: List[Tuple[str, str]] = []
    used = {link.from_.split(".", 1)[1] for link in flow.links if link.from_.split(".", 1)[0] == nid}
    for port in sorted(used):
        if port in OWN_OUTPUTS:
            continue
        if port not in have:
            out.append((port, f"`{port}` n'est plus dans la page {page.id}"))
    return out


# -- who listens to a page -------------------------------------------------------

def _active_flows(flow_roots: Roots) -> List[Tuple[str, str, int]]:
    """(scope, name, active_version) of every active flow of the readable scopes."""
    out: List[Tuple[str, str, int]] = []
    for scope in ("perso", "team", "project"):
        root = flow_roots.get(scope)
        if root is None or not Path(root).is_dir():
            continue
        for name, version in store.active_names(Path(root)):
            out.append((scope, name, version))
    return out


def listeners(flow_roots: Roots, page_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """{button: [{flow, scope, version, node}]}: the active flows a click on *button* runs.
    A flow hidden by a higher scope of the same name is skipped (store.resolve)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for scope, name, version in _active_flows(flow_roots):
        if store.resolve(flow_roots, name) != scope:
            continue
        try:
            flow = store.read_flow(flow_roots, scope, name, version)["flow"]
        except FlowStoreError:
            continue
        for nid, _node in page_nodes(flow, page_id):
            for button in linked_buttons(flow, nid):
                out.setdefault(button, []).append({"flow": name, "scope": scope, "version": version, "node": nid})
    return out


def uses(flow_roots: Roots, page_id: str) -> List[Dict[str, Any]]:
    """Flows (working file) with a Page node on *page_id*, active or not, for the page
    editor ("lance par") : [{flow, scope, label, active, buttons, fields}]."""
    out: List[Dict[str, Any]] = []
    for entry in store.list_flows(flow_roots):
        scope, name = entry.get("scope"), entry.get("name")
        if not scope or not name or entry.get("error") or entry.get("shadowed"):
            continue
        try:
            flow = store.read_flow(flow_roots, scope, name)["flow"]
        except FlowStoreError:
            continue
        for nid, node in page_nodes(flow, page_id):
            used = {link.from_.split(".", 1)[1] for link in flow.links if link.from_.split(".", 1)[0] == nid}
            ports = ((node.params.get("ports") or {}).get("outputs") or {})
            out.append({"flow": name, "scope": scope, "label": entry.get("label") or name,
                        "active": bool(entry.get("active")), "node": nid,
                        "buttons": sorted(p for p in used if ports.get(p) == "exec"),
                        "fields": sorted(p for p in used if p in ports and ports[p] != "exec")})
    return out


def first_button(node: Node) -> str:
    """Editor Run without a click: the first button of the node."""
    ports = ((node.params.get("ports") or {}).get("outputs") or {})
    return next((p for p, t in ports.items() if t == "exec"), "")
