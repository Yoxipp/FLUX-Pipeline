# build_output_path.py — resolve where a publish will land.
#
# Single responsibility: given a logical FLUX filename and the project context,
# return the destination folder. It reuses the existing token resolution
# (resolve_publish_path); it does not copy anything and does not re-implement
# path logic.
#
# The copy step (copy_publish) consumes this output_path directly, so the
# destination is resolved exactly once per publish and fed forward by reference.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register

from features.publisher.publish_core import resolve_publish_path


@register("build_output_path")
class BuildOutputPath(CommandBase):
    """Resolve the destination folder for a FLUX filename in the project.

    V5 storage frontier (Phase 1b, Unite 4): when a ``storage_root`` is configured,
    the destination is resolved through the ``StorageLocator`` (the single point
    that can send publishes to a NAS / synced folder). With no ``storage_root``
    (the default), the existing token resolution runs unchanged, byte-for-byte, so
    nothing moves until the maintainer sets a root.
    """
    doc_fr = "Trouve le dossier de destination d'un nom de fichier FLUX dans le projet (tokens)."

    # project_path comes from the production context snapshot, not from a param.
    required_metadata = ["project_path"]

    parameters = {
        "filename": {
            "type": "str",
            "label": "Nom du fichier",
            "hide": True,
        },
    }

    async def run(
        self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger
    ) -> Dict[str, Any]:
        from core import paths  # local: keep flux_core import direction one-way

        context = action_query.buffer.context
        project_path = Path(context["project_path"])
        filename: str = parameters["filename"]

        storage_root = paths.get_storage_root()
        if storage_root is not None:
            # Redirect mode: the StorageLocator owns the root; the project name
            # addresses it. project_name is in the run context; fall back to the
            # project folder name so this never needs a wider context.
            from core.repository_factory import get_storage

            project_name = context.get("project_name") or project_path.name
            try:
                output_path = Path(get_storage().resolve_dir(project_name, filename))
            except (ValueError, NotImplementedError) as exc:
                raise ValueError(
                    f"chemin de publication introuvable pour: {filename!r}"
                ) from exc
            return {"output_path": output_path}

        # Default: the existing token resolution, unchanged.
        output_path = resolve_publish_path(project_path, filename)
        if output_path is None:
            raise ValueError(f"chemin de publication introuvable pour: {filename!r}")

        return {"output_path": output_path}
