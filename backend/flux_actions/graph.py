# graph.py — read-only node-flow view of a YAML action (V5 Phase 2).
#
# Turns one action's step/command tree into a {nodes, edges} graph the front
# renders with React Flow, exactly like Silex shows an action as nodes. READ ONLY:
# it never runs, never writes, never mutates the YAML. The YAML stays the single
# source of truth; this is a view built from the same ActionBuffer the engine uses,
# so there is no second parser to drift.
#
#   node  = one command (id "step.command"), with its visible parameters
#   edge  = an ORDER link (step index -> next step) or a DATA-FLOW link
#           (a parameter wired from another command's output: value {from: ...})
#
# Positions are left at (0, 0): the front runs an auto-layout (dagre) over the
# graph, so the backend stays layout-agnostic.
#
# A4 (2026-09-27): every YAML of flux_actions/config is listed (not only the 5 the
# runner imports), the graph carries the action's description (its header comment),
# its steps, each command's doc (class docstring) and each parameter's tooltip. One
# order edge per pair of consecutive steps (every command to every command was a mesh).

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Dict, List

from flux_core import ActionQuery, OutputRef
from flux_core.registry import get_command

# Importing the commands package populates the registry before a YAML loads, same
# as the runner. Kept as a side-effect import; the names are not used here.
from flux_actions import commands as _commands  # noqa: F401
from flux_actions.runner import (
    CONFORM_TEXTURE_ACTION,
    GENERATE_PROXY_ACTION,
    PUBLISH_ACTION,
    PUBLISH_HOUDINI_ACTION,
    PUBLISH_MAYA_ACTION,
)

# The actions a graph can be requested for. One place maps a name to its YAML, so
# the endpoint never builds a path from user input (no traversal off this map).
ACTION_FILES: Dict[str, Path] = {
    "publish": PUBLISH_ACTION,
    "publish_maya": PUBLISH_MAYA_ACTION,
    "publish_houdini": PUBLISH_HOUDINI_ACTION,
    "conform_texture": CONFORM_TEXTURE_ACTION,
    "generate_proxy": GENERATE_PROXY_ACTION,
}
CONFIG_DIR = PUBLISH_ACTION.parent


def _action_files() -> Dict[str, Path]:
    """The known actions plus every other YAML of the config folder (by file stem)."""
    files = dict(ACTION_FILES)
    if CONFIG_DIR.is_dir():
        for f in sorted(CONFIG_DIR.glob("*.y*ml")):
            files.setdefault(f.stem, f)
    return files


def list_action_names() -> List[str]:
    """Return the action names a graph can be built for, sorted."""
    return sorted(_action_files())


def _header_comment(path: Path) -> str:
    """The comment block at the top of a YAML (its description), without the ``#``."""
    lines: List[str] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.startswith("#"):
                if lines:
                    break
                continue
            lines.append(raw[1:].strip())
    except OSError:
        return ""
    return "\n".join(lines).strip()


def _command_doc(key: str) -> Dict[str, str]:
    """{"doc", "module"} of a registered command (docstring, first paragraph)."""
    try:
        cls = get_command(key)
    except Exception:  # noqa: BLE001 - an unknown key shows without doc
        return {"doc": "", "module": ""}
    doc = inspect.getdoc(cls) or ""
    return {"doc": doc.split("\n\n", 1)[0].strip(), "module": getattr(cls, "__module__", "")}


# ── B4 (2026-09-28): inputs, outputs, notes, hidden hooks ────────────────────
# All read from the code / YAML text, never from a run: still read only (ADR 0008).

