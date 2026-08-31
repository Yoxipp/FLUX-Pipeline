# base.py — builder interface + the LayerContribution data it emits.
# Pure python, zero pxr: contributions are a description, not a stage mutation.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..resolve.base import ResolvedAsset

if TYPE_CHECKING:  # avoid import cycle at runtime
    from ..context import AssemblyContext
    from ..recipe.model import LayerSpec


class Arc(Enum):
    """A USD composition arc. The composer maps each to a concrete pxr call."""

    SUBLAYER = "sublayer"
    REFERENCE = "reference"
    PAYLOAD = "payload"
    VARIANT = "variant"
    OVER = "over"
    INHERIT = "inherit"


@dataclass(frozen=True)
class LayerContribution:
    """One unit of composition: *where* (prim_path), *how* (arc) and *what*
    (asset + opinions). Idempotent by construction — replaying yields the same
    stage edit.
    """

    prim_path: str
    arc: Arc
    asset: ResolvedAsset | None = None
    opinions: dict = field(default_factory=dict)


@runtime_checkable
class Builder(Protocol):
    """Transform a LayerSpec into composition contributions.

    A builder never touches a stage; it only describes contributions. It reads
    resolved paths through ``ctx.resolver`` and names through ``ctx.naming``.
    """

    kind: str

    def contribute(
        self, ctx: "AssemblyContext", spec: "LayerSpec"
    ) -> list[LayerContribution]:
        ...
