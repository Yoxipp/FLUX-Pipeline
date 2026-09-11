# status.py — execution status shared by every buffer in the action engine.
#
# A generic execution status model, independent of any DCC. A status is
# carried by parameters, commands, steps and the whole action so the UI can show
# progress and errors without the graph crashing.

from __future__ import annotations

from enum import Enum


class Status(str, Enum):
    """Lifecycle state of a buffer (parameter / command / step / action)."""

    WAITING = "waiting"        # not started yet
    PROCESSING = "processing"  # currently running
    VALID = "valid"            # parameters/context checked, ready or done ok
    INVALID = "invalid"        # a parameter failed to cast or is missing
    ERROR = "error"            # the command raised during execution
    COMPLETED = "completed"    # finished successfully

    def is_terminal(self) -> bool:
        """True when no further work is expected for this buffer."""
        return self in (Status.COMPLETED, Status.ERROR)
