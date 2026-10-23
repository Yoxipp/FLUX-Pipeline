# logic.py — nodes that choose a path or compute a boolean (02_NODES §4). P2: if; P3: the rest.
#
# Switch compares with the EXACT value (no pattern); its exec outputs are
# case_0..case_7, one per entry of ``cases``, then ``default``. Compare ``matches``
# takes a Houdini style pattern (patterns.py).

from __future__ import annotations

from typing import Any

from flux_flows.nodes.common import as_path
from flux_flows.nodes.contract import EXEC_KEY, NodeError
from flux_flows.nodes.registry import flow_node, port

MAX_CASES = 8


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


_SWITCH_TYPES = ("str", "int", "float")


def _switch_cast(kind: str, value: Any) -> Any:
    try:
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
    except (TypeError, ValueError):
        raise NodeError(f"Switch : {value!r} n'est pas du type {kind}") from None
    return "" if value is None else str(value)


@flow_node("logic.switch", "Switch", icon="Split",
           inputs=[port("exec", "exec", required=True),
                   port("value", "any", "Valeur a comparer aux cas", "Value compared with the cases", "maya",
                        required=True)],
           outputs=[*(port(f"case_{i}", "exec", f"Si la valeur vaut le cas {i}", f"When the value equals case {i}")
                      for i in range(MAX_CASES)),
                    port("default", "exec", "Aucun cas", "No case"), port("on_error", "exec")],
           params=[port("cases", "list[any]", "Valeurs exactes, une sortie case_<rang> par valeur",
                        "Exact values, one case_<rank> output each", ["maya", "houdini"], default=[]),
                   port("type", "str", "str, int ou float", "str, int or float", "str", default="str",
                        choices=_SWITCH_TYPES)],
           shelf=21, aliases=["cas", "selon", "switch"],
           doc_fr="Prend la sortie du cas egal a la valeur (valeur exacte, pas de motif), sinon default.",
           doc_en="Takes the output of the case equal to the value (exact value, no pattern), else default.")
async def switch(ctx, inputs, params):
    kind = params.get("type") or "str"
    if kind not in _SWITCH_TYPES:
        raise NodeError(f"type : {', '.join(_SWITCH_TYPES)}", code="E_PARAM_INVALID")
    cases = params.get("cases") or []
    if not isinstance(cases, list) or len(cases) > MAX_CASES:
        raise NodeError(f"cases : liste de {MAX_CASES} valeurs au plus", code="E_PARAM_INVALID")
    value = _switch_cast(kind, inputs.get("value"))
    for index, case in enumerate(cases):
        if _switch_cast(kind, case) == value:
            ctx.log(f"cas {index} ({case!r})")
            return {EXEC_KEY: f"case_{index}"}
    ctx.log("aucun cas : default")
    return {EXEC_KEY: "default"}


_COMPARE_OPS = ("eq", "ne", "lt", "le", "gt", "ge", "contains", "startswith", "endswith", "matches")


def _compare(op: str, a: Any, b: Any) -> bool:
    if op == "eq":
        return a == b
    if op == "ne":
        return a != b
    if op in ("lt", "le", "gt", "ge"):
        try:
            if isinstance(a, str) and isinstance(b, str):
                x, y = a, b
            else:
                x, y = float(a), float(b)
        except (TypeError, ValueError):
            raise NodeError(f"Compare {op} : {a!r} et {b!r} ne se comparent pas") from None
        return {"lt": x < y, "le": x <= y, "gt": x > y, "ge": x >= y}[op]
    if op == "contains":
        if isinstance(a, (list, tuple, dict)):
            return b in a
        return str(b) in str(a)
    if op == "startswith":
        return str(a).startswith(str(b))
    if op == "endswith":
        return str(a).endswith(str(b))
    from flux_flows.patterns import PatternError, matches

    try:
        return matches(str(b), str(a))
    except PatternError as exc:
        raise NodeError(exc.message, code=exc.code) from None


@flow_node("logic.compare", "Compare", icon="Scale",
           inputs=[port("a", "any", "Premiere valeur", "First value", "shot_010.abc", required=True),
                   port("b", "any", "Seconde valeur (motif pour matches)", "Second value (pattern for matches)",
                        "*.abc", required=True)],
           outputs=[port("result", "bool", "Resultat", "Result", True)],
           params=[port("op", "str", ", ".join(_COMPARE_OPS), ", ".join(_COMPARE_OPS), "eq", default="eq",
                        choices=_COMPARE_OPS)],
           shelf=22, aliases=["comparer", "egal", "superieur"],
           doc_fr="Compare a et b ; matches teste a contre le motif b (`*.abc ^*_tmp*`).",
           doc_en="Compares a and b; matches tests a against the pattern b (`*.abc ^*_tmp*`).")
