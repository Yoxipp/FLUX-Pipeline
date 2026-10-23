# migrate_v1.py — v1 YAML actions -> v2 flows (01_ARCHITECTURE §15, ADR 0057).
#
# On demand only, never at startup (several machines, no race), idempotent, the
# originals are never touched:
#   backend/flux_actions/config/*.yml -> backend/flux_flows/shipped/legacy_<name>.flow.yml
#       dev script, run ONCE and reviewed in the diff:  python -m flux_flows.migrate_v1 --shipped
#   CONFIG/actions/*.yml -> team flows (CONFIG/extensions/flows/), v001, inactive, history "migrate"
#       copies of a shipped action become legacy_<name>, actions created by the team keep their name
#       (POST /flows/migrate {dry_run}, Team TD)
#   CONFIG/nodes/*.py -> copied to CONFIG/extensions/nodes/ (inert for v2: no @flow_node)
#
# Conversion: event.manual, then one node per command chained by exec in v1 order
# (steps by (index, name), commands in file order). call_function -> flux.call_function,
# any other command -> flux.legacy_command (they run from P2 / P3). A v1 reference
# value: {from: "step.cmd.key"} becomes a data link <producer>.<key> -> <consumer>.<param>:
# the ports of these two nodes are dynamic, typed in params.ports (an output takes the
# type of the input that reads it). Literals go to params, ask_user to the interface
# + data.flow_input. One column per step (320 px), commands stacked inside it.
# legacy_* flows never activate (store.set_active): publish runs on v1 until P8.

from __future__ import annotations

import argparse
import filecmp
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from flux_flows import store
from flux_flows.model import LABEL_MAX, NAME_RE, RESERVED_NAMES, Flow, dump_flow, parse_flow

# Layout: one column per step (320 px, node width 240); inside a column, each command
# then its data.flow_input feeders, stacked with the editor's node height (v1_adapter.ts).
COL, GAP, HEADER_H, ROW_H = 320, 28, 28, 20
LEGACY_COMMAND = "flux.legacy_command"
CALL_FUNCTION = "flux.call_function"
_META_FIELDS = ("label", "tooltip", "hide", "prompt", "ask_user")
# v1 parameter type -> v2 port type (01 §3).
_TYPES = {"str": "str", "text": "str", "select": "str", "path": "path", "bool": "bool", "int": "int",
          "float": "float", "dict": "dict", "list": "list[any]", "any": "any"}
_INTERFACE_TYPES = {"str", "path", "bool", "int", "float", "list[str]"}


def v1_config_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "flux_actions" / "config"


def _v2_type(v1_type: Optional[str]) -> str:
    return _TYPES.get(v1_type or "str", "any")


# -- reading ------------------------------------------------------------------

def _comments(text: str) -> Tuple[str, str]:
    """(notes, description): the comment lines of the file, the "FR:" block apart."""
    notes: List[str] = []
    fr: List[str] = []
    in_fr = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped.startswith("#"):
            if stripped:
                in_fr = False
            continue
        line = stripped[1:].strip()
        if line == "FR:":
            in_fr = True
            continue
        (fr if in_fr else notes).append(line)
    return "\n".join(notes).strip(), " ".join(l for l in fr if l).strip()


def _default_param(command_cls: type, cmd_name: str, param: str) -> Any:
    try:
        return command_cls.build_buffer(cmd_name, {}).parameters.get(param)
    except Exception:  # noqa: BLE001 - only used to tell authored values from defaults
        return None


def _height(node: Dict[str, Any]) -> int:
    # Same formula as nodeHeight (app/src/pages/flow_editor/v1_adapter.ts).
    ports = node.get("params", {}).get("ports")
    if ports:
        rows = 1 + max(len(ports["inputs"]), len(ports["outputs"]))
    else:
        rows = 1   # event.manual: then; data.flow_input: value
    return HEADER_H + ROW_H * rows + 8


def _place(nodes: Dict[str, Dict[str, Any]], columns: List[List[str]]) -> None:
    for col, ids in enumerate(columns):
        y = 0
        for node_id in ids:
            nodes[node_id]["pos"] = [col * COL, y]
            y += _height(nodes[node_id]) + GAP


def flow_name_for(v1_name: str, *, legacy: bool) -> str:
    return f"{store.LEGACY_PREFIX}{v1_name}" if legacy else v1_name


