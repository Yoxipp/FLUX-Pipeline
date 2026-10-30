# team_commands.py — commands typed in the Team chat start flows (ADR 0081).
#
# A flow declares a command with an event.team_command node (TeamCommand): name, help,
# channels, confirm. Typing `/zip "\\server\proj\SEQ010"` in the built-in Team page runs
# every ACTIVE flow (perso of the author, team, project) whose active version has a
# TeamCommand of that name, on the backend of the author (their rights, their paths, no host).
# The flows are found by reading them, as page_inputs.listeners does for page buttons.

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from flux_flows import store
from flux_flows.page_inputs import _active_flows
from flux_flows.store import FlowStoreError

COMMAND_NODE = "event.team_command"
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
# `/name rest`: the name is lower case, the rest is free text.
_LINE_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]{1,31})(?:\s+(.*))?$", re.DOTALL)
# "quoted text" (Windows paths keep their backslashes) or a bare word.
_ARG_RE = re.compile(r'"([^"]*)"|(\S+)')
REPLY_NAME = "FLUX"     # author of the messages FLUX writes for a command

Roots = Mapping[str, Optional[Path]]


def parse(text: str) -> Optional[Tuple[str, List[str], str]]:
    """(name, args, rest) of a command line, None when *text* is not one. A trailing
    slash of an argument is dropped (`SEQ010\\` and `SEQ010` are the same folder)."""
    m = _LINE_RE.match((text or "").strip())
    if not m:
        return None
    rest = (m.group(2) or "").strip()
    args = []
    for quoted, bare in _ARG_RE.findall(rest):
        value = bare or quoted
        stripped = value.rstrip("/\\")
        args.append(stripped if stripped and not stripped.endswith(":") else value)
    return m.group(1).lower(), args, rest


def channel_allowed(params: Mapping[str, Any], channel: str) -> bool:
    """The `channels` param: patterns separated by spaces or commas, empty = every channel."""
    patterns = [p for p in re.split(r"[\s,]+", str(params.get("channels") or "").strip().lower()) if p]
    return not patterns or any(fnmatch.fnmatchcase(channel or "general", p.lstrip("#")) for p in patterns)


def commands(flow_roots: Roots, channel: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every command of the active flows: [{name, help, confirm, channels, flow, scope,
    version, node}], sorted by name. *channel* keeps those allowed in that channel.
    A flow hidden by a higher scope of the same name is skipped (store.resolve)."""
    out: List[Dict[str, Any]] = []
    for scope, name, version in _active_flows(flow_roots):
        if store.resolve(flow_roots, name) != scope:
            continue
        try:
            flow = store.read_flow(flow_roots, scope, name, version)["flow"]
        except FlowStoreError:
            continue
        for nid, node in sorted(flow.nodes.items()):
            if node.type != COMMAND_NODE:
                continue
            command = str(node.params.get("name") or "").strip().lower()
            if not NAME_RE.match(command):
                continue
            if channel is not None and not channel_allowed(node.params, channel):
                continue
            out.append({"name": command, "help": str(node.params.get("help") or ""),
                        "confirm": bool(node.params.get("confirm")),
                        "channels": str(node.params.get("channels") or ""),
                        "flow": name, "scope": scope, "version": version, "node": nid,
                        "label": flow.label or name})
    out.sort(key=lambda c: (c["name"], c["scope"], c["flow"]))
    return out


def listeners(flow_roots: Roots, command: str, channel: str) -> List[Dict[str, Any]]:
    """The commands named *command* allowed in *channel*."""
    return [c for c in commands(flow_roots, channel) if c["name"] == command]
