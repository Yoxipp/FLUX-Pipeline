# catalog.py - node catalogue and team-shared action edits (B6, ADR 0039 / 0040).
#
#   list_commands()        every registered command (built-in + the team's own nodes)
#   list_functions()       every public function of backend/features, core, dcc, read
#                          with ast (nothing imported): a "call_function" node each
#   load_user_nodes()      imports <FLUX_ROOT>/CONFIG/nodes/*.py (the team's nodes)
#   save_user_node()       writes one of those files, then loads it
#   resolve_action_file()  CONFIG/actions/<name>.yml when the team edited the action
#   save_action()          validates then writes CONFIG/actions/<name>.yml (+ backup, history)
#   reset_action()         removes the team copy: back to the shipped YAML
#
# Everything the team edits lives under FLUX_ROOT/CONFIG, shared by every workstation;
# the YAML shipped with FLUX (flux_actions/config) is never written.

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flux_core.registry import all_commands

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCAN_PACKAGES = ("features", "core", "dcc")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

NODE_TEMPLATE = '''# {name}.py - FLUX node written by the team (CONFIG/nodes).
#
# A node = a class with typed parameters (its inputs) and a run() that returns a dict
# (its outputs, usable by later nodes as {{from: "step.node.key"}}).

from flux_core import CommandBase, register


@register("{name}")
class Node(CommandBase):
    """What this node does, in one sentence (shown in the graph)."""

    parameters = {{
        "text": {{"type": "str", "label": "Texte"}},
    }}

    async def run(self, parameters, action_query, logger):
        text = parameters.get("text") or ""
        logger.info("{name}: %s", text)
        return {{"result": text}}
'''


# ── paths ─────────────────────────────────────────────────────────────────────

def _config_dir() -> Optional[Path]:
    try:
        from core.paths import get_config_dir

        return get_config_dir()
    except Exception:  # noqa: BLE001 - no FLUX_ROOT yet (first launch)
        return None


def actions_dir() -> Optional[Path]:
    base = _config_dir()
    return base / "actions" if base else None


def nodes_dir() -> Optional[Path]:
    base = _config_dir()
    return base / "nodes" if base else None


# ── team nodes ────────────────────────────────────────────────────────────────

_loaded: Dict[Path, float] = {}
_node_errors: Dict[str, str] = {}


def load_user_nodes() -> Dict[str, str]:
    """Import every CONFIG/nodes/*.py not loaded yet (or changed). Returns {file: error}."""
    folder = nodes_dir()
    if not folder or not folder.is_dir():
        return {}
    for path in sorted(folder.glob("*.py")):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if _loaded.get(path) == mtime:
            continue
        mod_name = f"flux_user_nodes.{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            _node_errors.pop(path.name, None)
        except Exception as exc:  # noqa: BLE001 - a broken team node never breaks FLUX
            _node_errors[path.name] = f"{type(exc).__name__}: {exc}"
        _loaded[path] = mtime
    return dict(_node_errors)


def save_user_node(name: str, code: str) -> Dict[str, Any]:
    """Write CONFIG/nodes/<name>.py (compiled first) and load it."""
    if not NAME_RE.match(name):
        raise ValueError("nom de node : minuscules, chiffres et _ (2 a 41 caracteres)")
    compile(code, f"{name}.py", "exec")   # SyntaxError -> caller
    folder = nodes_dir()
    if folder is None:
        raise ValueError("dossier FLUX (CONFIG) introuvable")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.py"
    if path.exists():
        _backup(path)
    path.write_text(code, encoding="utf-8")
    _history({"kind": "node", "name": name})
    errors = load_user_nodes()
    return {"path": str(path), "error": errors.get(path.name, "")}


def node_template(name: str) -> str:
    return NODE_TEMPLATE.format(name=name or "mon_node")


# ── catalogue ─────────────────────────────────────────────────────────────────

def _returned_keys(tree: ast.AST) -> List[str]:
    keys: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for k in node.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value not in keys:
                    keys.append(k.value)
    return keys


