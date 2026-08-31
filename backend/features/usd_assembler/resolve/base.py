# base.py — resolver abstraction. Pure python (no pxr): turns a pipeline identity
# (asset + symbolic version) into a resolved, frozen USD path.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ResolvedAsset:
    """A pipeline identity frozen to a concrete published USD file.

    *path* is the resolved layer file, *default_prim* its root prim name (target
    of references/payloads), *version* the concrete version label (never
    "latest" — resolution freezes it for determinism).
    """

    path: Path
    default_prim: str
    version: str


@runtime_checkable
class AssetResolver(Protocol):
    """Resolve an asset identity to a published USD file.

    Implementations must be deterministic and must raise (never silently fall
    back) when nothing is published for the requested identity.
    """

    def resolve(
        self, asset: str, version: str = "latest", dept: str | None = None
    ) -> ResolvedAsset:
        ...


class ResolveError(RuntimeError):
    """Raised when an asset identity cannot be resolved to a published file."""
