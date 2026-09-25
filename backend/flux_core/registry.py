# registry.py — stable-key command registry.
#
# Referencing commands by dotted import path (``pkg.mod.Class``) is fragile to
# renames and invisible to static analysis. Flux instead resolves a
# command by a stable string key set with the ``@register`` decorator. Renaming
# the class never changes the key, and every key is discoverable here.

from __future__ import annotations

from typing import Dict, Iterable, Tuple, Type

# key -> CommandBase subclass. Filled by the @register decorator at import time.
_REGISTRY: Dict[str, type] = {}


class CommandNotFound(KeyError):
    """Raised when an action references a command key that is not registered."""


def register(key: str):
    """Class decorator registering a command under a stable key.

    Usage::

        @register("build_output_path")
        class BuildOutputPath(CommandBase):
            ...
    """

    def _decorate(cls: type) -> type:
        if key in _REGISTRY and _REGISTRY[key] is not cls:
            raise ValueError(
                f"command key {key!r} already registered to {_REGISTRY[key]!r}"
            )
        cls.command_key = key
        _REGISTRY[key] = cls
        return cls

    return _decorate


def get_command(key: str) -> type:
    """Return the command class for ``key`` or raise CommandNotFound."""
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise CommandNotFound(f"no command registered under key {key!r}") from exc


def is_registered(key: str) -> bool:
    return key in _REGISTRY


def all_commands() -> Iterable[Tuple[str, type]]:
    """Iterate over ``(key, command_class)`` pairs, sorted by key."""
    return sorted(_REGISTRY.items())


def _clear_registry() -> None:
    """Test-only: empty the registry so a test can register throwaway commands."""
    _REGISTRY.clear()