def list_commands() -> List[Dict[str, Any]]:
    """Every registered command: key, doc, parameters (defaults), outputs, origin."""
    import inspect
    import textwrap

    from flux_actions import commands as _commands  # noqa: F401 - fills the registry

    load_user_nodes()
    out = []
    for key, cls in sorted(all_commands()):
        try:
            outputs = _returned_keys(ast.parse(textwrap.dedent(inspect.getsource(cls))))
        except (OSError, TypeError, SyntaxError):
            outputs = []
        doc = (inspect.getdoc(cls) or "").split("\n\n", 1)[0].strip()
        params = [{"name": n, "type": s.get("type", "str"), "value": s.get("value"),
                   "label": s.get("label") or n, "hide": bool(s.get("hide")), "tooltip": s.get("tooltip") or ""}
                  for n, s in cls.merged_parameters().items()]
        origin = "equipe" if cls.__module__.startswith("flux_user_nodes.") else "flux"
        out.append({"key": key, "doc": doc, "params": params, "outputs": outputs, "origin": origin,
                    "module": cls.__module__})
    return out


def _type_of(annotation: Optional[ast.expr]) -> str:
    text = ast.unparse(annotation) if annotation is not None else ""
    for pattern, kind in ((r"\bbool\b", "bool"), (r"\bint\b", "int"), (r"\bfloat\b", "float"),
                          (r"\bPath\b", "path"), (r"\b(list|List|tuple|Tuple|Iterable)\b", "list"),
                          (r"\b(dict|Dict|Mapping)\b", "dict"), (r"\bstr\b", "str")):
        if re.search(pattern, text):
            return kind
    return "any"


def _literal(node: Optional[ast.expr]) -> Any:
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None
    return value if isinstance(value, (str, int, float, bool, list, dict)) else None


_functions_cache: Optional[tuple[float, List[Dict[str, Any]]]] = None


def list_functions() -> List[Dict[str, Any]]:
    """Public top-level functions of the backend packages (ast only, cached 60 s)."""
    global _functions_cache
    if _functions_cache and time.monotonic() - _functions_cache[0] < 60:
        return _functions_cache[1]
    out: List[Dict[str, Any]] = []
    for package in SCAN_PACKAGES:
        root = BACKEND_DIR / package
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(BACKEND_DIR).with_suffix("")
            if any(p.startswith(("_", "test")) or p == "__pycache__" for p in rel.parts[1:]):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            module = ".".join(rel.parts)
            for fn in tree.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name.startswith("_"):
                    continue
                if any(isinstance(d, ast.Name) and d.id in ("router",) for d in fn.decorator_list) or \
                        any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                            and isinstance(d.func.value, ast.Name) and d.func.value.id == "router"
                            for d in fn.decorator_list):
                    continue   # HTTP routes are not pipeline functions
                a = fn.args
                positional = a.posonlyargs + a.args
                defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
                args = [{"name": x.arg, "type": _type_of(x.annotation), "value": _literal(d),
                         "required": d is None}
                        for x, d in zip(positional, defaults) if x.arg not in ("self", "cls")]
                args += [{"name": x.arg, "type": _type_of(x.annotation), "value": _literal(d),
                          "required": d is None} for x, d in zip(a.kwonlyargs, a.kw_defaults)]
                doc = (ast.get_docstring(fn) or "").split("\n\n", 1)[0].strip()
                out.append({"id": f"{module}:{fn.name}", "module": module, "name": fn.name,
                            "args": args, "doc": doc, "outputs": _returned_keys(fn) or ["result"]})
    _functions_cache = (time.monotonic(), out)
    return out


# ── team copies of the actions ─────────────────────────────────────────────────

def resolve_action_file(default: Path) -> Path:
    """CONFIG/actions/<stem>.yml when the team edited this action, else the shipped file."""
    load_user_nodes()
    folder = actions_dir()
    if folder is not None:
        team = folder / f"{Path(default).stem}.yml"
        if team.is_file():
            return team
    return Path(default)


def team_actions() -> Dict[str, Path]:
    folder = actions_dir()
    if folder is None or not folder.is_dir():
        return {}
    return {p.stem: p for p in sorted(folder.glob("*.yml"))}


def _backup(path: Path) -> None:
    dest = path.parent / "_backup"
    dest.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (dest / f"{path.name}.bak-{stamp}").write_bytes(path.read_bytes())


