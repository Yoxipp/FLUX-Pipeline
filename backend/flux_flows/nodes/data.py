# data.py — nodes that give a value (02_NODES §3). P2: value, get / set variable,
# flow_input; P3: path, python_value, json_value, template, context.
#
# Pure except set_variable. Variables are local to a run (01 §4): the engine
# owns them, casts a written value to the declared type and counts the writes.
# python_value reads a module variable with ast (literal_eval): the file is never
# executed. template keeps its ``text`` raw (registry ``raw``) and resolves it
# itself with its ``values`` as extra {keys}.

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Tuple

from flux_flows.nodes.common import as_path
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
    value = ctx.interface[ident]
    if ctx.interface_types.get(ident) in ("path", "dir") and isinstance(value, str):
        value = ctx.resolve(value, path_field=True)   # a "$FLUX/DAILY" default is a typed literal
    return {"value": value}


# -- P3 -----------------------------------------------------------------------------

def _posix(path: Any) -> str:
    return str(path).replace("\\", "/")


def _outside_pipe(path: Path) -> bool:
    try:
        from core.paths import get_flux_root

        root = get_flux_root()
        if root is None:
            return False
        path.resolve().relative_to(Path(root).resolve())
        return False
    except ValueError:
        return True
    except OSError:
        return False


@flow_node("data.path", "Path", icon="Route",
           outputs=[port("path", "path", "Chemin resolu", "Resolved path", "D:/FLUX/DAILY/IN"),
                    port("dir", "dir", "Le meme chemin si c'est un dossier existant, sinon vide",
                         "The same path when it is an existing folder, else empty", "D:/FLUX/DAILY/IN")],
           params=[port("value", "path", "Chemin ($FLUX/..., {project_path}/..., relatif au projet)",
                        "Path ($FLUX/..., {project_path}/..., relative to the project)", "$FLUX/DAILY/IN",
                        required=True),
                   port("relative_to", "str", "project (un chemin relatif part du projet) ou absolute",
                        "project (a relative path starts at the project) or absolute", "project",
                        default="project")],
           shelf=14, aliases=["chemin", "dossier", "fichier"],
           doc_fr="Un chemin fixe ; accepte $FLUX, {token} et ${variable}.",
           doc_en="A fixed path; accepts $FLUX, {token} and ${variable}.")
def path_(ctx, inputs, params):
    text = params.get("value")
    if params.get("relative_to", "project") == "absolute" and not Path(str(text or "")).is_absolute():
        raise NodeError(f"Chemin absolu attendu, recu {text!r}")
    path = as_path(ctx, text)
    if _outside_pipe(path):
        ctx.log(f"W_ABSOLUTE_PATH : {path} est hors du pipe FLUX", "warn")
    return {"path": _posix(path), "dir": _posix(path) if path.is_dir() else ""}


