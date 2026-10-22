# operator.py — nodes that compute and loop (02_NODES §5). P2: foreach_begin / foreach_end.
#
# The engine runs the block (01 §4): Begin's body checks the list, then the engine
# runs the chain from ``loop`` once per item up to the End whose ``params.begin``
# names this Begin, and goes on from End.done. ``mode`` is reserved for V2 work
# items: stored, ignored.

from __future__ import annotations

from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

FOREACH_BEGIN = "operator.foreach_begin"
FOREACH_END = "operator.foreach_end"
MAX_ITEMS = 10000
ITEMS_KEY = "_items"


@flow_node(FOREACH_BEGIN, "ForEachBegin", icon="Repeat1",
           inputs=[port("exec", "exec", required=True),
                   port("list", "list[any]", "Liste a parcourir", "List to walk", ["a.abc", "b.abc"], required=True)],
           outputs=[port("loop", "exec", "Corps de la boucle, une fois par element", "Loop body, once per item"),
                    port("item", "any", "Element courant", "Current item", "a.abc"),
                    port("index", "int", "Rang de l'element (0 d'abord)", "Item rank (0 first)", 0),
                    port("count", "int", "Nombre d'elements", "Number of items", 2),
                    port("on_error", "exec")],
           params=[port("mode", "str", "Reserve V2 (work items)", "Reserved for V2 (work items)", "sequential",
                        default="sequential"),
                   port("max_items", "int", "Nombre maximal d'elements", "Maximum number of items", MAX_ITEMS,
                        default=MAX_ITEMS)],
           shelf=30, aliases=["boucle", "loop", "pour chaque"],
           doc_fr="Execute le corps une fois par element de la liste. Liste vide = corps saute.",
           doc_en="Runs the body once per list item. Empty list = body skipped.")
async def foreach_begin(ctx, inputs, params):
    items = inputs.get("list")
    if items is None:
        items = []
    if isinstance(items, (tuple, set)):
        items = list(items)
    if not isinstance(items, list):
        raise NodeError(f"ForEach attend une liste, recu {type(items).__name__}")
    limit = params.get("max_items") or MAX_ITEMS
    if len(items) > int(limit):
        raise NodeError(f"{len(items)} elements : maximum {limit} (parametre max_items)")
    return {ITEMS_KEY: items, "count": len(items)}


@flow_node(FOREACH_END, "ForEachEnd", icon="Repeat1",
           inputs=[port("exec", "exec", required=True),
                   port("collect", "any", "Valeur gardee a chaque tour", "Value kept at each turn")],
           outputs=[port("done", "exec", "Suite, une fois la boucle finie", "Next, once the loop is done"),
                    port("results", "list[any]", "Valeurs de collect, une par tour", "collect values, one per turn"),
                    port("on_error", "exec")],
           params=[port("begin", "str", "Id du ForEachBegin apparie (pose par l'editeur)",
                        "Id of the paired ForEachBegin (set by the editor)", "n3", required=True)],
           shelf=31, aliases=["boucle", "fin"],
           doc_fr="Ferme la boucle de son ForEachBegin ; results liste les valeurs de collect.",
           doc_en="Closes the loop of its ForEachBegin; results lists the collect values.")
async def foreach_end(ctx, inputs, params):
    # Driven by the engine (a body for the catalog and direct calls only).
    return {}
