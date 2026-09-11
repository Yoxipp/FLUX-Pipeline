# flux_core — declarative action engine (YAML steps -> Python commands).
#
# Pure core: zero dependency on any DCC. DCC packages (flux_maya, flux_houdini,
# ...) import flux_core, never the other way round. The public surface exported
# here is the compat contract other layers rely on; treat it like pipe_core.py
# and never break it without checking every consumer (gitnexus impact).

from __future__ import annotations

from .action_query import ActionQuery
from .buffers import (
    ActionBuffer,
    CommandBuffer,
    OutputRef,
    ParameterBuffer,
    StepBuffer,
    diff_dicts,
)
from .command_base import CommandBase
from .loader import (
    ActionLoadError,
    ActionSchemaError,
    build_action_buffer,
    load_action,
)
from .parameters import ParameterCastError, cast_value, is_known_type
from .repository import MetadataRepository
from .registry import (
    CommandNotFound,
    all_commands,
    get_command,
    is_registered,
    register,
)
from .status import Status

__all__ = [
    "ActionQuery",
    "ActionBuffer",
    "StepBuffer",
    "CommandBuffer",
    "ParameterBuffer",
    "OutputRef",
    "diff_dicts",
    "CommandBase",
    "load_action",
    "build_action_buffer",
    "ActionSchemaError",
    "ActionLoadError",
    "register",
    "get_command",
    "is_registered",
    "all_commands",
    "CommandNotFound",
    "cast_value",
    "is_known_type",
    "ParameterCastError",
    "MetadataRepository",
    "Status",
]
