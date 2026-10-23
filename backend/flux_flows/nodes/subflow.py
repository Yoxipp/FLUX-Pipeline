# subflow.py — calling another flow (02_NODES §10). P3.
#
# flow_call runs the called flow inline (engine Run.call_flow: child run with the
# same project, user and mode, started at its event.manual, depth 8 at most, a
# flow already in the call chain = E_SUBFLOW_CYCLE). Its inputs are the called
# flow's interface ids: linked inputs (dynamic ports) or literals in params of the
# same name. Its outputs are the values set by the called flow's flow_output nodes
# (ids of interface.outputs), plus run_id.

from __future__ import annotations

from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

FLOW_CALL = "subflow.flow_call"
FLOW_OUTPUT = "subflow.flow_output"
_OWN_PARAMS = ("flow", "version", "timeout_s", "ports")


@flow_node(FLOW_CALL, "FlowCall", icon="Workflow",
           inputs=[port("exec", "exec", required=True)],
           outputs=[port("then", "exec"), port("on_error", "exec"),
                    port("run_id", "str", "Run du flow appele", "Run of the called flow")],
           params=[port("flow", "str", "Nom du flow appele (perso, projet, equipe, livre)",
                        "Called flow name (perso, project, team, shipped)", "export_caches", required=True),
                   port("version", "str", "current (fichier de travail) ou un numero de version",
                        "current (working file) or a version number", "current", default="current")],
           shelf=90, aliases=["sous-flow", "appeler", "subflow"],
           doc_fr="Appelle un autre flow : ses parametres exposes deviennent les entrees, ses FlowOutput les sorties.",
           doc_en="Calls another flow: its exposed parameters become inputs, its FlowOutput nodes the outputs.")
async def flow_call(ctx, inputs, params):
    name = str(params.get("flow") or "")
    if not name:
        raise NodeError("FlowCall attend `flow`")
    values = {k: v for k, v in params.items() if k not in _OWN_PARAMS}
    values.update({k: v for k, v in inputs.items() if k != "exec" and v is not None})
    return await ctx.call_flow(name, params.get("version") or "current", values)


@flow_node(FLOW_OUTPUT, "FlowOutput", icon="LogOut",
           inputs=[port("exec", "exec", required=True),
                   port("value", "any", "Valeur rendue au flow appelant", "Value given back to the caller",
                        required=True)],
           outputs=[port("then", "exec")],
           params=[port("id", "str", "Sortie declaree dans interface.outputs", "Output declared in interface.outputs",
                        "scene", required=True)],
           shelf=91, aliases=["sortie", "retour", "output"],
           doc_fr="Rend une valeur au FlowCall qui a appele ce flow.",
           doc_en="Gives a value back to the FlowCall that called this flow.")
async def flow_output(ctx, inputs, params):
    ident = str(params.get("id") or "")
    ctx.set_output(ident, inputs.get("value"))
    ctx.log(f"sortie {ident} = {inputs.get('value')!r}")
    return {}