def _module_value(source: str, name: str) -> Tuple[bool, Any]:
    """Value of the last top level ``name = <literal>`` of *source*, never executed."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise NodeError(f"Fichier Python illisible : {exc.msg} (ligne {exc.lineno})") from None
    found, value = False, None
    for stmt in tree.body:
        targets = []
        if isinstance(stmt, ast.Assign):
            targets, node = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, node = [stmt.target], stmt.value
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            try:
                value, found = ast.literal_eval(node), True
            except ValueError:
                raise NodeError(f"`{name}` n'est pas une valeur simple (texte, nombre, liste, dict) : "
                                "le fichier n'est jamais execute") from None
    return found, value


@flow_node("data.python_value", "PythonValue", icon="FileCode",
           outputs=[port("value", "any", "Valeur de la variable", "Variable value", ["maya", "houdini"])],
           params=[port("file", "path", "Fichier .py", ".py file", "$FLUX/CONFIG/extensions/values.py", required=True),
                   port("name", "str", "Variable du module", "Module variable", "SOFTS", required=True)],
           shelf=15, aliases=["python", "variable", "config"],
           doc_fr="Lit une variable d'un fichier Python sans l'executer (valeurs simples seulement).",
           doc_en="Reads a variable of a Python file without running it (plain values only).")
def python_value(ctx, inputs, params):
    path, name = as_path(ctx, params.get("file"), "file"), str(params.get("name") or "")
    if not name.isidentifier():
        raise NodeError(f"Nom de variable invalide {name!r}", code="E_PARAM_INVALID")
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NodeError(f"Fichier illisible {path} : {exc}") from None
    found, value = _module_value(source, name)
    if not found:
        raise NodeError(f"`{name}` n'est pas defini dans {path.name}")
    return {"value": value}


_KEY_PART = re.compile(r"([^.\[\]]+)|\[(-?\d+)\]")


def _walk(data: Any, key: str) -> Tuple[bool, Any]:
    pos = 0
    for m in _KEY_PART.finditer(key):
        if m.start() != pos and key[pos:m.start()] != ".":
            raise NodeError(f"Cle invalide `{key}` (ex. a.b[0].c)", code="E_PARAM_INVALID")
        pos = m.end()
        if m.group(1) is not None:
            if not isinstance(data, dict) or m.group(1) not in data:
                return False, None
            data = data[m.group(1)]
        else:
            idx = int(m.group(2))
            if not isinstance(data, list) or not -len(data) <= idx < len(data):
                return False, None
            data = data[idx]
    if pos != len(key):
        raise NodeError(f"Cle invalide `{key}` (ex. a.b[0].c)", code="E_PARAM_INVALID")
    return True, data


@flow_node("data.json_value", "JsonValue", icon="Braces",
           inputs=[port("json", "dict", "Donnees (sinon le fichier)", "Data (else the file)")],
           outputs=[port("value", "any", "Valeur trouvee", "Value found", "v002"),
                    port("found", "bool", "Vrai si la cle existe", "True when the key exists", True)],
           params=[port("file", "path", "Fichier .json (si json n'est pas relie)", ".json file (when json is not linked)",
                        "$FLUX/CONFIG/settings.json"),
                   port("key", "str", "Chemin pointe a.b[0].c", "Dotted path a.b[0].c", "shots[0].name", required=True),
                   port("default", "any", "Valeur si la cle manque", "Value when the key is missing")],
           shelf=16, aliases=["json", "cle", "lire"],
           doc_fr="Lit une valeur dans un JSON par son chemin a.b[0].c.",
           doc_en="Reads a value of a JSON by its path a.b[0].c.")
def json_value(ctx, inputs, params):
    data = inputs.get("json")
    if data is None:
        if not params.get("file"):
            raise NodeError("JsonValue attend `json` relie ou `file`")
        path = as_path(ctx, params.get("file"), "file")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise NodeError(f"JSON illisible {path} : {exc}") from None
    found, value = _walk(data, str(params.get("key") or ""))
    return {"value": value if found else params.get("default"), "found": found}


@flow_node("data.template", "Template", icon="Type",
           inputs=[port("values", "dict", "Cles en plus pour {cle}", "Extra keys for {key}", {"soft": "maya"})],
           outputs=[port("text", "str", "Texte resolu", "Resolved text", "DAILY_20261023_maya")],
           params=[port("text", "str", "Texte avec {token}, {date:%Y%m%d}, ${variable}, $FLUX",
                        "Text with {token}, {date:%Y%m%d}, ${variable}, $FLUX", "DAILY_{date:%Y%m%d}_{soft}",
                        required=True)],
           raw=("text",), shelf=17, aliases=["texte", "format", "modele"],
           doc_fr="Compose un texte avec les tokens du run et les cles de values.",
           doc_en="Builds a text from the run tokens and the keys of values.")
async def template(ctx, inputs, params):
    values = inputs.get("values") or {}
    if not isinstance(values, dict):
        raise NodeError("values : dictionnaire attendu")
    extra = {str(k): ("" if v is None else str(v)) for k, v in values.items()}
    return {"text": ctx.resolve(str(params.get("text") or ""), path_field=True, extra=extra)}


_CONTEXT_OUTPUTS = ("project", "project_path", "asset", "seq", "shot", "user", "date", "time", "flow")


@flow_node("data.context", "Context", icon="Info",
           outputs=[port("project", "str", "Projet du run", "Run project", "DEMO"),
                    port("project_path", "dir", "Dossier du projet", "Project folder", "D:/FLUX/DOSSIER_PROJETS/DEMO"),
                    port("asset", "str", "Asset (si l'evenement le donne)", "Asset (when the event gives it)"),
                    port("seq", "str", "Sequence (si l'evenement la donne)", "Sequence (when the event gives it)"),
                    port("shot", "str", "Shot (si l'evenement le donne)", "Shot (when the event gives it)"),
                    port("user", "str", "Artiste (MAJUSCULES)", "Artist (UPPER CASE)", "ADAM"),
                    port("date", "str", "Date du run AAAA-MM-JJ", "Run date YYYY-MM-DD", "2026-10-23"),
                    port("time", "str", "Heure du run HH-MM-SS", "Run time HH-MM-SS", "22-00-00"),
                    port("flow", "str", "Nom du flow", "Flow name", "daily_render")],
           shelf=18, aliases=["contexte", "projet", "utilisateur"],
           doc_fr="Les valeurs du run : projet, artiste, date, shot...", doc_en="The run values: project, artist, date, shot...")
async def context(ctx, inputs, params):
    c = ctx.context or {}
    return {k: ("" if c.get(k) is None else c.get(k)) for k in _CONTEXT_OUTPUTS}
