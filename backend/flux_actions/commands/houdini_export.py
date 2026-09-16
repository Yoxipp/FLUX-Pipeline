# houdini_export.py — publish the open Houdini scene direct-to-dest (engine command).
#
# Single responsibility: cook the selected ROP straight into the resolved
# pipeline destination and return the published path. Unlike Maya, there is NO
# temp file and NO copy step: Houdini writes big caches (muscle sims) and copying
# them twice would be slow for nothing, so the cook targets the final path itself.
#
# The publish logic is NOT reimplemented here. This command dispatches to
# dcc.houdini.houdini_export.publish_houdini_rop, which already resolves the
# immutable vNNN path, sets the output parm on the ROP, cooks into it, derives LAST
# and logs — all over the HTTP client that runs on Houdini's main thread.
# Keeping that one block whole avoids double resolution and any drift from the
# legacy path (routers/dcc.py), which calls the same function.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register

from dcc.houdini.houdini_export import publish_houdini_rop


@register("houdini_export")
class HoudiniExport(CommandBase):
    """Cook the selected Houdini ROP straight into the resolved destination."""

    # project_path comes from the production context snapshot, not from a param.
    required_metadata = ["project_path"]

    parameters = {
        # FLUX stem (from select); publish_houdini_rop appends the extension itself.
        "base_name": {
            "type": "str",
            "label": "Nom de la scene",
            "hide": True,
        },
        # Dotted format (from select), selects the ROP output parameter.
        "extension": {
            "type": "str",
            "label": "Format",
            "hide": True,
        },
        # The node to cook (from select); None uses the selected node in Houdini.
        "rop_node_path": {
            "type": "str",
            "label": "Noeud ROP",
            "value": None,
            "hide": True,
        },
        # Single flat vNNN file vs a per-version frame sequence folder (from select).
        "is_sequence": {
            "type": "bool",
            "label": "Sequence",
            "value": False,
            "hide": True,
        },
        # Optional [start, end, step] for a frame-range cook.
        "frame_range": {
            "type": "list",
            "label": "Plage d'images",
            "value": None,
            "hide": True,
        },
        # Optional frame token width for sequences ($F4 -> 0001). None keeps the
        # publish block's own default, so the constant lives in one place only.
        "frame_padding": {
            "type": "int",
            "label": "Largeur du token image",
            "value": None,
            "hide": True,
        },
        # Optional per-format ROP options (see houdiniExportOptions.ts).
        "options": {
            "type": "dict",
            "label": "Options d'export",
            "value": None,
            "hide": True,
        },
        # Optional point-attribute filter: {"mode": "keep"|"remove", "names": [...]}.
        "attr_filter": {
            "type": "dict",
            "label": "Filtre d'attributs",
            "value": None,
            "hide": True,
        },
        # Free-text publish note, written to the modif log.
        "description": {
            "type": "str",
            "label": "Description",
            "value": "",
            "hide": True,
        },
    }

    async def run(
        self, parameters: Dict[str, Any], action_query: Any, logger: logging.Logger
    ) -> Dict[str, Any]:
        context = action_query.buffer.context
        project_path = Path(context["project_path"])
        user: str = str(context.get("user") or "")

        base_name: str = parameters["base_name"]
        extension: str = parameters["extension"]
        rop_node_path = parameters.get("rop_node_path")
        is_sequence: bool = bool(parameters.get("is_sequence"))
        options = parameters.get("options")
        attr_filter = parameters.get("attr_filter")
        description: str = parameters.get("description") or ""

        # Houdini frame ranges are (start, end, step); accept a 2- or 3-item list.
        frame_range = parameters.get("frame_range")
        fr: tuple[int, ...] | None = None
        if frame_range and len(frame_range) >= 2:
            fr = tuple(int(v) for v in frame_range)

        # Forward the padding only when the caller set one; None lets the publish
        # block apply its own default (FRAME_PADDING), keeping a single source.
        frame_padding = parameters.get("frame_padding")
        extra: Dict[str, Any] = {}
        if frame_padding is not None:
            extra["frame_padding"] = int(frame_padding)

        resp = publish_houdini_rop(
            project_path,
            base_name,
            extension,
            rop_node_path=rop_node_path,
            is_sequence=is_sequence,
            frame_range=fr,
            description=description,
            user=user,
            options=options,
            attr_filter=attr_filter,
            **extra,
        )
        if not resp.get("ok"):
            raise ValueError(f"publish Houdini echoue: {resp.get('error', 'inconnu')}")

        return {
            "dest_path": Path(resp["path"]),
            "version": resp.get("version"),
            "version_str": resp.get("version_str"),
            "rop_node": resp.get("rop_node"),
            "is_sequence": resp.get("is_sequence", is_sequence),
        }
