# command_base.py — base class every command inherits from.
#
# A command is one atomic, reusable unit of pipeline work (build a path, save a
# scene, copy a file, submit to the farm). It declares its typed parameters as a
# class attribute and implements a single async ``run`` method. The same command
# runs in the UI, on the CLI and on the farm without change.

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .buffers import CommandBuffer, OutputRef, ParameterBuffer
from .parameters import ParameterCastError, cast_value, is_known_type
from .status import Status

# Fields a parameter declaration may carry in a command's ``parameters`` dict.
_PARAM_FIELDS = ("type", "value", "label", "tooltip", "hide", "ask_user", "prompt")


class CommandBase:
    """Base class for all commands. Subclasses set ``parameters`` and ``run``."""

    # Declared per subclass: param_name -> {type, value, label, hide, ...}.
    parameters: Dict[str, Dict[str, Any]] = {}

    # Context keys the command needs (project, sequence, shot, task...).
    required_metadata: List[str] = []

    # Set by the @register decorator; the stable key this command answers to.
    command_key: str = ""

    # -- parameter declaration ------------------------------------------------

    @classmethod
    def merged_parameters(cls) -> Dict[str, Dict[str, Any]]:
        """Merge ``parameters`` down the inheritance chain (subclass wins).

        Walks the MRO from the most base class to ``cls`` so a subclass can add
        parameters or override single fields of an inherited one.
        """

        merged: Dict[str, Dict[str, Any]] = {}
        for klass in reversed(cls.__mro__):
            own = vars(klass).get("parameters", {})
            for name, spec in own.items():
                merged.setdefault(name, {}).update(spec)
        return merged

    @classmethod
    def build_buffer(cls, name: str, overrides: Dict[str, Dict[str, Any]] | None = None) -> CommandBuffer:
        """Build a CommandBuffer from the declared parameters plus overrides.

        ``overrides`` is the per-command parameter block read from the action
        YAML; it can set values (including an ``OutputRef``) and toggle flags.
        """

        overrides = overrides or {}
        buffer = CommandBuffer(name=name, command=cls.command_key)
        specs = cls.merged_parameters()
        # Ensure YAML-only parameters (declared solely in the action) still exist.
        for param_name in overrides:
            specs.setdefault(param_name, {})
        for param_name, spec in specs.items():
            merged_spec = {**spec, **overrides.get(param_name, {})}
            buffer.parameters[param_name] = ParameterBuffer(
                name=param_name,
                type=merged_spec.get("type", "str"),
                value=merged_spec.get("value"),
                label=merged_spec.get("label"),
                tooltip=merged_spec.get("tooltip"),
                hide=bool(merged_spec.get("hide", False)),
                ask_user=bool(merged_spec.get("ask_user", False)),
                prompt=bool(merged_spec.get("prompt", False)),
            )
        return buffer

    # -- validation -----------------------------------------------------------

    @classmethod
    def check_parameters(cls, buffer: CommandBuffer, logger: logging.Logger) -> bool:
        """Cast each concrete parameter to its type. Return False on any failure.

        Unresolved output references are skipped here: they are resolved and
        re-checked at execution time, once the producing command has run.
        """

        ok = True
        for param in buffer.parameters.values():
            if isinstance(param.value, OutputRef):
                continue  # resolved later, in ActionQuery
            if not is_known_type(param.type):
                param.status = Status.INVALID
                logger.error("param %s: unknown type %r", param.name, param.type)
                ok = False
                continue
            if param.value is None:
                param.status = Status.WAITING
                continue
            try:
                param.value = cast_value(param.type, param.value)
                param.status = Status.VALID
            except ParameterCastError as exc:
                param.status = Status.INVALID
                logger.error("param %s: %s", param.name, exc)
                ok = False
        buffer.status = Status.VALID if ok else Status.INVALID
        return ok

    @classmethod
    def check_context_metadata(cls, context: Dict[str, Any], logger: logging.Logger) -> bool:
        """Return False (and log) when a required context key is missing."""

        missing = [k for k in cls.required_metadata if k not in context or context[k] is None]
        if missing:
            logger.error("command %s missing context: %s", cls.command_key, ", ".join(missing))
            return False
        return True

    # -- execution ------------------------------------------------------------

    async def run(self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger) -> Dict[str, Any]:
        """Do the work and return named outputs. Override in every subclass.

        ``parameters`` holds fully cast, fully resolved values. Returned keys
        become this command's outputs, addressable as ``step.command.key`` by
        later commands.
        """

        raise NotImplementedError(f"{type(self).__name__}.run is not implemented")