def convert_action(path: Path, *, flow_name: str, search_paths: Optional[List[Path]] = None) -> Tuple[Optional[Flow], Dict[str, Any]]:
    """One v1 action file -> (Flow or None, report {action, flow, nodes, unknown_commands, unresolved_links, error})."""
    from flux_core import OutputRef, get_command, load_action

    path = Path(path)
    report: Dict[str, Any] = {"action": path.stem, "flow": flow_name, "nodes": 0,
                              "unknown_commands": [], "unresolved_links": [], "error": None}
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    raw_steps = raw.get("steps") or {}
    for step in raw_steps.values():
        for cmd in ((step or {}).get("commands") or {}).values():
            key = (cmd or {}).get("command")
            try:
                get_command(key)
            except Exception:  # noqa: BLE001 - KeyError today; any lookup failure = unknown
                report["unknown_commands"].append(key)
    if report["unknown_commands"]:
        report["error"] = "commandes v1 inconnues"
        return None, report
    try:
        action = load_action(path, search_paths)
    except Exception as exc:  # noqa: BLE001 - reported, never raised to the batch
        report["error"] = f"{type(exc).__name__}: {exc}"
        return None, report

    notes_text, description = _comments(text)
    nodes: Dict[str, Dict[str, Any]] = {"n1": {"type": "event.manual", "pos": [0, 0], "params": {}}}
    links: List[Dict[str, str]] = []
    origin_params: Dict[str, Dict[str, Any]] = {}
    inputs: List[Dict[str, Any]] = []
    by_ref: Dict[Tuple[str, str], str] = {}   # (step, command) -> node id
    pending: List[Tuple[str, str, str, Any]] = []   # (node, param, type, OutputRef)
    exec_prev, n = "n1", 1
    flow_inputs = 0
    columns: List[List[str]] = [["n1"]]

    for step in action.ordered_steps():
        columns.append([])
        for cmd_name, cmd in step.commands.items():
            n += 1
            node_id = f"n{n}"
            by_ref[(step.name, cmd_name)] = node_id
            command_cls = get_command(cmd.command)
            literals: Dict[str, Any] = {}
            in_ports: Dict[str, str] = {}
            feeders: Dict[str, Dict[str, Any]] = {}
            for pname, param in cmd.parameters.items():
                default = _default_param(command_cls, cmd_name, pname)
                ptype = _v2_type(param.type)
                meta = {f: getattr(param, f) for f in _META_FIELDS
                        if default is None or getattr(param, f) != getattr(default, f)}
                if meta:
                    origin_params[f"{node_id}.{pname}"] = meta
                if isinstance(param.value, OutputRef):
                    in_ports[pname] = ptype
                    pending.append((node_id, pname, ptype, param.value))
                elif param.ask_user:
                    flow_inputs += 1
                    input_id = f"{cmd_name}_{pname}"[:40]
                    itype = ptype if ptype in _INTERFACE_TYPES else "str"
                    inputs.append({"id": input_id, "type": itype, "label": param.label or pname,
                                   "default": param.value})
                    src = f"in{flow_inputs}"
                    feeders[src] = {"type": "data.flow_input", "params": {"id": input_id}}
                    in_ports[pname] = ptype
                    links.append({"from": f"{src}.value", "to": f"{node_id}.{pname}"})
                elif default is None or param.value != default.value:
                    literals[pname] = param.value
            if cmd.command == "call_function":
                params: Dict[str, Any] = {"function": literals.pop("function", None)}
                if literals:
                    params["args"] = literals
                node_type = CALL_FUNCTION
            else:
                params = {"command": cmd.command}
                if literals:
                    params["params"] = literals
                node_type = LEGACY_COMMAND
            params["ports"] = {"inputs": in_ports, "outputs": {}}
            nodes[node_id] = {"type": node_type, "params": params, "label": f"{step.name}.{cmd_name}"}
            nodes.update(feeders)
            columns[-1] += [node_id, *feeders]
            links.append({"from": f"{exec_prev}.then", "to": f"{node_id}.exec"})
            exec_prev = node_id

    for node_id, pname, ptype, ref in pending:
        src = by_ref.get((ref.step, ref.command))
        if src is None or int(src[1:]) >= int(node_id[1:]):
            report["unresolved_links"].append(f"{ref.step}.{ref.command}.{ref.key} -> {node_id}.{pname}")
            nodes[node_id]["params"]["ports"]["inputs"].pop(pname, None)
            continue
        nodes[src]["params"]["ports"]["outputs"].setdefault(ref.key, ptype)
        links.append({"from": f"{src}.{ref.key}", "to": f"{node_id}.{pname}"})

    _place(nodes, columns)
    doc: Dict[str, Any] = {
        "flux_flow": 2, "name": flow_name,
        "label": f"{action.name} (v1)"[:LABEL_MAX], "description": description,
        "origin": {"kind": "v1", "name": action.name, "shelf": action.shelf, "thumbnail": action.thumbnail,
                   "extends": raw.get("extends"), "params": origin_params},
        "interface": inputs, "nodes": nodes, "links": links,
        "notes": [{"id": "k1", "pos": [0, _height(nodes["n1"]) + GAP], "text": notes_text}] if notes_text else [],
    }
    try:
        flow = parse_flow(doc)
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
        return None, report
    report["nodes"] = len(nodes)
    return flow, report


