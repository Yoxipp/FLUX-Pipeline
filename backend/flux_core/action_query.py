# action_query.py — load, hold and run one action.
#
# ActionQuery is the object the UI, the CLI and the farm all talk to. It owns
# the ActionBuffer, lets callers override parameter values before running, and
# executes the steps in order. As execution mutates the buffer it emits diffs
# (never the full state) to an optional callback, so the front stays in sync
# over the existing :8765 websocket.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .buffers import ActionBuffer, OutputRef, diff_dicts
from .command_base import CommandBase
from .loader import load_action
from .parameters import ParameterCastError, cast_value
from .registry import get_command
from .status import Status

# A diff callback receives the minimal change set since the last emission.
DiffCallback = Callable[[Dict[str, Any]], None]


class ActionQuery:
    """Runtime front-end for a single action: resolve, override, execute."""

    def __init__(
        self,
        buffer: ActionBuffer,
        context: Optional[Dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
        on_diff: Optional[DiffCallback] = None,
    ) -> None:
        self.buffer = buffer
        # Snapshot the production context once, at construction (project/seq/shot/task).
        self.buffer.context = dict(context or {})
        self.logger = logger or logging.getLogger("flux_core.action")
        self._on_diff = on_diff
        self._last_serialized = self.buffer.serialize()
        # (step_name, command_name) -> named outputs of that command.
        self._outputs: Dict[Tuple[str, str], Dict[str, Any]] = {}

    # -- construction helpers -------------------------------------------------

    @classmethod
    def from_file(
        cls,
        source: Path,
        search_paths: Optional[List[Path]] = None,
        context: Optional[Dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
        on_diff: Optional[DiffCallback] = None,
    ) -> "ActionQuery":
        buffer = load_action(source, search_paths)
        return cls(buffer, context=context, logger=logger, on_diff=on_diff)

    # -- overrides ------------------------------------------------------------

    def set_parameter(self, step: str, command: str, param: str, value: Any) -> None:
        """Override one parameter value before execution."""
        self.buffer.steps[step].commands[command].parameters[param].value = value
        self._emit_diff()

    # -- diff emission --------------------------------------------------------

    def _emit_diff(self) -> None:
        current = self.buffer.serialize()
        if self._on_diff is not None:
            delta = diff_dicts(self._last_serialized, current)
            if delta:
                self._on_diff(delta)
        self._last_serialized = current

    # -- execution ------------------------------------------------------------

    def _resolve_value(self, value: Any) -> Any:
        """Replace an OutputRef by the value produced by the referenced command."""
        if not isinstance(value, OutputRef):
            return value
        key = (value.step, value.command)
        if key not in self._outputs or value.key not in self._outputs[key]:
            raise KeyError(
                f"output '{value.step}.{value.command}.{value.key}' not produced yet"
            )
        return self._outputs[key][value.key]

    async def execute(self) -> Status:
        """Run every step in index order. Return the final action status.

        A command failure stops the run and marks the action ERROR, but never
        raises out of here: the graph reports its own failure instead of
        crashing the host process.
        """

        self.buffer.status = Status.PROCESSING
        self._emit_diff()

        for step in self.buffer.ordered_steps():
            step.status = Status.PROCESSING
            self._emit_diff()
            for cmd_name, cmd in step.commands.items():
                if not await self._run_command(step.name, cmd_name, cmd):
                    step.status = Status.ERROR
                    self.buffer.status = Status.ERROR
                    self._emit_diff()
                    return self.buffer.status
            step.status = Status.COMPLETED
            self._emit_diff()

        self.buffer.status = Status.COMPLETED
        self._emit_diff()
        return self.buffer.status

    async def _run_command(self, step_name: str, cmd_name: str, cmd) -> bool:
        """Resolve, validate and run one command. Return False on failure."""
        command_cls: type[CommandBase] = get_command(cmd.command)
        cmd.status = Status.PROCESSING
        self._emit_diff()

        # Resolve output references and cast every value to its declared type.
        resolved: Dict[str, Any] = {}
        for param in cmd.parameters.values():
            try:
                raw = self._resolve_value(param.value)
            except KeyError as exc:
                param.status = Status.INVALID
                cmd.status = Status.INVALID
                self.logger.error("command %s.%s: %s", step_name, cmd_name, exc)
                self._emit_diff()
                return False
            if raw is None:
                resolved[param.name] = None
                continue
            try:
                resolved[param.name] = cast_value(param.type, raw)
                param.value = resolved[param.name]
                param.status = Status.VALID
            except ParameterCastError as exc:
                param.status = Status.INVALID
                cmd.status = Status.INVALID
                self.logger.error("command %s.%s param %s: %s", step_name, cmd_name, param.name, exc)
                self._emit_diff()
                return False

        if not command_cls.check_context_metadata(self.buffer.context, self.logger):
            cmd.status = Status.INVALID
            self._emit_diff()
            return False

        try:
            outputs = await command_cls().run(resolved, self, self.logger)
        except Exception as exc:  # noqa: BLE001 - a command must not crash the graph
            cmd.status = Status.ERROR
            cmd.logs.append(str(exc))
            self.logger.exception("command %s.%s raised", step_name, cmd_name)
            self._emit_diff()
            return False

        outputs = outputs or {}
        cmd.outputs = dict(outputs)
        self._outputs[(step_name, cmd_name)] = dict(outputs)
        cmd.status = Status.COMPLETED
        self._emit_diff()
        return True
