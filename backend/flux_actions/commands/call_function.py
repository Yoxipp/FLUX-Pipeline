# call_function.py - any public function of the FLUX code as a node (B6, 2026-09-28).
#
# The Graph YAML editor offers every public function of backend/features, core and
# dcc (catalog.list_functions). Such a node is this command with ``function`` set to
# "package.module:name" and one parameter per argument of the function (YAML-only
# parameters, the engine accepts them). An argument left empty takes, in order, the
# action context value of the same name (project_path, user...), then its default.
# A dict result becomes the node outputs, anything else is the output "result".

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register


def resolve_function(ref: str):
    """"package.module:name" -> the function object (ValueError when not found)."""
    module_name, _, func_name = (ref or "").partition(":")
    if not module_name or not func_name or func_name.startswith("_"):
        raise ValueError(f"fonction invalide: {ref!r} (attendu package.module:nom)")
    func = getattr(importlib.import_module(module_name), func_name, None)
    if not callable(func):
        raise ValueError(f"fonction introuvable: {ref!r}")
    return func


def _coerce(value: Any, annotation: Any) -> Any:
    """A text typed in the graph becomes what the annotation asks (Path, int, float, bool)."""
    if not isinstance(value, str) or annotation is inspect.Parameter.empty:
        return value
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", str(annotation))
    try:
        if "Path" in text:
            return Path(value)
        if text.startswith("bool"):
            return value.strip().lower() in ("1", "true", "oui", "yes", "on")
        if text.startswith("int"):
            return int(value)
        if text.startswith("float"):
            return float(value)
    except ValueError:
        return value
    return value


@register("call_function")
class CallFunction(CommandBase):
    """Run one function of the FLUX code; its arguments are the node inputs."""

    parameters = {
        "function": {
            "type": "str",
            "label": "Fonction",
            "tooltip": "package.module:nom, choisie dans le catalogue",
        },
    }

    async def run(self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger) -> Dict[str, Any]:
        func = resolve_function(parameters.get("function", ""))
        context = getattr(action_query.buffer, "context", {}) or {}
        kwargs: Dict[str, Any] = {}
        for name, arg in inspect.signature(func).parameters.items():
            if arg.kind in (arg.VAR_POSITIONAL, arg.VAR_KEYWORD):
                continue
            value = parameters.get(name)
            if value is None and name in context:
                value = context[name]
            if value is not None:
                kwargs[name] = _coerce(value, arg.annotation)
        logger.info("call_function: %s(%s)", parameters["function"], ", ".join(kwargs))
        if inspect.iscoroutinefunction(func):
            result = await func(**kwargs)
        else:
            result = await asyncio.to_thread(func, **kwargs)
        if isinstance(result, dict) and all(isinstance(k, str) for k in result):
            return dict(result)
        return {"result": result}
