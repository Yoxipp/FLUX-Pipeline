# event.py — nodes that start a flow (02_NODES §2). P2: button and manual.
#
# An event has no incoming exec. Its outputs are the trigger payload: ``values``
# (the interface values) plus one port per interface id (01 §9).

from __future__ import annotations

from flux_flows.nodes.registry import flow_node, port

_THEN = port("then", "exec", "Suite du flow", "Next step")
_VALUES = port("values", "dict", "Valeurs de l'interface du flow", "Values of the flow interface",
               {"dest_folder": "$FLUX/DAILY"})


def _payload(ctx, inputs, params):
    values = dict(ctx.interface)
    return {**values, "values": values}


@flow_node("event.button", "Button", icon="MousePointerClick", outputs=[_THEN, _VALUES],
           params=[port("button_id", "str", "Bouton de page qui lance ce flow", "Page button that starts this flow",
                        "daily_render")],
           shelf=1, aliases=["bouton", "page", "start"],
           doc_fr="Part quand on clique le bouton d'une page TOOL, ou avec Run dans l'editeur.",
           doc_en="Starts when a TOOL page button is clicked, or with Run in the editor.")
async def button(ctx, inputs, params):
    return _payload(ctx, inputs, params)


@flow_node("event.manual", "Manual", icon="Play", outputs=[_THEN, _VALUES], shelf=0,
           aliases=["start", "depart", "run"],
           doc_fr="Depart a la main (Run de l'editeur) ou par un autre flow.",
           doc_en="Manual start (editor Run) or from another flow.")
async def manual(ctx, inputs, params):
    return _payload(ctx, inputs, params)
