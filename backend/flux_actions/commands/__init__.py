# flux_actions.commands — importing this package registers every command.
#
# The @register decorator only runs when the module defining a command is
# imported. The loader resolves command keys at buffer-build time, so this
# package must be imported before any action is loaded. Import it once (the
# runner does) and the whole command registry is populated.

from __future__ import annotations

from . import (  # noqa: F401
    build_output_path,
    copy_publish,
    maya_export,
    publish_file,
    select_dcc_publish,
    select_publish,
)

__all__ = [
    "select_publish",
    "select_dcc_publish",
    "build_output_path",
    "maya_export",
    "copy_publish",
    "publish_file",
]
