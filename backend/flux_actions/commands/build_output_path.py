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
    """Resolve the destination folder for a FLUX filename in the project."""

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
        project_path = Path(action_query.buffer.context["project_path"])
        filename: str = parameters["filename"]

        output_path = resolve_publish_path(project_path, filename)
        if output_path is None:
            raise ValueError(f"chemin de publication introuvable pour: {filename!r}")

        return {"output_path": output_path}
