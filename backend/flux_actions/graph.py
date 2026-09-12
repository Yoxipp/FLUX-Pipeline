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

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from flux_core import ActionQuery, OutputRef

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


def list_action_names() -> List[str]:
    """Return the action names a graph can be built for, sorted."""
    return sorted(ACTION_FILES)


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
    }


def build_action_graph(name: str) -> Dict[str, Any]:
    """Return ``{name, nodes, edges}`` for the named action.

    Raises KeyError when *name* is not a known action.
    """
    source = ACTION_FILES[name]  # KeyError -> unknown action (handled by caller)
    query = ActionQuery.from_file(source)
    buffer = query.buffer

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    ordered = buffer.ordered_steps()

    # ── nodes: one per command ────────────────────────────────────────────────
    for step in ordered:
        for cmd_name, cmd in step.commands.items():
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
                    },
                }
            )

    # ── order edges: consecutive steps, every command to every command ────────
    for earlier, later in zip(ordered, ordered[1:]):
        for src_cmd in earlier.commands:
            for dst_cmd in later.commands:
                src = _node_id(earlier.name, src_cmd)
                dst = _node_id(later.name, dst_cmd)
                edges.append(
                    {
                        "id": f"order:{src}->{dst}",
                        "source": src,
                        "target": dst,
                        "kind": "order",
                    }
                )

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

    return {"name": name, "nodes": nodes, "edges": edges}