# What a command writes besides its output keys, and what runs behind it without a
# YAML step (the publish hooks). Kept here, next to the view, because the engine has
# no declaration for side effects. Update when publish_core / usd_publish_hooks change.
COMMAND_EFFECTS: Dict[str, List[Dict[str, str]]] = {
    "copy_publish": [
        {"kind": "output", "label": "Fichier vNNN", "detail": "version immuable, publish_layout.publish_into_layout (ADR 0017)"},
        {"kind": "output", "label": "LAST", "detail": "copie, .link ou pointeur USD derive de vNNN (ADR 0017)"},
        {"kind": "output", "label": "modif_logs.json", "detail": "modif_log.append_log (note de publish, historique)"},
        {"kind": "output", "label": "Activite", "detail": "activity_writer.log_publish (fil Activity)"},
        {"kind": "hook", "label": "Proxy USD", "detail": "usd_publish_hooks : action generate_proxy si USD avec meshes, interrupteur proxy_usd"},
        {"kind": "hook", "label": "Controle USD (R3)", "detail": "validate.publish_check, avertissements dans modif_logs"},
        {"kind": "hook", "label": "Component (asset)", "detail": "component_auto.refresh_from_publish_folder (ADR 0019 / 0023)"},
        {"kind": "hook", "label": "Stage du shot", "detail": "shot_stage.refresh_from_publish_folder, departement de shot (ADR 0020)"},
    ],
    "houdini_export": [
        {"kind": "output", "label": "Fichier vNNN", "detail": "le ROP ecrit directement la version immuable (ADR 0017)"},
        {"kind": "output", "label": "LAST", "detail": "derive apres le cook ; sequence = .link"},
        {"kind": "output", "label": "modif_logs.json", "detail": "modif_log.append_log"},
        {"kind": "output", "label": "Activite", "detail": "activity_writer.log_publish"},
    ],
    "conform_texture": [
        {"kind": "output", "label": "Textures .tx", "detail": "texture_conform.conform_set (Painter / Mari, interrupteur conform)"},
    ],
    "generate_proxy": [
        {"kind": "output", "label": "Layer proxy", "detail": "<source>.proxy.usda (purpose proxy)"},
    ],
}


def _command_outputs(key: str) -> List[str]:
    """Output keys of a command: the keys of the dict literals its execute() returns."""
    import ast
    import textwrap

    try:
        src = textwrap.dedent(inspect.getsource(get_command(key)))
    except Exception:  # noqa: BLE001 - unknown command / no source (frozen build)
        return []
    keys: List[str] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for k in node.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value not in keys:
                    keys.append(k.value)
    return keys


def _runner_inputs(source: Path) -> List[Dict[str, Any]]:
    """What the runner injects into this action at launch (read in runner.py).

    * context  : keys of the ``context`` dict passed to ActionQuery.from_file
    * runtime  : parameters set with query.set_parameter("step", "cmd", "param", ...)
    """
    import ast

    from flux_actions import runner

    try:
        tree = ast.parse(Path(runner.__file__).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    consts = {n: getattr(runner, n) for n in dir(runner) if n.endswith("_ACTION")}
    inputs: List[Dict[str, Any]] = []
    seen = set()
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    calls_of = {fn.name: [c for c in ast.walk(fn) if isinstance(c, ast.Call)] for fn in funcs}
    # A function uses the action when it loads its YAML, or calls a helper that does
    # (run_publish_action -> _build_publish_query).
    users = {name for name, calls in calls_of.items()
             if any(isinstance(a, ast.Name) and consts.get(a.id) == source for c in calls for a in c.args)}
    users |= {name for name, calls in calls_of.items()
              if any(isinstance(c.func, ast.Name) and c.func.id in users for c in calls)}
    for fn in funcs:
        if fn.name not in users:
            continue
        calls = calls_of[fn.name]
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                    and any(isinstance(t, ast.Name) and t.id == "context" for t in node.targets)):
                for k in node.value.keys:
                    if isinstance(k, ast.Constant) and ("context", k.value) not in seen:
                        seen.add(("context", k.value))
                        inputs.append({"kind": "context", "name": k.value, "target": "", "function": fn.name})
        for c in calls:
            if isinstance(c.func, ast.Attribute) and c.func.attr == "set_parameter" and len(c.args) >= 3:
                parts = [a.value for a in c.args[:3] if isinstance(a, ast.Constant)]
                if len(parts) == 3 and ("runtime", tuple(parts)) not in seen:
                    seen.add(("runtime", tuple(parts)))
                    inputs.append({"kind": "runtime", "name": parts[2],
                                   "target": _node_id(parts[0], parts[1]), "function": fn.name})
    return inputs


