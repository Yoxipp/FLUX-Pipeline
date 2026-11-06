# page_links.py — what a TOOL page reads from flows (04_PAGES_TOOL §4, ADR 0068).
#
# Since ADR 0068 a page no longer starts flows (an InputsPageReader node in the flow picks
# the page, see page_inputs.py). The only page -> flow link left is a data widget showing
# an interface output of a flow's last run (source: flow + output).

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from flux_flows import page_store
from flux_flows.model import Flow
from flux_flows.pages import Page, iter_widgets
from flux_flows.store import FlowStoreError

Roots = Mapping[str, Optional[Path]]


# -- index --------------------------------------------------------------------

def page_links(page: Page) -> List[Dict[str, Any]]:
    """Every link of *page* to a flow: {widget, label, kind, role: source, flow, output}."""
    out: List[Dict[str, Any]] = []
    for w in iter_widgets(page):
        base = {"widget": w.id, "label": w.label or w.id, "kind": w.kind}
        if w.source is not None and w.source.flow is not None:
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


def broken_by(flow: Flow, links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Links of the pages to *flow* that this version of the flow breaks (W_PAGE_LINK_BROKEN)."""
    outputs = {o.id for o in flow.interface.outputs}
    out = []
    for l in links:
        if l.get("flow", flow.name) != flow.name:
            continue
        if l["role"] == "source" and l["output"] not in outputs:
            out.append({**l, "reason_fr": f"sortie `{l['output']}` disparue", "reason_en": f"output `{l['output']}` gone"})
    return out
