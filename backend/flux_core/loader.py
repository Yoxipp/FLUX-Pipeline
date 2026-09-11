# loader.py — read an action YAML, validate it, resolve inheritance, build a buffer.
#
# Design choices that avoid the usual action-engine anti-patterns:
#   * Standard YAML only. No custom ``!inherit`` / ``!command-output`` tags.
#     Inheritance is ``extends: <action_name>``; a data-flow reference is
#     ``value: {from: "step.command.output_key"}``. Both are resolved by code
#     here, so any IDE and static analysis can read the files.
#   * Every action is validated against a pydantic schema at load. A typo like
#     ``lavel:`` fails loudly with the exact field path, instead of being
#     silently ignored the way a custom-tag loader would.

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .buffers import ActionBuffer, OutputRef, StepBuffer
from .command_base import CommandBase
from .registry import get_command


class ActionSchemaError(ValueError):
    """Raised when an action file does not match the schema. Names the field."""


class ActionLoadError(ValueError):
    """Raised when an action file cannot be read or its ``extends`` is broken."""


# -- schema -------------------------------------------------------------------

class _ParameterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = "str"
    value: Any = None
    label: Optional[str] = None
    tooltip: Optional[str] = None
    hide: bool = False
    ask_user: bool = False
    prompt: bool = False


class _CommandModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str
    label: Optional[str] = None
    tooltip: Optional[str] = None
    parameters: Dict[str, _ParameterModel] = {}


class _StepModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = 0
    commands: Dict[str, _CommandModel] = {}


class _ActionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    extends: Optional[str] = None
    shelf: Optional[str] = None
    thumbnail: Optional[str] = None
    steps: Dict[str, _StepModel] = {}


# -- reading + inheritance ----------------------------------------------------

def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ActionLoadError(f"cannot read action file {path}: {exc}") from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ActionLoadError(f"action file {path} is not a YAML mapping")
    return data


def _find_action_file(name: str, search_paths: List[Path]) -> Path:
    for base in search_paths:
        candidate = base / f"{name}.yml"
        if candidate.is_file():
            return candidate
        candidate = base / f"{name}.yaml"
        if candidate.is_file():
            return candidate
    raise ActionLoadError(f"parent action {name!r} not found in {search_paths}")


def _deep_merge(parent: Dict[str, Any], child: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``child`` over ``parent`` recursively; child wins on scalars."""
    out = dict(parent)
    for key, value in child.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _resolve_extends(raw: Dict[str, Any], search_paths: List[Path], seen: set) -> Dict[str, Any]:
    parent_name = raw.get("extends")
    if not parent_name:
        return raw
    if parent_name in seen:
        raise ActionLoadError(f"circular 'extends' involving {parent_name!r}")
    seen.add(parent_name)
    parent_raw = _read_yaml(_find_action_file(parent_name, search_paths))
    parent_raw = _resolve_extends(parent_raw, search_paths, seen)
    merged = _deep_merge(parent_raw, raw)
    merged.pop("extends", None)
    # The merged action keeps the child's own name, not the parent's.
    merged["name"] = raw.get("name", parent_raw.get("name"))
    return merged


def _validate(raw: Dict[str, Any]) -> _ActionModel:
    try:
        return _ActionModel.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise ActionSchemaError(f"invalid action at '{loc}': {first['msg']}") from exc


# -- buffer construction ------------------------------------------------------

def _override_from_param(model: _ParameterModel) -> Dict[str, Any]:
    """Turn a validated parameter model into a build_buffer override spec.

    Only the fields the YAML author actually wrote are emitted, so a block that
    sets just ``value:`` never resets the command's declared ``type``/``hide``/…
    back to their schema defaults. A ``value: {from: "..."}`` mapping becomes an
    OutputRef kept unresolved.
    """
    spec: Dict[str, Any] = {}
    for field in model.model_fields_set:
        if field == "value":
            continue  # handled below (may need OutputRef parsing)
        spec[field] = getattr(model, field)
    if "value" in model.model_fields_set:
        value = model.value
        if isinstance(value, dict) and set(value.keys()) == {"from"}:
            spec["value"] = OutputRef.parse(value["from"])
        else:
            spec["value"] = value
    return spec


def build_action_buffer(model: _ActionModel) -> ActionBuffer:
    """Build the runtime ActionBuffer from a validated action model."""
    action = ActionBuffer(name=model.name, shelf=model.shelf, thumbnail=model.thumbnail)
    for step_name, step_model in model.steps.items():
        step = StepBuffer(name=step_name, index=step_model.index)
        for cmd_name, cmd_model in step_model.commands.items():
            command_cls: type[CommandBase] = get_command(cmd_model.command)
            overrides = {p: _override_from_param(pm) for p, pm in cmd_model.parameters.items()}
            step.commands[cmd_name] = command_cls.build_buffer(cmd_name, overrides)
        action.steps[step_name] = step
    return action


def load_action(source: Path, search_paths: Optional[List[Path]] = None) -> ActionBuffer:
    """Load, validate and resolve an action file into a ready ActionBuffer.

    ``search_paths`` is where parent actions named by ``extends`` are looked up;
    it defaults to the folder containing ``source``.
    """
    source = Path(source)
    if search_paths is None:
        search_paths = [source.parent]
    raw = _read_yaml(source)
    raw = _resolve_extends(raw, search_paths, seen=set())
    model = _validate(raw)
    return build_action_buffer(model)