def _history(entry: Dict[str, Any]) -> None:
    folder = actions_dir()
    if folder is None:
        return
    try:
        from core import config

        user = config.get_current_user() or "unknown"
    except Exception:  # noqa: BLE001
        user = "unknown"
    folder.mkdir(parents=True, exist_ok=True)
    line = {"at": datetime.now().isoformat(timespec="seconds"), "user": user, **entry}
    with open(folder / "history.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def _comment(lines: str, indent: int) -> List[str]:
    pad = " " * indent
    return [f"{pad}# {ln}".rstrip() for ln in (lines or "").splitlines()]


def render_action_yaml(doc: Dict[str, Any]) -> str:
    """Our own emitter for the action schema: readable, keeps notes as comments."""
    out = _comment(doc.get("description", ""), 0)
    if out:
        out.append("")
    out += [f"name: {doc['name']}", "", "steps:"]
    for step in sorted(doc.get("steps", []), key=lambda s: s.get("index", 0)):
        out += ["", f"  {step['name']}:"] + _comment(step.get("note", ""), 4)
        out += [f"    index: {int(step.get('index', 0))}", "    commands:"]
        for cmd in step.get("commands", []):
            out += [f"      {cmd['name']}:", f"        command: {cmd['command']}"]
            out += _comment(cmd.get("note", ""), 8)
            params = {k: v for k, v in (cmd.get("parameters") or {}).items() if v is not None}
            if params:
                out.append("        parameters:")
                for pname, value in params.items():
                    out.append(f"          {pname}:")
                    if cmd["command"] == "call_function" and pname != "function":
                        # A function argument is passed as is (the function coerces it).
                        out.append("            type: any")
                    out.append(f"            value: {json.dumps(value, ensure_ascii=False)}")
    return "\n".join(out) + "\n"


def validate_action(doc: Dict[str, Any]) -> None:
    """Schema, known commands, links only toward an earlier step (ValueError otherwise)."""
    import yaml

    from flux_core.loader import _validate, build_action_buffer

    if not NAME_RE.match(str(doc.get("name", ""))):
        raise ValueError("nom d'action : minuscules, chiffres et _")
    index_of = {s["name"]: int(s.get("index", 0)) for s in doc.get("steps", [])}
    commands_of = {s["name"]: {c["name"] for c in s.get("commands", [])} for s in doc.get("steps", [])}
    for step in doc.get("steps", []):
        for cmd in step.get("commands", []):
            for pname, value in (cmd.get("parameters") or {}).items():
                if isinstance(value, dict) and set(value) == {"from"}:
                    parts = str(value["from"]).split(".")
                    if len(parts) != 3 or parts[1] not in commands_of.get(parts[0], set()):
                        raise ValueError(f"{step['name']}.{cmd['name']}.{pname} : lien vers {value['from']} introuvable")
                    if index_of[parts[0]] >= int(step.get("index", 0)):
                        raise ValueError(f"{step['name']}.{cmd['name']}.{pname} : un lien vient d'une etape precedente")
    raw = yaml.safe_load(render_action_yaml(doc))
    build_action_buffer(_validate(raw))


def save_action(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Validate, back up the previous team copy, write CONFIG/actions/<name>.yml."""
    from flux_actions import commands as _commands  # noqa: F401

    load_user_nodes()
    validate_action(doc)
    folder = actions_dir()
    if folder is None:
        raise ValueError("dossier FLUX (CONFIG) introuvable")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc['name']}.yml"
    if path.exists():
        _backup(path)
    path.write_text(render_action_yaml(doc), encoding="utf-8")
    _history({"kind": "save", "action": doc["name"],
              "commands": sum(len(s.get("commands", [])) for s in doc.get("steps", []))})
    return {"path": str(path)}


def reset_action(name: str) -> bool:
    """Remove the team copy (backed up first): the shipped YAML is used again."""
    folder = actions_dir()
    path = folder / f"{name}.yml" if folder else None
    if not path or not path.is_file() or not NAME_RE.match(name):
        return False
    _backup(path)
    path.unlink()
    _history({"kind": "reset", "action": name})
    return True
