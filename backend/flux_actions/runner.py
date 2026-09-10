# runner.py — the opt-in entry point that runs a publish through the engine.
#
# This is the Phase 1 "switch": the legacy router path stays untouched and is
# still the default. run_publish_action reproduces that publish through the
# declarative action engine instead, so both can be compared and validated
# before anything is wired live.

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from flux_core import ActionQuery, Status

# Importing the commands package populates the registry before the YAML loads.
from flux_actions import commands as _commands  # noqa: F401

# The bundled publish action shipped with Flux.
PUBLISH_ACTION = Path(__file__).parent / "config" / "publish.yml"


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
    # Context is stored as plain strings so the buffers stay JSON-serialisable.
    context = {
        "project_path": str(project_path),
        "project_name": project_name,
        "user": user,
    }

    query = ActionQuery.from_file(
        PUBLISH_ACTION, context=context, logger=logger, on_diff=on_diff
    )

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