async def compare(ctx, inputs, params):
    op = params.get("op") or "eq"
    if op not in _COMPARE_OPS:
        raise NodeError(f"Operation inconnue '{op}' ({', '.join(_COMPARE_OPS)})", code="E_PARAM_INVALID")
    return {"result": _compare(op, inputs.get("a"), inputs.get("b"))}


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise NodeError(f"`{name}` : booleen attendu, recu {value!r}")
    return value


_BOOL_INPUTS = [port("a", "bool", "Premier booleen", "First boolean", True, required=True),
                port("b", "bool", "Deuxieme booleen", "Second boolean", True, required=True),
                port("c", "bool", "Troisieme (optionnel)", "Third (optional)"),
                port("d", "bool", "Quatrieme (optionnel)", "Fourth (optional)")]


def _bools(inputs) -> list:
    return [_bool(inputs.get(n), n) for n in ("a", "b", "c", "d") if n in ("a", "b") or inputs.get(n) is not None]


@flow_node("logic.and", "And", icon="Merge", inputs=_BOOL_INPUTS,
           outputs=[port("result", "bool", "Vrai si tous sont vrais", "True when all are true", True)],
           shelf=23, aliases=["et", "and"], doc_fr="Vrai si toutes les entrees sont vraies.",
           doc_en="True when every input is true.")
async def and_(ctx, inputs, params):
    return {"result": all(_bools(inputs))}


@flow_node("logic.or", "Or", icon="GitMerge", inputs=_BOOL_INPUTS,
           outputs=[port("result", "bool", "Vrai si au moins un est vrai", "True when one is true", True)],
           shelf=24, aliases=["ou", "or"], doc_fr="Vrai si au moins une entree est vraie.",
           doc_en="True when at least one input is true.")
async def or_(ctx, inputs, params):
    return {"result": any(_bools(inputs))}


@flow_node("logic.not", "Not", icon="Ban",
           inputs=[port("value", "bool", "Booleen", "Boolean", True, required=True)],
           outputs=[port("result", "bool", "Le contraire", "The opposite", False)],
           shelf=25, aliases=["non", "not", "inverse"], doc_fr="Le contraire du booleen.",
           doc_en="The opposite of the boolean.")
async def not_(ctx, inputs, params):
    return {"result": not _bool(inputs.get("value"), "value")}


@flow_node("logic.is_empty", "IsEmpty", icon="CircleDashed",
           inputs=[port("value", "any", "Valeur", "Value", [])],
           outputs=[port("result", "bool", "Vrai si vide ('', [], {}, rien)", "True when empty ('', [], {}, none)",
                         True)],
           shelf=26, aliases=["vide", "empty"], doc_fr="Vrai si la valeur est vide.",
           doc_en="True when the value is empty.")
async def is_empty(ctx, inputs, params):
    value = inputs.get("value")
    return {"result": value is None or value in ("", [], {}) or (isinstance(value, (list, tuple, dict)) and not value)}


@flow_node("logic.exists", "Exists", icon="FileSearch",
           inputs=[port("path", "path", "Chemin a tester", "Path to test", "$FLUX/DAILY", required=True)],
           outputs=[port("result", "bool", "Vrai si le chemin existe", "True when the path exists", True),
                    port("is_dir", "bool", "Vrai si c'est un dossier", "True when it is a folder", True)],
           shelf=27, aliases=["existe", "exists", "fichier"], doc_fr="Le fichier ou le dossier existe-t-il ?",
           doc_en="Does the file or folder exist?")
def exists(ctx, inputs, params):
    from core.paths import path_exists_safe

    path = as_path(ctx, inputs.get("path"))
    found = path_exists_safe(path)
    return {"result": found, "is_dir": found and path.is_dir()}


@flow_node("logic.select", "Select", icon="ToggleLeft",
           inputs=[port("condition", "bool", "Condition", "Condition", True, required=True),
                   port("a", "any", "Valeur si vrai", "Value when true", "maya", required=True),
                   port("b", "any", "Valeur si faux", "Value when false", "houdini", required=True)],
           outputs=[port("value", "any", "a ou b", "a or b", "maya")],
           shelf=28, aliases=["choisir", "ternaire", "select"], doc_fr="a si la condition est vraie, sinon b.",
           doc_en="a when the condition is true, else b.")
async def select(ctx, inputs, params):
    return {"value": inputs.get("a") if _bool(inputs.get("condition"), "condition") else inputs.get("b")}
