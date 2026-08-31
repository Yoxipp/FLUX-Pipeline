# edit_target.py — own a shot's department sublayers and route each contribution
# to the layer it belongs to. The ONLY pxr use here is Sdf/Usd layer plumbing;
# the routing policy (which dept, what order) stays data-driven.

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Sdf, Usd

if TYPE_CHECKING:  # pragma: no cover
    pass


class EditTargetRouter:
    """Create and track a shot's department layers, and hand out edit targets.

    Department layers start life as anonymous Sdf layers stacked under the root
    (by identifier) so opinions authored into them compose live. ``finalize``
    then rewrites the root's ``subLayerPaths`` to the deterministic on-disk file
    names (strong→weak), decoupling in-memory authoring from the published paths.
    """

    def __init__(self, stage: "Usd.Stage") -> None:
        self._stage = stage
        self._root = stage.GetRootLayer()
        # dept -> (filename, Sdf.Layer), insertion-ordered as declared.
        self._departments: dict[str, tuple[str, "Sdf.Layer"]] = {}

    def add_department(self, dept: str, filename: str) -> "Sdf.Layer":
        """Create an anonymous layer for *dept* and stack it under the root."""
        layer = Sdf.Layer.CreateAnonymous(dept)
        self._root.subLayerPaths.append(layer.identifier)
        self._departments[dept] = (filename, layer)
        return layer

    def target_for(self, dept: str | None) -> "Usd.EditTarget":
        """Return the edit target for *dept* (the root layer when unset/unknown)."""
        entry = self._departments.get(dept) if dept else None
        layer = entry[1] if entry else self._root
        return Usd.EditTarget(layer)

    def root_target(self) -> "Usd.EditTarget":
        return Usd.EditTarget(self._root)

    def finalize(self, order: list[str]) -> None:
        """Rewrite the root sublayer stack to file names, strongest first.

        *order* is the department order strong→weak; only declared departments
        are emitted, so the published paths match what was actually authored.
        """
        present = [d for d in order if d in self._departments]
        self._root.subLayerPaths.clear()
        for dept in present:
            filename, _ = self._departments[dept]
            self._root.subLayerPaths.append(f"./{filename}")

    def department_layers(self) -> dict[str, tuple[str, "Sdf.Layer"]]:
        """Return {dept: (filename, layer)} for the writer/façade to publish."""
        return dict(self._departments)
