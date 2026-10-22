# data.py — nodes that give a value (02_NODES §3). P2: value, get / set variable, flow_input.
#
# Pure except set_variable. Variables are local to a run (01 §4): the engine
# owns them, casts a written value to the declared type and counts the writes.

from __future__ import annotations

from typing import Any

from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

VALUE_TYPES = ("str", "int", "float", "bool", "list", "dict", "pattern")
_TRUE = ("1", "true", "yes", "oui", "on")
_FALSE = ("0", "false", "no", "non", "off", "")


def cast_literal(kind: str, value: Any) -> Any:
    """Cast a literal typed in Params. Raises NodeError with a readable message."""
    try:
        if value is None:
            return None
        if kind in ("str", "pattern", "path", "dir"):
            return value if isinstance(value, str) else str(value)
        if kind == "int":
            if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
                raise ValueError
            return int(value)
        if kind == "float":
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        if kind == "bool":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in _TRUE or text in _FALSE:
                return text in _TRUE
            raise ValueError
        if kind == "list" or kind.startswith("list["):
            if not isinstance(value, (list, tuple)):
                raise ValueError
            return list(value)
        if kind == "dict":
            if not isinstance(value, dict):
                raise ValueError
            return dict(value)
    except (TypeError, ValueError):
        raise NodeError(f"La valeur {value!r} n'est pas du type {kind}") from None
    return value


@flow_node("data.value", "Value", icon="Hash",
           outputs=[port("value", "any", "La valeur saisie", "The typed value", 3)],
           params=[port("type", "str", "Type de la valeur", "Value type", "int", default="str"),
                   port("value", "any", "Valeur", "Value", 3)],
           shelf=10, aliases=["constante", "const", "nombre", "texte"],
           doc_fr="Une valeur fixe : texte, nombre, booleen, liste, dictionnaire ou motif.",
           doc_en="A fixed value: text, number, boolean, list, dict or pattern.")
async def value(ctx, inputs, params):
    kind = params.get("type") or "str"
    if kind not in VALUE_TYPES:
        raise NodeError(f"Type inconnu '{kind}' (attendu : {', '.join(VALUE_TYPES)})")
    return {"value": cast_literal(kind, params.get("value"))}


@flow_node("data.get_variable", "GetVariable", icon="Variable",
           outputs=[port("value", "any", "Valeur courante de la variable", "Current value of the variable")],
           params=[port("name", "str", "Variable declaree du flow", "Declared flow variable", "copied", required=True)],
           shelf=11, aliases=["variable", "lire"],
           doc_fr="Lit une variable du flow (locale au run).",
           doc_en="Reads a flow variable (local to the run).")
async def get_variable(ctx, inputs, params):
    return {"value": ctx.get_variable(params.get("name") or "")}


@flow_node("data.set_variable", "SetVariable", icon="PenLine",
           inputs=[port("exec", "exec", required=True),
                   port("value", "any", "Nouvelle valeur", "New value", 1, required=True)],
           outputs=[port("then", "exec"), port("on_error", "exec"),
                    port("value", "any", "Valeur ecrite (apres conversion)", "Written value (converted)")],
           params=[port("name", "str", "Variable declaree du flow", "Declared flow variable", "copied", required=True)],
           shelf=12, aliases=["variable", "ecrire", "assigner"],
           doc_fr="Ecrit une variable du flow, convertie selon son type.",
           doc_en="Writes a flow variable, converted to its type.")
async def set_variable(ctx, inputs, params):
    written = ctx.set_variable(params.get("name") or "", inputs.get("value"))
    ctx.log(f"variable {params.get('name')} = {written!r}")
    return {"value": written}


@flow_node("data.flow_input", "FlowInput", icon="LogIn",
           outputs=[port("value", "any", "Valeur du parametre expose", "Value of the exposed parameter")],
           params=[port("id", "str", "Parametre de l'interface du flow", "Flow interface parameter", "dest_folder",
                        required=True)],
           shelf=13, aliases=["parametre", "interface", "entree"],
           doc_fr="Valeur d'un parametre expose du flow (saisi dans la page, sinon son defaut).",
           doc_en="Value of an exposed flow parameter (typed in the page, else its default).")
async def flow_input(ctx, inputs, params):
    ident = params.get("id") or ""
    if ident not in ctx.interface:
        raise NodeError(f"Le parametre `{ident}` n'est pas dans l'interface du flow")
    return {"value": ctx.interface[ident]}
