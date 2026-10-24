# contract.py — what a node body sees and returns (01_ARCHITECTURE §4, §5).
#
#   body(ctx, inputs, params) -> {port: value}
#   simulate(ctx, inputs, params) -> {"lines": [{kind, text_fr, path?}], "outputs": {...}}
#
# * ``inputs``: one value per input port: the linked value, else the literal of
#   ``params`` (the link wins), else the port default. Dynamic ports
#   (flux.legacy_command) appear the same way. ``params``: the node's raw params.
# * A body may be ``async def`` (runs on the loop: keep it short) or a plain
#   function (runs in the FLOWS pool, may block, tests ``ctx.cancelled``).
# * Branching: a body chooses its exec output with the key EXEC_KEY
#   (``{"_exec": "else"}``); default is ``then``.
# * Failure: raise NodeError (or any exception). The engine records the message
#   and the values received; ``on_error`` linked = error_handled.

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

EXEC_KEY = "_exec"


class NodeError(Exception):
    """A node failed in a way the artist can read. ``message`` is shown on the node."""

    def __init__(self, message: str, *, code: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class NodeContext:
    """Per node call view of a run. ``run`` is the engine's run (duck typed:
    tests may pass a stub with the same methods)."""

    def __init__(self, run: Any, node_id: str) -> None:
        self._run = run
        self.node_id = node_id

    # -- read only facts of the run ---------------------------------------------
    @property
    def run_id(self) -> str:
        return self._run.run_id

    @property
    def flow(self) -> str:
        return self._run.flow_name

    @property
    def mode(self) -> str:
        """``real`` or ``dry``."""
        return self._run.mode

    @property
    def dry(self) -> bool:
        return self._run.mode == "dry"

    @property
    def context(self) -> Dict[str, Any]:
        """project, project_path, user, host, date, time, flow, run_id (01 §11)."""
        return self._run.context

    @property
    def interface(self) -> Dict[str, Any]:
        """Values of the flow interface: defaults overridden by the trigger payload."""
        return self._run.interface

    @property
    def payload(self) -> Dict[str, Any]:
        """Payload of the event that started the run (empty for a manual run)."""
        return getattr(self._run, "payload", None) or {}

    @property
    def interface_types(self) -> Dict[str, str]:
        """Type of each interface input (str, path, dir...)."""
        return {i.id: i.type for i in self._run.flow.interface.inputs}

    @property
    def cancelled(self) -> threading.Event:
        return self._run.cancelled

    def resolve(self, text: Any, path_field: bool = False, extra: Optional[Dict[str, Any]] = None) -> Any:
        """The run's resolver ({token}, ${var}, $FLUX at the head of a path field);
        ``extra`` adds {keys} (data.template values)."""
        return self._run.resolve_text(text, path_field=path_field, extra=extra)

    # -- effects on the run -----------------------------------------------------
    def log(self, text: str, level: str = "info") -> None:
        self._run.node_log(self.node_id, level, text)

    def notify(self, text: str, level: str = "info", path: Optional[str] = None) -> None:
        """Toast in the FLUX windows connected to /flows/ws."""
        self._run.notify(self.node_id, level, text, path)

    def get_variable(self, name: str) -> Any:
        return self._run.get_variable(name)

    def set_variable(self, name: str, value: Any) -> Any:
        return self._run.set_variable(name, value)

    def add_cleanup(self, fn) -> None:
        """*fn()* runs at the end of the run, whatever its outcome (a headless session closes)."""
        self._run.add_cleanup(fn)

    # -- subflows (subflow.flow_call / flow_output) ------------------------------
    async def call_flow(self, name: str, version: Any, values: Dict[str, Any], flow: Any = None) -> Dict[str, Any]:
        """Run flow *name* inline (or the given *flow*: a DCC subflow node)."""
        return await self._run.call_flow(self.node_id, name, version, values, flow=flow)

    def set_output(self, ident: str, value: Any) -> None:
        self._run.set_output(ident, value)

    # -- dispatcher (ADR 0067) ------------------------------------------------------
    def dispatch_batch(self) -> Optional[Dict[str, Any]]:
        """The job of the innermost ForEach in mode dispatch ({"tasks": [...], title?, priority?}),
        else None. dispatcher.submit adds its tasks there; the engine sends it at ForEachEnd."""
        return self._run.dispatch_batch()