# -- shipped (dev script) -----------------------------------------------------

def migrate_shipped(source: Optional[Path] = None, dest: Optional[Path] = None, *, write: bool = True) -> List[Dict[str, Any]]:
    """backend/flux_actions/config/*.yml -> shipped/legacy_<name>.flow.yml. Rewrites only on change."""
    from flux_actions import commands  # noqa: F401 - registers the v1 commands

    source = source or v1_config_dir()
    from flux_flows import locations

    dest = dest or locations.shipped_dir()
    reports = []
    for path in sorted(Path(source).glob("*.yml")):
        flow, report = convert_action(path, flow_name=flow_name_for(path.stem, legacy=True))
        if flow is not None:
            target = Path(dest) / f"{flow.name}{store.SUFFIX}"
            text = dump_flow(flow)
            report["status"] = "unchanged" if target.is_file() and target.read_text(encoding="utf-8") == text else "written"
            if write and report["status"] == "written":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode("utf-8"))
        else:
            report["status"] = "failed"
        reports.append(report)
    return reports


# -- team (POST /flows/migrate) -----------------------------------------------

def _copy_nodes(src: Optional[Path], dst: Optional[Path], dry_run: bool) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if src is None or dst is None or not src.is_dir():
        return out
    for path in sorted(src.glob("*.py")):
        target = dst / path.name
        if target.is_file():
            status = "unchanged" if filecmp.cmp(path, target, shallow=False) else "conflict"
        else:
            status = "copied"
            if not dry_run:
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        out.append({"file": path.name, "status": status})
    return out


def migrate_team(roots: Dict[str, Optional[Path]], *, actions_dir: Optional[Path], nodes_src: Optional[Path],
                 nodes_dst: Optional[Path], shipped_names: List[str], user: str, dry_run: bool = True) -> Dict[str, Any]:
    """CONFIG/actions/*.yml -> team flows. Never overwrites a team flow: an existing one
    is "unchanged" (same content) or "exists" (edited since). Returns the report."""
    actions: List[Dict[str, Any]] = []
    files = sorted(Path(actions_dir).glob("*.yml")) if actions_dir and Path(actions_dir).is_dir() else []
    team_root = Path(roots["team"]) if roots.get("team") else None
    for path in files:
        name = flow_name_for(path.stem, legacy=path.stem in shipped_names)
        if not NAME_RE.match(name) or name in RESERVED_NAMES:
            actions.append({"action": path.stem, "flow": name, "status": "failed", "error": "nom de flow invalide ou reserve"})
            continue
        flow, report = convert_action(path, flow_name=name, search_paths=[path.parent, v1_config_dir()])
        if flow is None:
            report["status"] = "failed"
        elif team_root is not None and store.working_file(team_root, name).is_file():
            current = store.working_file(team_root, name).read_text(encoding="utf-8")
            report["status"] = "unchanged" if store._canonical(current) == dump_flow(flow) else "exists"
        elif dry_run:
            report["status"] = "would_write"
        else:
            store.save_flow(roots, "team", flow, user=user, note=f"migration v1 {path.stem}")
            out = store.increment_flow(roots, "team", name, user=user, note=f"migration v1 {path.stem}")
            store._history(roots, "team", {"kind": "migrate", "user": user, "flow": name, "from": path.name,
                                           "version": out["created"]})
            report["status"] = "written"
        actions.append(report)
    return {"dry_run": dry_run, "actions": actions, "nodes": _copy_nodes(nodes_src, nodes_dst, dry_run)}


def migrate_team_config(*, user: str, dry_run: bool = True) -> Dict[str, Any]:
    """POST /flows/migrate: the real CONFIG/ folders (rights checked by the router)."""
    from flux_actions import catalog, commands  # noqa: F401 - registers the v1 commands
    from flux_flows import locations

    catalog.load_user_nodes()   # team commands used by CONFIG/actions
    return migrate_team({"team": locations.scope_dir("team")}, actions_dir=catalog.actions_dir(),
                        nodes_src=catalog.nodes_dir(), nodes_dst=locations.team_nodes_dir(),
                        shipped_names=[p.stem for p in v1_config_dir().glob("*.yml")],
                        user=user, dry_run=dry_run)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Dev script: v1 actions -> shipped legacy_* flows (01 §15).")
    parser.add_argument("--shipped", action="store_true", required=True)
    parser.add_argument("--check", action="store_true", help="report only, write nothing")
    args = parser.parse_args(argv)
    reports = migrate_shipped(write=not args.check)
    for r in reports:
        extra = f" error={r['error']}" if r["error"] else ""
        extra += f" unresolved={r['unresolved_links']}" if r["unresolved_links"] else ""
        print(f"{r['action']:<18} -> {r['flow']:<26} {r['status']:<9} nodes={r['nodes']}{extra}")
    return 1 if any(r["status"] == "failed" for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
