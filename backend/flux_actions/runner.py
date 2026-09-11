# runner.py — the opt-in entry point that runs a publish through the engine.
#
# This is the Phase 1 "switch": the legacy router path stays untouched and is
# still the default. run_publish_action reproduces that publish through the
# declarative action engine instead, so both can be compared and validated
# before anything is wired live.
#
# Phase 2 adds two read/preview helpers the generic front form consumes:
#   build_publish_form   -> the visible parameters the front renders as fields
#   preview_publish_action -> resolve the destination without copying anything
# Both reuse the same action and command graph; no logic is duplicated.

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from flux_core import ActionQuery, OutputRef, Status

# Importing the commands package populates the registry before the YAML loads.
from flux_actions import commands as _commands  # noqa: F401

# The bundled publish action shipped with Flux.
PUBLISH_ACTION = Path(__file__).parent / "config" / "publish.yml"

# The Maya scene publish action (select -> resolve -> export -> copy).
PUBLISH_MAYA_ACTION = Path(__file__).parent / "config" / "publish_maya.yml"

# The resolve step name inside publish.yml (last step of a preview run).
_RESOLVE_STEP = "resolve"


def _build_publish_query(
    project_path: Path,
    user: str,
    project_name: str,
    logger: Optional[logging.Logger],
    on_diff: Optional[Callable[[Dict[str, Any]], None]],
) -> ActionQuery:
    """Load publish.yml with the production context snapshot applied."""
    # Context is stored as plain strings so the buffers stay JSON-serialisable.
    context = {
        "project_path": str(project_path),
        "project_name": project_name,
        "user": user,
    }
    return ActionQuery.from_file(
        PUBLISH_ACTION, context=context, logger=logger, on_diff=on_diff
    )


def run_publish_action(
    source_path: Path,
    project_path: Path,
    description: str,
    user: str,
    project_name: str = "",
    target_name: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
    on_diff: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[Path]:
    """Publish a file via the action engine and return the destination path.

    Same inputs and same result as the legacy ``publish_file`` router call, but
    routed through ``publish.yml``. Returns the LAST path on success, else None.
    ``on_diff`` receives buffer diffs for a future front; it may be omitted.
    """
    query = _build_publish_query(project_path, user, project_name, logger, on_diff)

    # Feed the per-run inputs the action leaves open.
    query.set_parameter("select", "select", "source_path", str(source_path))
    if target_name is not None:
        query.set_parameter("select", "select", "target_name", target_name)
    query.set_parameter("publish", "publish", "description", description)

    status = asyncio.run(query.execute())
    if status is not Status.COMPLETED:
        return None

    dest = query.buffer.steps["publish"].commands["publish"].outputs.get("dest_path")
    return Path(dest) if dest is not None else None


def run_maya_publish_action(
    base_name: str,
    extension: str,
    scope: str,
    project_path: Path,
    description: str,
    user: str,
    project_name: str = "",
    port: Optional[int] = None,
    frame_range: Optional[List[int]] = None,
    options: Optional[Dict[str, Any]] = None,
    logger: Optional[logging.Logger] = None,
    on_diff: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[Path]:
    """Publish the open Maya scene via the action engine; return the dest path.

    Runs publish_maya.yml (select -> resolve -> export -> copy). The scene is
    exported to a temp file by the export step and copied by the same copy step
    the local publish uses. The temp export dir is always removed afterwards.
    Returns the LAST path on success, else None.
    """
    context = {
        "project_path": str(project_path),
        "project_name": project_name,
        "user": user,
    }
    query = ActionQuery.from_file(
        PUBLISH_MAYA_ACTION, context=context, logger=logger, on_diff=on_diff
    )

    query.set_parameter("select", "select", "base_name", base_name)
    query.set_parameter("select", "select", "extension", extension)
    query.set_parameter("select", "select", "scope", scope)
    if port is not None:
        query.set_parameter("export", "export", "port", port)
    if frame_range is not None:
        query.set_parameter("export", "export", "frame_range", frame_range)
    if options is not None:
        query.set_parameter("export", "export", "options", options)
    query.set_parameter("publish", "publish", "description", description)

    try:
        status = asyncio.run(query.execute())
        if status is not Status.COMPLETED:
            return None
        dest = query.buffer.steps["publish"].commands["publish"].outputs.get("dest_path")
        return Path(dest) if dest is not None else None
    finally:
        # The export step created a temp dir; remove it once the copy has read it.
        export_cmd = query.buffer.steps.get("export")
        if export_cmd is not None:
            export_dir = export_cmd.commands["export"].outputs.get("export_dir")
            if export_dir is not None:
                shutil.rmtree(export_dir, ignore_errors=True)


def build_publish_form() -> List[Dict[str, Any]]:
    """Return the user-facing fields of the publish action, in run order.

    The front renders this list directly: one field per entry, driven by the
    parameter's declared ``type``/``label`` with no per-feature form code. A
    parameter is a user field when it is not hidden and its value is not wired
    from another command's output (an OutputRef is machine-fed, never typed).
    """
    query = ActionQuery.from_file(PUBLISH_ACTION)
    fields: List[Dict[str, Any]] = []
    for step in query.buffer.ordered_steps():
        for cmd_name, cmd in step.commands.items():
            for param in cmd.parameters.values():
                if param.hide or isinstance(param.value, OutputRef):
                    continue
                data = param.serialize()
                # Address a field unambiguously: step / command / parameter.
                data["step"] = step.name
                data["command"] = cmd_name
                fields.append(data)
    return fields


def preview_publish_action(
    source_path: Path,
    project_path: Path,
    user: str,
    project_name: str = "",
    target_name: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> Optional[Path]:
    """Resolve where a publish would land, without copying anything.

    Runs the same graph as ``run_publish_action`` but stops after the resolve
    step, so this is the first real consumer of ``build_output_path``. Returns
    the destination folder, or None when the inputs do not resolve yet.
    """
    query = _build_publish_query(project_path, user, project_name, logger, None)

    query.set_parameter("select", "select", "source_path", str(source_path))
    if target_name is not None:
        query.set_parameter("select", "select", "target_name", target_name)

    status = asyncio.run(query.execute(stop_after=_RESOLVE_STEP))
    if status is not Status.COMPLETED:
        return None

    output_path = (
        query.buffer.steps[_RESOLVE_STEP].commands["output"].outputs.get("output_path")
    )
    return Path(output_path) if output_path is not None else None
