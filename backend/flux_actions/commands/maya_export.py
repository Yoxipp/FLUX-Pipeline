# maya_export.py — export the open Maya scene to a temp file (engine command).
#
# Single responsibility: run a Maya export and hand the produced file to the next
# step as source_path. It does NOT resolve the destination and does NOT copy: the
# copy step consumes this source_path together with the resolved output_path.
#
# The export logic itself is not reimplemented here. This command dispatches to
# dcc.maya.maya_export_client.run_maya_export, which drives the SAME
# run_publish_export the legacy publish endpoint uses, over the Maya commandPort.
#
# The produced file lives in a temp dir; the temp dir is returned as export_dir
# so the caller (runner) can delete it once the copy has read the bytes.

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register

from dcc.maya.maya_export_client import run_maya_export


@register("maya_export")
class MayaExport(CommandBase):
    """Export the open Maya scene/selection to a temp file, reusing the legacy core.
    Runs in the Maya the artist has open (commandPort bridge), not in a background mayapy."""
    doc_fr = 'Exporte la scene / selection Maya ouverte dans un fichier temporaire. Tourne dans le Maya ouvert (commandPort), pas dans un mayapy en arriere-plan.'

    parameters = {
        # Logical FLUX filename (from select), names the temp export file.
        "filename": {
            "type": "str",
            "label": "Nom du fichier",
            "hide": True,
        },
        # Dotted format (from select), selects the exporter.
        "extension": {
            "type": "str",
            "label": "Format",
            "hide": True,
        },
        # "scene" or "selection" (from select).
        "scope": {
            "type": "str",
            "label": "Portee",
            "hide": True,
        },
        # Optional Maya instance port; None uses the base commandPort.
        "port": {
            "type": "int",
            "label": "Port Maya",
            "value": None,
            "hide": True,
        },
        # Optional [start, end] or [start, end, step] for animated .abc / USD.
        "frame_range": {
            "type": "list",
            "label": "Plage d'images",
            "value": None,
            "hide": True,
        },
        # Optional per-format export options (see mayaExportOptions.ts).
        "options": {
            "type": "dict",
            "label": "Options d'export",
            "value": None,
            "hide": True,
        },
    }

    async def run(
        self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger
    ) -> Dict[str, Any]:
        filename: str = parameters["filename"]
        extension: str = parameters["extension"]
        scope: str = parameters.get("scope") or "scene"
        port = parameters.get("port")
        options = parameters.get("options")

        frame_range = parameters.get("frame_range")
        fr: tuple[float, ...] | None = None
        if frame_range and len(frame_range) >= 2:
            fr = tuple(float(v) for v in frame_range[:3])

        export_dir = Path(tempfile.mkdtemp(prefix="flux_maya_export_"))
        out_path = export_dir / filename

        exported, export_logs = run_maya_export(
            out_path,
            extension,
            scope,
            port=port,
            frame_range=fr,
            options=options,
        )
        if exported is None:
            # Nothing to keep; the caller only cleans a dir it knows about.
            raise ValueError(f"export Maya echoue pour: {filename}")

        return {
            "source_path": exported,
            "export_dir": export_dir,
            "export_logs": export_logs,
        }
