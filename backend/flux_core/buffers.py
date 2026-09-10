# buffers.py — serialisable state tree for one action.
#
# The engine keeps the whole action state in nested buffers:
#
#     ActionBuffer -> StepBuffer -> CommandBuffer -> ParameterBuffer
#
# Buffers serialise to plain dicts. The front never receives the full state on
# every change: it receives only the diff between the previous and current
# serialisation (see ``diff_dicts``). This keeps the websocket traffic small,
# exactly like the Silex buffer/diff model.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .status import Status

# Sentinel used inside a diff to mark a key that no longer exists.
REMOVED = {"__removed__": True}


@dataclass
class OutputRef:
    """A parameter value that points at another command's named output.

    Authored in YAML as ``value: {from: "step.command.output_key"}`` and kept
    unresolved until execution time, when the producing command has run.
    """

    step: str
    command: str
    key: str

    @classmethod
    def parse(cls, ref: str) -> "OutputRef":
        parts = ref.split(".")
        if len(parts) != 3:
            raise ValueError(
                f"output reference must be 'step.command.key', got {ref!r}"
            )
        return cls(step=parts[0], command=parts[1], key=parts[2])

    def serialize(self) -> Dict[str, str]:
        return {"from": f"{self.step}.{self.command}.{self.key}"}


@dataclass
class ParameterBuffer:
    """One typed input of a command."""

    name: str
    type: str = "str"
    value: Any = None
    label: Optional[str] = None
    tooltip: Optional[str] = None
    hide: bool = False        # not shown in the generated form
    ask_user: bool = False    # pause for input in interactive mode
    prompt: bool = False      # force a prompt even when a value exists
    status: Status = Status.WAITING

    def serialize(self) -> Dict[str, Any]:
        value = self.value.serialize() if isinstance(self.value, OutputRef) else self.value
        return {
            "name": self.name,
            "type": self.type,
            "value": value,
            "label": self.label if self.label is not None else self.name,
            "tooltip": self.tooltip,
            "hide": self.hide,
            "ask_user": self.ask_user,
            "prompt": self.prompt,
            "status": self.status.value,
        }


@dataclass
class CommandBuffer:
    """One atomic step-in-a-step: a registered command plus its parameters."""

    name: str
    command: str  # stable registry key, resolved via the command registry
    parameters: Dict[str, ParameterBuffer] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    status: Status = Status.WAITING
    logs: list = field(default_factory=list)

    def serialize(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "parameters": {k: p.serialize() for k, p in self.parameters.items()},
            "outputs": dict(self.outputs),
            "status": self.status.value,
            "logs": list(self.logs),
        }


@dataclass
class StepBuffer:
    """An ordered group of commands. Steps run in ascending ``index`` order."""

    name: str
    index: int = 0
    commands: Dict[str, CommandBuffer] = field(default_factory=dict)
    status: Status = Status.WAITING

    def serialize(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "index": self.index,
            "commands": {k: c.serialize() for k, c in self.commands.items()},
            "status": self.status.value,
        }


@dataclass
class ActionBuffer:
    """The whole action: metadata plus its ordered steps and a context snapshot."""

    name: str
    shelf: Optional[str] = None
    thumbnail: Optional[str] = None
    steps: Dict[str, StepBuffer] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    status: Status = Status.WAITING

    def ordered_steps(self) -> list["StepBuffer"]:
        """Steps sorted by index, then by name for a stable tie-break."""
        return sorted(self.steps.values(), key=lambda s: (s.index, s.name))

    def serialize(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "shelf": self.shelf,
            "thumbnail": self.thumbnail,
            "context": dict(self.context),
            "status": self.status.value,
            "steps": {k: s.serialize() for k, s in self.steps.items()},
        }


def diff_dicts(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Return only what changed between two serialised buffer states.

    A leaf that changed appears with its new value. A nested dict that changed
    appears with only its changed children. A key present in ``old`` but not in
    ``new`` appears as ``REMOVED``. Unchanged branches are omitted entirely.
    """

    out: Dict[str, Any] = {}
    for key, new_val in new.items():
        if key not in old:
            out[key] = new_val
            continue
        old_val = old[key]
        if isinstance(old_val, dict) and isinstance(new_val, dict):
            child = diff_dicts(old_val, new_val)
            if child:
                out[key] = child
        elif old_val != new_val:
            out[key] = new_val
    for key in old:
        if key not in new:
            out[key] = REMOVED
    return out
