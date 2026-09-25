# parameters.py — parameter type system for the action engine.
#
# Each command declares typed parameters. A raw value coming from YAML or from
# the UI is cast to the declared type before execution. Casting is centralised
# here so every command validates the same way and the front can render a field
# per type without hardcoding anything.

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict


class ParameterCastError(ValueError):
    """Raised when a raw value cannot be cast to its declared parameter type."""


def _cast_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off", ""):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ParameterCastError(f"cannot cast {value!r} to bool")


def _cast_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ParameterCastError(f"cannot cast {value!r} to int") from exc


def _cast_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ParameterCastError(f"cannot cast {value!r} to float") from exc


def _cast_str(value: Any) -> str:
    if value is None:
        raise ParameterCastError("cannot cast None to str")
    return str(value)


def _cast_path(value: Any) -> Path:
    if value is None or value == "":
        raise ParameterCastError("cannot cast empty value to path")
    return Path(str(value))


def _cast_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, tuple):
        return list(value)
    raise ParameterCastError(f"cannot cast {value!r} to list")


def _cast_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    raise ParameterCastError(f"cannot cast {value!r} to dict")


# Registry of type name -> cast function. "select" and "path" behave like str at
# runtime; the extra name only tells the front which widget to render.
_CASTERS: Dict[str, Callable[[Any], Any]] = {
    "str": _cast_str,
    "text": _cast_str,
    "select": _cast_str,
    "int": _cast_int,
    "float": _cast_float,
    "bool": _cast_bool,
    "path": _cast_path,
    "list": _cast_list,
    "dict": _cast_dict,
    "any": lambda v: v,
}


def is_known_type(type_name: str) -> bool:
    """True when the given declared type has a registered caster."""
    return type_name in _CASTERS


def cast_value(type_name: str, value: Any) -> Any:
    """Cast ``value`` to ``type_name``; raise ParameterCastError on failure."""
    caster = _CASTERS.get(type_name)
    if caster is None:
        raise ParameterCastError(f"unknown parameter type {type_name!r}")
    return caster(value)
