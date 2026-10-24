# operator.py — nodes that compute and loop (02_NODES §5). P2: foreach; P3: the rest.
#
# The engine runs the blocks (01 §4): Begin's body checks its inputs, then the
# engine runs the chain from ``loop`` once per turn up to the End whose
# ``params.begin`` names this Begin, and goes on from End.done. ForEach walks a
# list, For an inclusive range (start..end, step), While reads its condition again
# after each turn (max_iterations, error at the ceiling; one turn in a dry run).
# BreakLoop leaves the innermost loop. Sequence runs then_0, then_1... one after
# the other (one link per exec output, A3). ``mode`` is reserved for V2 work
# items: stored, ignored.

from __future__ import annotations

import math as _math
import os
import re
from datetime import datetime, timedelta
from pathlib import Path, PurePath
from typing import Any, List

from flux_flows.nodes.common import as_bool, as_list, as_path
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

FOREACH_BEGIN = "operator.foreach_begin"
FOREACH_END = "operator.foreach_end"
FOR_BEGIN = "operator.for_begin"
FOR_END = "operator.for_end"
WHILE_BEGIN = "operator.while_begin"
WHILE_END = "operator.while_end"
BREAK_LOOP = "operator.break_loop"
SEQUENCE = "operator.sequence"
BLOCK_ENDS = {FOREACH_BEGIN: FOREACH_END, FOR_BEGIN: FOR_END, WHILE_BEGIN: WHILE_END}
MAX_ITEMS = 10000
MAX_ITERATIONS = 1000
MAX_SEQUENCE = 8
ITEMS_KEY = "_items"
CONDITION_KEY = "_condition"
LIMIT_KEY = "_limit"
SEQUENCE_KEY = "_sequence"
LOOP_MODES = ("sequential",)              # ``mode`` of the loop begins (V2 adds work items)
MATCH_ON = ("name", "path")               # operator.list_filter
SORT_KEYS = ("natural", "name", "date", "size")   # operator.list_sort