def _yaml_notes(path: Path) -> Dict[str, List[str]]:
    """Comments written inside the YAML, by "step" or "step.command" (header excluded)."""
    notes: Dict[str, List[str]] = {}
    step = cmd = ""
    in_steps = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return notes
    for raw in lines:
        body = raw.strip()
        if not body:
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if body.startswith("#"):
            if in_steps and step:
                notes.setdefault(f"{step}.{cmd}" if cmd else step, []).append(body.lstrip("#").strip())
            continue
        key = body.split(":", 1)[0].strip()
        if indent == 0:
            in_steps = key == "steps"
            step = cmd = ""
        elif in_steps and indent == 2:
            step, cmd = key, ""
        elif in_steps and indent == 6 and body.endswith(":") and step:
            cmd = key
    return notes


def _node_id(step_name: str, cmd_name: str) -> str:
    return f"{step_name}.{cmd_name}"


def _param_view(param: Any) -> Dict[str, Any]:
    """A read-only view of one parameter for a node body.

    ``wired`` marks a value fed from another command's output (an OutputRef);
    such a value is machine-fed, never typed by a user.
    """
    wired = isinstance(param.value, OutputRef)
    value = param.value.serialize() if wired else param.value
    return {
        "name": param.name,
        "type": param.type,
        "label": param.label if param.label is not None else param.name,
        "value": value,
        "wired": wired,
        "hide": param.hide,
        "tooltip": getattr(param, "tooltip", None) or "",
    }


def build_action_graph(name: str) -> Dict[str, Any]:
    """Return ``{name, nodes, edges}`` for the named action.

    Raises KeyError when *name* is not a known action.
    """
    source = _action_files()[name]  # KeyError -> unknown action (handled by caller)
    query = ActionQuery.from_file(source)
    buffer = query.buffer

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    ordered = buffer.ordered_steps()
    notes = _yaml_notes(source)

    # ── nodes: one per command ────────────────────────────────────────────────
    for step in ordered:
        for cmd_name, cmd in step.commands.items():
            nid = _node_id(step.name, cmd_name)
            nodes.append(
                {
                    "id": _node_id(step.name, cmd_name),
                    "position": {"x": 0, "y": 0},  # front runs the layout
                    "data": {
                        "label": cmd_name,
                        "command": cmd.command,
                        "step": step.name,
                        "index": step.index,
                        "status": cmd.status.value,
                        "params": [_param_view(p) for p in cmd.parameters.values()],
                        "outputs": _command_outputs(cmd.command),
                        "effects": COMMAND_EFFECTS.get(cmd.command, []),
                        "note": "\n".join(notes.get(nid, [])),
                        **_command_doc(cmd.command),
                    },
                }
            )

    # ── order edges: one per pair of consecutive steps (first command to first) ─
    with_cmds = [st for st in ordered if st.commands]
    for earlier, later in zip(with_cmds, with_cmds[1:]):
        src = _node_id(earlier.name, next(iter(earlier.commands)))
        dst = _node_id(later.name, next(iter(later.commands)))
        edges.append({"id": f"order:{src}->{dst}", "source": src, "target": dst, "kind": "order"})

    # ── data-flow edges: a parameter wired from another command's output ──────
    for step in ordered:
        for cmd_name, cmd in step.commands.items():
            dst = _node_id(step.name, cmd_name)
            for param in cmd.parameters.values():
                if not isinstance(param.value, OutputRef):
                    continue
                ref = param.value
                src = _node_id(ref.step, ref.command)
                edges.append(
                    {
                        "id": f"data:{src}.{ref.key}->{dst}.{param.name}",
                        "source": src,
                        "target": dst,
                        "kind": "dataflow",
                        "label": f"{ref.key} -> {param.name}",
                    }
                )

    steps = [{"name": st.name, "index": st.index, "commands": list(st.commands),
              "note": "\n".join(notes.get(st.name, []))} for st in ordered]
    return {"name": name, "nodes": nodes, "edges": edges, "steps": steps,
            "inputs": _runner_inputs(source),
            "description": _header_comment(source), "file": source.name}
