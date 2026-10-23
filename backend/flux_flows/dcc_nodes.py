# dcc_nodes.py — DCC nodes shipped as locked subflows, like Houdini HDAs (01 §12, 03 §8,
# decisions 18 and 19). P6a.
#
# A flow with ``node_type`` is a NODE of the catalogue: its interface inputs are the node's
# ports (``select`` inputs = settings with choices), its interface outputs the node's
# outputs; the engine runs it inline like a FlowCall (working file, started at its
# event.manual). Double click in the editor = enter it, read only.
#   shipped  backend/flux_flows/shipped/dcc/<soft>/<name>.flow.yml   (in the exe, never written)
#   team     CONFIG/extensions/flows/<name>.flow.yml with the same node_type = "Deverrouiller"
#            (POST /flows/{name}/unlock, Team TD): it replaces the shipped node for the whole
#            team; deleting it ("Revenir au defaut") brings the shipped one back.
# A team flow with a node_type no shipped flow has is a team node built from nodes.
# Flags (session, live_only, licence, effect, destructive, icon) come from the core leaf
# ``<node_type>_core`` when there is one (the Python node inside, hidden from Tab / Shelf).

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DCC_DIR = "dcc"
_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"sig": None, "index": {}, "at": 0.0}
RESCAN_S = 2.0      # the team folder may sit on the share: stat it at most every 2 s


@dataclass
class DccFlow:
    name: str
    scope: str            # shipped | team
    path: Path
    flow: Any
    shipped_path: Optional[Path] = None   # the shipped original of a team copy


def shipped_dcc_dir() -> Path:
    from flux_flows import locations

    return locations.shipped_dir() / DCC_DIR


def shipped_file(name: str) -> Optional[Path]:
    """shipped/dcc/<soft>/<name>.flow.yml, None when *name* is not a shipped DCC node."""
    from flux_flows.store import SUFFIX

    folder = shipped_dcc_dir()
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob(f"*/{name}{SUFFIX}")):
        return path
    return None


def _team_dir() -> Optional[Path]:
    from flux_flows import locations

    try:
        return locations.scope_dir("team")
    except (RuntimeError, ValueError):
        return None


def _files() -> List[Tuple[str, Path]]:
    from flux_flows.store import SUFFIX

    out: List[Tuple[str, Path]] = []
    folder = shipped_dcc_dir()
    if folder.is_dir():
        out += [("shipped", p) for p in sorted(folder.glob(f"*/*{SUFFIX}"))]
    team = _team_dir()
    if team is not None and team.is_dir():
        out += [("team", p) for p in sorted(team.glob(f"*{SUFFIX}"))]
    return out


def _signature(files: List[Tuple[str, Path]]) -> Tuple:
    sig = []
    for scope, path in files:
        try:
            st = path.stat()
            sig.append((scope, str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    return tuple(sig)


def index() -> Dict[str, DccFlow]:
    """{node_type: DccFlow}: the team copy wins over the shipped flow. Re-read when a file
    changes (mtime + size); a broken file is skipped."""
    from flux_flows.model import FlowSchemaError, load_flow_text

    with _LOCK:
        if _CACHE["sig"] is not None and time.monotonic() - _CACHE["at"] < RESCAN_S:
            return dict(_CACHE["index"])
    files = _files()
    sig = _signature(files)
    with _LOCK:
        if sig == _CACHE["sig"]:
            _CACHE["at"] = time.monotonic()
            return dict(_CACHE["index"])
    found: Dict[str, DccFlow] = {}
    shipped_by_type: Dict[str, Path] = {}
    for scope, path in files:
        try:
            text = path.read_text(encoding="utf-8")
            if scope == "team" and "node_type:" not in text:
                continue                        # a plain team flow: not a node
            flow = load_flow_text(text)
        except (OSError, FlowSchemaError, ValueError):
            continue
        if not flow.node_type:
            continue
        if scope == "shipped":
            shipped_by_type[flow.node_type] = path
            found.setdefault(flow.node_type, DccFlow(flow.name, "shipped", path, flow))
        else:
            found[flow.node_type] = DccFlow(flow.name, "team", path, flow, shipped_by_type.get(flow.node_type))
    with _LOCK:
        _CACHE["sig"], _CACHE["index"], _CACHE["at"] = sig, found, time.monotonic()
    return dict(found)


def reset_cache() -> None:
    with _LOCK:
        _CACHE["sig"], _CACHE["index"], _CACHE["at"] = None, {}, 0.0


def _interface_port(item: Any, required: bool = False):
    from flux_flows.nodes.registry import port

    doc = item.label or item.id
    if item.type == "select":
        options = list(item.options or [])
        return port(item.id, "str", doc, doc, item.default, default=item.default, choices=options, wirable=False)
    return port(item.id, item.type, doc, doc, item.default, default=item.default, required=required)


def spec_for(entry: DccFlow):
    """The NodeSpec of a DCC flow (ports = interface, flags of its core leaf)."""
    from flux_flows.nodes import registry
    from flux_flows.nodes.registry import NodeSpec, port

    flow = entry.flow
    node_type = flow.node_type
    family = node_type.split(".", 1)[0]
    core = registry.get_core(f"{node_type}_core")
    inputs = [port("exec", "exec", required=True)]
    params = []
    for item in flow.interface.inputs:
        p = _interface_port(item, required=item.type.startswith("session["))
        (params if item.type == "select" else inputs).append(p)
    outputs = [port("then", "exec"), port("on_error", "exec")]
    outputs += [port(o.id, o.type, o.label or o.id, o.label or o.id) for o in flow.interface.outputs]
    outputs.append(port("run_id", "str", "Run interne du node", "Inner run of the node"))
    name, scope, loaded = entry.name, entry.scope, flow

    async def body(ctx, inputs_, params_):
        values = {k: v for k, v in params_.items() if k in {i.id for i in loaded.interface.inputs}}
        values.update({k: v for k, v in inputs_.items() if k != "exec" and v is not None})
        return await ctx.call_flow(name, "current", values, flow=loaded)

    async def simulate(ctx, inputs_, params_):
        # The inner flow runs in dry mode too: its report lines are merged by call_flow.
        return {"lines": [], "outputs": await body(ctx, inputs_, params_)}

    effect = bool(core.effect) if core else any(
        (s := registry.get_core(n.type)) is not None and s.effect for n in flow.nodes.values())
    spec = NodeSpec(
        type=node_type, label=flow.label or node_type, family=family, icon=core.icon if core else "",
        inputs=inputs, outputs=outputs, params=params, shelf=core.shelf if core else None,
        aliases=list(core.aliases) if core else [], doc_fr=flow.description or (core.doc_fr if core else ""),
        doc_en=core.doc_en if core else flow.description, destructive=core.destructive if core else None,
        effect=effect, session=core.session if core else None, live_only=core.live_only if core else False,
        licence=core.licence if core else None, source="flux" if scope == "shipped" else "team",
        file=str(entry.path.name), func=body, simulate=simulate if effect else None,
    )
    spec.subflow = {"name": name, "scope": scope, "locked": scope == "shipped",
                    "shipped": scope == "shipped" or entry.shipped_path is not None}
    return spec


def specs() -> Dict[str, Any]:
    out = {}
    for node_type, entry in index().items():
        try:
            out[node_type] = spec_for(entry)
        except Exception:  # noqa: BLE001 - one broken DCC flow never hides the catalogue
            continue
    return out


def get_spec(node_type: str):
    entry = index().get(node_type)
    return spec_for(entry) if entry is not None else None