@flow_node(FOREACH_BEGIN, "ForEachBegin", icon="Repeat1",
           inputs=[port("exec", "exec", required=True),
                   port("list", "list[any]", "Liste a parcourir", "List to walk", ["a.abc", "b.abc"], required=True)],
           outputs=[port("loop", "exec", "Corps de la boucle, une fois par element", "Loop body, once per item"),
                    port("item", "any", "Element courant", "Current item", "a.abc"),
                    port("index", "int", "Rang de l'element (0 d'abord)", "Item rank (0 first)", 0),
                    port("count", "int", "Nombre d'elements", "Number of items", 2),
                    port("on_error", "exec")],
           params=[port("mode", "str", "Reserve V2 (work items)", "Reserved for V2 (work items)", "sequential",
                        default="sequential", choices=LOOP_MODES),
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


# -- blocks (P3) ------------------------------------------------------------------

def _int(value: Any, what: str) -> int:
    try:
        if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
            raise ValueError
        return int(value)
    except (TypeError, ValueError):
        raise NodeError(f"{what} : nombre entier attendu, recu {value!r}", code="E_PARAM_INVALID") from None


def _float(value: Any, what: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        return float(value)
    except (TypeError, ValueError):
        raise NodeError(f"{what} : nombre attendu, recu {value!r}") from None


@flow_node(SEQUENCE, "Sequence", icon="ListStart",
           inputs=[port("exec", "exec", required=True)],
           outputs=[*(port(f"then_{i}", "exec", f"Suite n {i}", f"Next n {i}") for i in range(MAX_SEQUENCE)),
                    port("on_error", "exec")],
           params=[port("count", "int", "Nombre de suites (1 a 8)", "Number of outputs (1 to 8)", 2, default=2)],
           shelf=32, aliases=["suite", "ordre", "then"],
           doc_fr="Execute ses sorties dans l'ordre, une apres l'autre (une sortie exec = un seul lien).",
           doc_en="Runs its outputs in order, one after the other (one exec output = one link).")
async def sequence(ctx, inputs, params):
    count = _int(params.get("count", 2), "count")
    if not 1 <= count <= MAX_SEQUENCE:
        raise NodeError(f"count : entre 1 et {MAX_SEQUENCE}", code="E_PARAM_INVALID")
    ctx.log(f"{count} suite(s)")
    return {SEQUENCE_KEY: [f"then_{i}" for i in range(count)]}


@flow_node(FOR_BEGIN, "ForBegin", icon="Repeat",
           inputs=[port("exec", "exec", required=True),
                   port("start", "int", "Premier index", "First index", 1, required=True),
                   port("end", "int", "Dernier index (inclus)", "Last index (included)", 10, required=True),
                   port("step", "int", "Pas (defaut 1, negatif pour descendre)", "Step (default 1, negative goes down)",
                        1, default=1)],
           outputs=[port("loop", "exec", "Corps de la boucle", "Loop body"),
                    port("index", "int", "Index courant", "Current index", 1), port("on_error", "exec")],
           params=[port("max_iterations", "int", "Nombre maximal de tours", "Maximum number of turns",
                        MAX_ITERATIONS, default=MAX_ITERATIONS),
                   port("mode", "str", "Reserve V2", "Reserved for V2", "sequential", default="sequential",
                        choices=LOOP_MODES)],
           shelf=33, aliases=["boucle", "for", "compteur"],
           doc_fr="Execute le corps pour chaque index de start a end inclus.",
           doc_en="Runs the body for each index from start to end included.")
async def for_begin(ctx, inputs, params):
    start, end = _int(inputs.get("start"), "start"), _int(inputs.get("end"), "end")
    step = _int(inputs.get("step") if inputs.get("step") not in (None, "") else 1, "step")
    if step == 0:
        raise NodeError("step ne peut pas valoir 0", code="E_PARAM_INVALID")
    limit = _int(params.get("max_iterations") or MAX_ITERATIONS, "max_iterations")
    turns = max(0, (end - start) // step + 1)
    if turns > limit:
        raise NodeError(f"{turns} tours : maximum {limit} (parametre max_iterations)")
    return {ITEMS_KEY: list(range(start, end + (1 if step > 0 else -1), step))}


@flow_node(WHILE_BEGIN, "WhileBegin", icon="RefreshCw",
           inputs=[port("exec", "exec", required=True),
                   port("condition", "bool", "Tourne tant que c'est vrai (relue apres chaque tour)",
                        "Loops while true (read again after each turn)", True, required=True)],
           outputs=[port("loop", "exec", "Corps de la boucle", "Loop body"),
                    port("index", "int", "Tour courant (0 d'abord)", "Current turn (0 first)", 0),
                    port("on_error", "exec")],
           params=[port("max_iterations", "int", "Plafond de tours (erreur au plafond, jamais infini)",
                        "Turn ceiling (error at the ceiling, never infinite)", MAX_ITERATIONS,
                        default=MAX_ITERATIONS)],
           shelf=34, aliases=["boucle", "while", "tant que"],
           doc_fr="Execute le corps tant que la condition est vraie, au plus max_iterations tours.",
           doc_en="Runs the body while the condition is true, at most max_iterations turns.")
async def while_begin(ctx, inputs, params):
    cond = inputs.get("condition")
    if not isinstance(cond, bool):
        raise NodeError(f"While attend un booleen, recu {cond!r} : utilise Compare")
    limit = _int(params.get("max_iterations") or MAX_ITERATIONS, "max_iterations")
    if limit < 1:
        raise NodeError("max_iterations : au moins 1", code="E_PARAM_INVALID")
    return {CONDITION_KEY: cond, LIMIT_KEY: limit}


def _end_node(type_: str, label: str, begin_label: str, icon: str, shelf: int) -> None:
    @flow_node(type_, label, icon=icon,
               inputs=[port("exec", "exec", required=True)],
               outputs=[port("done", "exec", "Suite, une fois la boucle finie", "Next, once the loop is done"),
                        port("on_error", "exec")],
               params=[port("begin", "str", f"Id du {begin_label} apparie (pose par l'editeur)",
                            f"Id of the paired {begin_label} (set by the editor)", "n3", required=True)],
               shelf=shelf, aliases=["boucle", "fin"],
               doc_fr=f"Ferme la boucle de son {begin_label}.", doc_en=f"Closes the loop of its {begin_label}.")
    async def _end(ctx, inputs, params):
        return {}   # driven by the engine


_end_node(FOR_END, "ForEnd", "ForBegin", "Repeat", 35)
_end_node(WHILE_END, "WhileEnd", "WhileBegin", "RefreshCw", 36)


@flow_node(BREAK_LOOP, "BreakLoop", icon="LogOut", inputs=[port("exec", "exec", required=True)],
           shelf=37, aliases=["sortir", "break", "stop"],
           doc_fr="Sort de la boucle englobante : la suite part de son done.",
           doc_en="Leaves the enclosing loop: the flow goes on from its done.")
async def break_loop(ctx, inputs, params):
    return {}   # driven by the engine


# -- values -----------------------------------------------------------------------

_MATH_OPS = ("add", "sub", "mul", "div", "mod", "min", "max", "round", "floor", "ceil", "abs")
_UNARY = ("round", "floor", "ceil", "abs")


@flow_node("operator.math", "Math", icon="Calculator",
           inputs=[port("a", "float", "Premier nombre", "First number", 3, required=True),
                   port("b", "float", "Second nombre (operations a deux termes)", "Second number (binary ops)", 2)],
           outputs=[port("result", "float", "Resultat", "Result", 5.0),
                    port("as_int", "int", "Resultat tronque en entier", "Result truncated to an integer", 5)],
           params=[port("op", "str", ", ".join(_MATH_OPS), ", ".join(_MATH_OPS), "add", default="add",
                        choices=_MATH_OPS)],
           shelf=60, aliases=["calcul", "addition", "nombre"],
           doc_fr="Calcule a op b (ou op a pour round, floor, ceil, abs).",
           doc_en="Computes a op b (or op a for round, floor, ceil, abs).")
async def math_(ctx, inputs, params):
    op = params.get("op") or "add"
    if op not in _MATH_OPS:
        raise NodeError(f"Operation inconnue '{op}' ({', '.join(_MATH_OPS)})", code="E_PARAM_INVALID")
    a = _float(inputs.get("a"), "a")
    b = 0.0 if op in _UNARY else _float(inputs.get("b") if inputs.get("b") is not None else 0, "b")
    if op in ("div", "mod") and b == 0:
        raise NodeError("Division par zero")
    result = {"add": lambda: a + b, "sub": lambda: a - b, "mul": lambda: a * b, "div": lambda: a / b,
              "mod": lambda: a % b, "min": lambda: min(a, b), "max": lambda: max(a, b),
              "round": lambda: float(round(a)), "floor": lambda: float(_math.floor(a)),
              "ceil": lambda: float(_math.ceil(a)), "abs": lambda: abs(a)}[op]()
    return {"result": result, "as_int": int(result)}


@flow_node("operator.null", "Null", icon="Circle",
           inputs=[port("value", "any", "Valeur a faire passer", "Value to pass through")],
           outputs=[port("value", "any", "La meme valeur", "The same value")],
           shelf=61, aliases=["relais", "passe", "organiser"],
           doc_fr="Laisse passer la valeur : sert a ranger le graph.",
           doc_en="Passes the value through: used to tidy the graph.")
async def null(ctx, inputs, params):
    return {"value": inputs.get("value")}


# -- text -------------------------------------------------------------------------

@flow_node("operator.str_join", "StrJoin", icon="Type",
           inputs=[port("items", "list[str]", "Textes a joindre", "Texts to join", ["a", "b"], required=True)],
           outputs=[port("text", "str", "Texte joint", "Joined text", "a_b")],
           params=[port("sep", "str", "Separateur", "Separator", "_", default="")],
           shelf=62, aliases=["joindre", "concat"],
           doc_fr="Joint les textes avec le separateur.", doc_en="Joins the texts with the separator.")
async def str_join(ctx, inputs, params):
    items = as_list(inputs.get("items"), "items")
    return {"text": str(params.get("sep") or "").join("" if i is None else str(i) for i in items)}


@flow_node("operator.str_split", "StrSplit", icon="Scissors",
           inputs=[port("text", "str", "Texte a couper", "Text to split", "a_b", required=True)],
           outputs=[port("items", "list[str]", "Morceaux", "Pieces", ["a", "b"])],
           params=[port("sep", "str", "Separateur (vide = espaces)", "Separator (empty = spaces)", "_", default="")],
           shelf=63, aliases=["couper", "split"],
           doc_fr="Coupe le texte a chaque separateur.", doc_en="Splits the text at each separator.")
async def str_split(ctx, inputs, params):
    return {"items": str(inputs.get("text")).split(params.get("sep") or None)}


@flow_node("operator.str_replace", "StrReplace", icon="Replace",
           inputs=[port("text", "str", "Texte", "Text", "shot_010_tmp", required=True)],
           outputs=[port("text", "str", "Texte remplace", "Replaced text", "shot_010")],
           params=[port("find", "str", "A chercher", "To find", "_tmp", required=True),
                   port("with", "str", "Remplacer par", "Replace with", "", default=""),
                   port("regex", "bool", "find est une expression reguliere", "find is a regular expression",
                        False, default=False)],
           shelf=64, aliases=["remplacer", "replace"],
           doc_fr="Remplace find par with dans le texte.", doc_en="Replaces find with with in the text.")
async def str_replace(ctx, inputs, params):
    text, find, repl = str(inputs.get("text")), str(params.get("find") or ""), str(params.get("with") or "")
    if not find:
        raise NodeError("StrReplace attend `find`")
    if as_bool(params.get("regex")):
        try:
            return {"text": re.sub(find, repl, text)}
        except re.error as exc:
            raise NodeError(f"Expression reguliere invalide : {exc}", code="E_PARAM_INVALID") from None
    return {"text": text.replace(find, repl)}


_CASE_OPS = ("upper", "lower", "title", "strip")


@flow_node("operator.str_case", "StrCase", icon="CaseSensitive",
           inputs=[port("text", "str", "Texte", "Text", "jerome", required=True)],
           outputs=[port("text", "str", "Texte transforme", "Changed text", "JEROME")],
           params=[port("op", "str", "upper, lower, title ou strip", "upper, lower, title or strip", "upper",
                        default="upper", choices=_CASE_OPS)],
           shelf=65, aliases=["majuscules", "minuscules", "casse"],
           doc_fr="Majuscules, minuscules, titre ou espaces retires.",
           doc_en="Upper case, lower case, title or stripped.")
async def str_case(ctx, inputs, params):
    op = params.get("op") or "upper"
    if op not in _CASE_OPS:
        raise NodeError(f"Operation inconnue '{op}' ({', '.join(_CASE_OPS)})", code="E_PARAM_INVALID")
    return {"text": getattr(str(inputs.get("text")), op)()}


@flow_node("operator.str_format", "StrFormat", icon="ListOrdered",
           inputs=[port("value", "any", "Valeur a formater", "Value to format", 7, required=True)],
           outputs=[port("text", "str", "Texte", "Text", "007")],
           params=[port("spec", "str", "Format Python (03d donne 007, .2f donne 3.14)",
                        "Python format (03d gives 007, .2f gives 3.14)", "03d", default="")],
           shelf=66, aliases=["format", "padding", "zero"],
           doc_fr="Met une valeur en forme : 03d donne 007.", doc_en="Formats a value: 03d gives 007.")
async def str_format(ctx, inputs, params):
    value, spec = inputs.get("value"), str(params.get("spec") or "")
    if spec and isinstance(value, str):
        if spec[-1] in "dxXob":
            value = _int(value, "value")
        elif spec[-1] in "feEgG%":
            value = _float(value, "value")
    try:
        return {"text": format(value, spec)}
    except (ValueError, TypeError) as exc:
        raise NodeError(f"Format `{spec}` impossible pour {value!r} : {exc}", code="E_PARAM_INVALID") from None


# -- lists ------------------------------------------------------------------------

@flow_node("operator.list_length", "ListLength", icon="List",
           inputs=[port("list", "list[any]", "Liste", "List", ["a", "b"], required=True)],
           outputs=[port("length", "int", "Nombre d'elements", "Number of items", 2)],
           shelf=67, aliases=["taille", "nombre", "count"],
           doc_fr="Nombre d'elements de la liste.", doc_en="Number of items of the list.")
async def list_length(ctx, inputs, params):
    return {"length": len(as_list(inputs.get("list"), "list"))}


@flow_node("operator.list_get", "ListGet", icon="List",
           inputs=[port("list", "list[any]", "Liste", "List", ["a", "b"], required=True),
                   port("index", "int", "Rang (0 d'abord, -1 = dernier)", "Rank (0 first, -1 = last)", 0,
                        required=True)],
           outputs=[port("item", "any", "Element", "Item", "a"),
                    port("found", "bool", "Vrai si le rang existe", "True when the rank exists", True)],
           params=[port("default", "any", "Valeur si le rang n'existe pas", "Value when the rank does not exist")],
           shelf=68, aliases=["element", "index"],
           doc_fr="Element au rang donne (negatif = depuis la fin).",
           doc_en="Item at the given rank (negative = from the end).")
async def list_get(ctx, inputs, params):
    items = as_list(inputs.get("list"), "list")
    index = _int(inputs.get("index"), "index")
    if -len(items) <= index < len(items):
        return {"item": items[index], "found": True}
    return {"item": params.get("default"), "found": False}


def _posix(path: Any) -> str:
    return str(path).replace("\\", "/")


def _match_key(item: Any, on: str) -> str:
    if isinstance(item, dict):   # publish record
        item = item.get("path") or item.get("name") or ""
    text = _posix(item)
    return text if on == "path" else text.rsplit("/", 1)[-1]


@flow_node("operator.list_filter", "ListFilter", icon="ListFilter",
           inputs=[port("list", "list[any]", "Liste", "List", ["a.abc", "b_tmp.abc"], required=True)],
           outputs=[port("items", "list[any]", "Elements retenus", "Kept items", ["a.abc"]),
                    port("rejected", "list[any]", "Elements ecartes", "Rejected items", ["b_tmp.abc"])],
           params=[port("pattern", "pattern", "Motif facon Houdini (* = tout, ^ exclut)", "Houdini style pattern "
                        "(* = all, ^ excludes)", "*.abc ^*_tmp*", required=True, default="*"),
                   port("match_on", "str", "name (nom) ou path (chemin entier)", "name or path (whole path)",
                        "name", default="name", choices=MATCH_ON)],
           shelf=69, aliases=["filtrer", "filter", "motif"],
           doc_fr="Garde les elements qui correspondent au motif (`*.abc ^*_tmp*`).",
           doc_en="Keeps the items matching the pattern (`*.abc ^*_tmp*`).")
async def list_filter(ctx, inputs, params):
    from flux_flows.patterns import PatternError, mask

    items = as_list(inputs.get("list"), "list")
    on = params.get("match_on") or "name"
    if on not in MATCH_ON:
        raise NodeError("match_on : name ou path", code="E_PARAM_INVALID")
    try:
        keep = mask(str(params.get("pattern") or ""), [_match_key(i, on) for i in items])
    except PatternError as exc:
        raise NodeError(exc.message, code=exc.code) from None
    return {"items": [i for i, k in zip(items, keep) if k], "rejected": [i for i, k in zip(items, keep) if not k]}


def _natural(text: str) -> List[Any]:
    return [(0, int(part), "") if part.isdigit() else (1, 0, part.lower()) for part in re.split(r"(\d+)", text)]


def _stat(item: Any, field: str) -> float:
    try:
        st = Path(_match_key(item, "path")).stat()
    except OSError:
        return 0.0
    return st.st_mtime if field == "date" else float(st.st_size)


@flow_node("operator.list_sort", "ListSort", icon="ArrowDownUp",
           inputs=[port("list", "list[any]", "Liste", "List", ["b", "a"], required=True)],
           outputs=[port("items", "list[any]", "Liste triee", "Sorted list", ["a", "b"])],
           params=[port("key", "str", "name, date, size ou natural (v2 avant v10)",
                        "name, date, size or natural (v2 before v10)", "natural", default="natural", choices=SORT_KEYS),
                   port("reverse", "bool", "Ordre inverse", "Reverse order", False, default=False)],
           shelf=70, aliases=["trier", "sort", "ordre"],
           doc_fr="Trie par nom, date, taille (fichiers) ou ordre naturel.",
           doc_en="Sorts by name, date, size (files) or natural order.")
def list_sort(ctx, inputs, params):
    items = as_list(inputs.get("list"), "list")
    key = params.get("key") or "natural"
    keys = {"name": lambda i: _match_key(i, "path").lower(), "natural": lambda i: _natural(_match_key(i, "path")),
            "date": lambda i: _stat(i, "date"), "size": lambda i: _stat(i, "size")}
    if key not in keys:
        raise NodeError("key : name, date, size ou natural", code="E_PARAM_INVALID")
    return {"items": sorted(items, key=keys[key], reverse=as_bool(params.get("reverse")))}


@flow_node("operator.list_unique", "ListUnique", icon="ListChecks",
           inputs=[port("list", "list[any]", "Liste", "List", ["a", "a", "b"], required=True)],
           outputs=[port("items", "list[any]", "Sans doublons (ordre garde)", "Without duplicates (order kept)",
                         ["a", "b"])],
           shelf=71, aliases=["doublons", "unique"],
           doc_fr="Retire les doublons en gardant l'ordre.", doc_en="Removes duplicates, keeping the order.")
async def list_unique(ctx, inputs, params):
    out: List[Any] = []
    for item in as_list(inputs.get("list"), "list"):
        if item not in out:
            out.append(item)
    return {"items": out}


@flow_node("operator.list_append", "ListAppend", icon="ListPlus",
           inputs=[port("list", "list[any]", "Liste", "List", ["a"], required=True),
                   port("item", "any", "Element a ajouter", "Item to add", "b", required=True)],
           outputs=[port("items", "list[any]", "Nouvelle liste", "New list", ["a", "b"])],
           shelf=72, aliases=["ajouter", "append"],
           doc_fr="Renvoie une nouvelle liste avec l'element a la fin.",
           doc_en="Returns a new list with the item at the end.")
async def list_append(ctx, inputs, params):
    return {"items": [*as_list(inputs.get("list"), "list"), inputs.get("item")]}


# -- paths ------------------------------------------------------------------------

@flow_node("operator.path_join", "PathJoin", icon="Route",
           inputs=[port("base", "path", "Dossier de depart", "Base folder", "$FLUX/DAILY", required=True),
                   port("a", "str", "Morceau 1", "Part 1", "2026-10-23", required=True),
                   port("b", "str", "Morceau 2", "Part 2"), port("c", "str", "Morceau 3", "Part 3")],
           outputs=[port("path", "path", "Chemin joint", "Joined path", "D:/FLUX/DAILY/2026-10-23")],
           shelf=73, aliases=["joindre", "chemin", "join"],
           doc_fr="Joint un dossier et des morceaux de chemin relatifs.", doc_en="Joins a folder and relative parts.")
async def path_join(ctx, inputs, params):
    path = as_path(ctx, inputs.get("base"), "base")
    for name in ("a", "b", "c"):
        part = inputs.get(name)
        if part in (None, ""):
            continue
        pure = PurePath(str(part))
        if pure.is_absolute() or pure.drive or ".." in pure.parts:
            raise NodeError(f"`{name}` doit etre un morceau relatif, sans `..` : {part!r}")
        path = path / str(part)
    return {"path": _posix(path)}


@flow_node("operator.path_split", "PathSplit", icon="FolderTree",
           inputs=[port("path", "path", "Chemin", "Path", "D:/x/shot_010_v002.abc", required=True)],
           outputs=[port("parent", "dir", "Dossier parent", "Parent folder", "D:/x"),
                    port("name", "str", "Nom avec extension", "Name with extension", "shot_010_v002.abc"),
                    port("stem", "str", "Nom sans extension", "Name without extension", "shot_010_v002"),
                    port("ext", "str", "Extension (avec le point)", "Extension (with the dot)", ".abc")],
           shelf=74, aliases=["decouper", "nom", "extension"],
           doc_fr="Dossier parent, nom, nom sans extension et extension.",
           doc_en="Parent folder, name, name without extension and extension.")
async def path_split(ctx, inputs, params):
    p = PurePath(_posix(inputs.get("path")))
    return {"parent": _posix(p.parent), "name": p.name, "stem": p.stem, "ext": p.suffix}


@flow_node("operator.path_relative", "PathRelative", icon="FolderTree",
           inputs=[port("path", "path", "Chemin", "Path", "D:/proj/a/b.abc", required=True),
                   port("base", "dir", "Dossier de reference", "Reference folder", "D:/proj", required=True)],
           outputs=[port("relative", "str", "Chemin relatif (en /)", "Relative path (with /)", "a/b.abc")],
           shelf=75, aliases=["relatif", "relative"],
           doc_fr="Chemin relatif a un dossier.", doc_en="Path relative to a folder.")
async def path_relative(ctx, inputs, params):
    path, base = as_path(ctx, inputs.get("path"), "path"), as_path(ctx, inputs.get("base"), "base")
    try:
        return {"relative": _posix(os.path.relpath(path, base))}
    except ValueError:   # another drive on Windows
        raise NodeError(f"`{path}` et `{base}` ne sont pas sur le meme disque") from None


@flow_node("operator.path_flux_token", "PathFluxToken", icon="Link",
           inputs=[port("value", "str", "Chemin absolu ou $FLUX/...", "Absolute path or $FLUX/...",
                        "$FLUX/DAILY", required=True)],
           outputs=[port("token", "str", "Forme portable $FLUX/... si sous la racine", "Portable $FLUX/... form",
                         "$FLUX/DAILY"),
                    port("path", "path", "Chemin absolu sur ce poste", "Absolute path on this machine",
                         "D:/FLUX/DAILY")],
           shelf=76, aliases=["flux", "portable", "token"],
           doc_fr="Passe d'un chemin absolu a la forme portable $FLUX/... et inversement.",
           doc_en="Converts between an absolute path and the portable $FLUX/... form.")
async def path_flux_token(ctx, inputs, params):
    from core.paths import from_flux_token, to_flux_token

    try:
        absolute = from_flux_token(str(inputs.get("value")))
        return {"token": _posix(to_flux_token(absolute)), "path": _posix(absolute)}
    except Exception as exc:
        raise NodeError(f"`$FLUX` ne peut pas etre resolu sur ce poste : {exc}") from None


# -- dates ------------------------------------------------------------------------

def _parse_iso(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        raise NodeError(f"Date ISO attendue (2026-10-23 ou 2026-10-23T22:00:00), recu {value!r}") from None


@flow_node("operator.date_now", "DateNow", icon="Calendar",
           outputs=[port("iso", "str", "Date et heure ISO", "ISO date and time", "2026-10-23T22:00:00"),
                    port("date", "str", "Date AAAA-MM-JJ", "Date YYYY-MM-DD", "2026-10-23"),
                    port("epoch", "float", "Secondes depuis 1970", "Seconds since 1970", 1792792800.0)],
           shelf=77, aliases=["maintenant", "date", "jour"],
           doc_fr="Date et heure au moment ou le node est lu.", doc_en="Date and time when the node is read.")
async def date_now(ctx, inputs, params):
    now = datetime.now().replace(microsecond=0)
    return {"iso": now.isoformat(), "date": now.strftime("%Y-%m-%d"), "epoch": now.timestamp()}


@flow_node("operator.date_format", "DateFormat", icon="CalendarDays",
           inputs=[port("iso", "str", "Date ISO", "ISO date", "2026-10-23T22:00:00", required=True)],
           outputs=[port("text", "str", "Date formatee", "Formatted date", "20261023")],
           params=[port("fmt", "str", "Format strftime (%Y%m%d)", "strftime format (%Y%m%d)", "%Y%m%d",
                        default="%Y-%m-%d")],
           shelf=78, aliases=["format", "date"],
           doc_fr="Met une date en forme (strftime).", doc_en="Formats a date (strftime).")
async def date_format(ctx, inputs, params):
    try:
        return {"text": _parse_iso(inputs.get("iso")).strftime(str(params.get("fmt") or "%Y-%m-%d"))}
    except ValueError as exc:
        raise NodeError(f"Format invalide : {exc}", code="E_PARAM_INVALID") from None


@flow_node("operator.date_add", "DateAdd", icon="CalendarClock",
           inputs=[port("iso", "str", "Date ISO", "ISO date", "2026-10-23", required=True)],
           outputs=[port("iso", "str", "Nouvelle date ISO", "New ISO date", "2026-10-22T00:00:00")],
           params=[port("days", "float", "Jours (negatif = avant)", "Days (negative = before)", -1, default=0),
                   port("hours", "float", "Heures", "Hours", 0, default=0)],
           shelf=79, aliases=["hier", "demain", "ajouter"],
           doc_fr="Ajoute des jours et des heures a une date.", doc_en="Adds days and hours to a date.")
async def date_add(ctx, inputs, params):
    when = _parse_iso(inputs.get("iso"))
    delta = timedelta(days=_float(params.get("days") or 0, "days"), hours=_float(params.get("hours") or 0, "hours"))
    return {"iso": (when + delta).isoformat()}
