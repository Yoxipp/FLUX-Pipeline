# Team node template (02_NODES §1). Copy this file into CONFIG/extensions/nodes/,
# rename it and the node type, then open Tab in the flow editor: the file is
# reloaded as soon as it changes, no restart. A file that fails to import shows
# its error in the catalog; the other nodes keep working.
#
# Rules:
#   * type "<family>.<name>", family among event data logic operator action flux
#     session dcc bridge subflow ; never a FLUX type (refused).
#   * body(ctx, inputs, params) -> dict of outputs ; raise NodeError for a message
#     the artist can read on the node.
#   * a node that writes, moves, sends or launches anything sets effect=True (or
#     destructive=...) and gives simulate(ctx, inputs, params) -> {lines, outputs}
#     that writes nothing (dry run).
#   * team nodes run with FLUX's own rights: keep them in the team folder only.

from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port


def _simulate(ctx, inputs, params):
    return {"lines": [{"kind": "team", "text_fr": f"saluerait {inputs.get('name') or '?'}"}],
            "outputs": {"text": ""}}


@flow_node("data.team_hello", "TeamHello", icon="Smile",
           inputs=[port("exec", "exec", required=True),
                   port("name", "str", "Nom a saluer", "Name to greet", "ADAM", required=True)],
           outputs=[port("then", "exec"), port("on_error", "exec"),
                    port("text", "str", "Message", "Message", "Bonjour ADAM")],
           params=[port("prefix", "str", "Debut du message", "Message start", "Bonjour", default="Bonjour")],
           effect=True, simulate=_simulate, aliases=["exemple", "modele"],
           doc_fr="Exemple de node d'equipe : construit un message et l'ecrit dans le log du node.",
           doc_en="Team node example: builds a message and writes it in the node log.")
def team_hello(ctx, inputs, params):
    name = str(inputs.get("name") or "").strip()
    if not name:
        raise NodeError("TeamHello attend `name`")
    text = f"{params.get('prefix') or 'Bonjour'} {name}"
    ctx.log(text, "info")
    return {"text": text}
