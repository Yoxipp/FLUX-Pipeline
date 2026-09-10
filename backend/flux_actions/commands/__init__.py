# flux_actions.commands — importing this package registers every command.
#
# The @register decorator only runs when the module defining a command is
# imported. The loader resolves command keys at buffer-build time, so this
# package must be imported before any action is loaded. Import it once (the
# runner does) and the whole command registry is populated.

from __future__ import annotations

from . import build_output_path, publish_file, select_publish  # noqa: F401

__all__ = ["select_publish", "build_output_path", "publish_file"]
