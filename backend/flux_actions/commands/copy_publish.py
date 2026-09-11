# copy_publish.py — the copy half of a publish, reusing the legacy core.
#
# Single responsibility: archive the previous version, copy the source into the
# ALREADY-RESOLVED destination folder, and write the logs. It does not resolve
# the path: it consumes the folder that build_output_path produced. This is what
# removes the double resolution the Phase 1 publish_file command still had.
#
# Production context (project_path, user, project_name) comes from the action's
# context snapshot; the per-publish inputs arrive as parameters, most of them by
# named reference from the earlier select / resolve steps.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register

# Alias the reused function so the class name and the module stay unambiguous.
from features.publisher.publish_core import copy_publish as run_copy_publish


@register("copy_publish")
class CopyPublish(CommandBase):
    """Copy the selected file into the resolved folder, reusing the legacy core."""

    required_metadata = ["project_path", "user"]

    parameters = {
        "source_path": {
            "type": "path",
            "label": "Fichier source",
            "hide": True,
        },
        # The destination folder, fed by build_output_path (resolve step).
        "output_path": {
            "type": "path",
            "label": "Dossier de destination",
            "hide": True,
        },
        # The logical FLUX name, fed by select_publish; supplies the base name.
        "filename": {
            "type": "str",
            "label": "Nom du fichier",
            "hide": True,
        },
        "description": {
            "type": "str",
            "label": "Description",
            "value": "",
            "ask_user": True,
        },
    }

    async def run(
        self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger
    ) -> Dict[str, Any]:
        context = action_query.buffer.context
        project_path = Path(context["project_path"])
        user: str = context["user"]
        # Same fallback as the legacy publish_file: project_name or the folder name.
        project_name: str = context.get("project_name", "") or project_path.name

        source_path: Path = parameters["source_path"]
        output_path: Path = parameters["output_path"]
        filename: str = parameters["filename"]
        description: str = parameters.get("description") or ""

        # Exactly the copy half of the legacy publish; no logic duplicated here.
        dest = run_copy_publish(
            source_path,
            output_path,
            filename,
            description,
            user,
            project_name,
        )
        if dest is None:
            raise ValueError(f"publish echoue pour: {source_path}")

        return {"dest_path": dest}
