# logic.py — nodes that choose a path (02_NODES §4). P2: if.

from __future__ import annotations

from flux_flows.nodes.contract import EXEC_KEY, NodeError
from flux_flows.nodes.registry import flow_node, port


@flow_node("logic.if", "If", icon="GitBranch",
           inputs=[port("exec", "exec", required=True),
                   port("condition", "bool", "Condition a tester", "Condition to test", True, required=True)],
           outputs=[port("then", "exec", "Si vrai", "If true"), port("else", "exec", "Si faux", "If false"),
                    port("on_error", "exec")],
           shelf=20, aliases=["si", "condition", "branch"],
           doc_fr="Une seule branche s'execute : then si la condition est vraie, else sinon.",
           doc_en="Only one branch runs: then when the condition is true, else otherwise.")
async def if_(ctx, inputs, params):
    cond = inputs.get("condition")
    if not isinstance(cond, bool):
        raise NodeError(f"If attend un booleen, recu {cond!r} : utilise Compare")
    ctx.log("branche then" if cond else "branche else")
    return {EXEC_KEY: "then" if cond else "else"}
