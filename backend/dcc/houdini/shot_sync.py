"""
FLUX: push regenerated shot stages to the open Houdini sessions (P0, Houdini Work).

A Production edit (casting, frame range) regenerates the shot stage on disk, but a
FLUX Shot Import already open in Houdini keeps the range copied at resolve time and
USD keeps the layer cached. After the regeneration the backend asks every connected
Houdini (in-app server 48884..48891) to run ``refresh_from_flux`` on the FLUX Shot
nodes of those shots (range read from the new stage, layer reloaded).

Best effort: never raises, never blocks the Production save (run in a daemon thread).
"""

from __future__ import annotations

import threading
from typing import Callable, Iterable

from core.logger import get_logger

log = get_logger(__name__)

# The /run answers once every FLUX Shot is refreshed; a busy Houdini must not hold
# the notifier thread for the 600 s export budget.
RUN_TIMEOUT_S = 30.0


def build_refresh_code(project: str, shots: Iterable[tuple[str, str]]) -> str:
    """Python run inside Houdini. Old sessions whose served module predates
    ``refresh_from_flux`` reload it first (``_load`` from the HDA bootstrap)."""
    changed = [[str(seq), str(shot)] for seq, shot in shots]
    return f"""
import hou
_project = {project!r}
_changed = {changed!r}
result = []
_type = hou.lopNodeTypeCategory().nodeTypes().get("flux_shot")
for _node in (_type.instances() if _type is not None else ()):
    try:
        _mod = _node.hdaModule()
        if not hasattr(_mod, "refresh_from_flux") and hasattr(_mod, "_load"):
            _mod._load()
        _fn = getattr(_mod, "refresh_from_flux", None)
        _res = _fn(_node, _project, _changed) if _fn is not None else "old_module"
    except Exception as _exc:
        _res = "error: %s" % _exc
    if _res is not None:
        result.append([_node.path(), _res])
# A render Work (FLUX Work LOP) loaded on one of these sequences follows the Timeline:
# new shots get their block, ranges are pulled (features/houdini_work/render_sync.py).
_wtype = hou.lopNodeTypeCategory().nodeTypes().get("flux_work")
for _node in (_wtype.instances() if _wtype is not None else ()):
    try:
        _mod = _node.hdaModule()
        if not hasattr(_mod, "follow_timeline_from_flux") and hasattr(_mod, "_load"):
            _mod._load()
        _fn = getattr(_mod, "follow_timeline_from_flux", None)
        _res = _fn(_node, _project, _changed) if _fn is not None else "old_module"
    except Exception as _exc:
        _res = "error: %s" % _exc
    if _res is not None:
        result.append([_node.path(), _res])
"""


def _connected_ports() -> list[int]:
    from core.dcc_instances import scan_instances

    return [inst["port"] for inst in scan_instances("Houdini") if inst.get("connected")]


def notify_shot_stages(project: str, shots: Iterable[tuple[str, str]], *,
                       ports: Callable[[], list[int]] | None = None,
                       client_factory: Callable[[int], object] | None = None) -> dict[int, object]:
    """Ask every connected Houdini to follow the regenerated *shots*. Returns
    {port: run result} (an error dict for a session that did not answer)."""
    shots = [(seq, shot) for seq, shot in shots]
    if not shots:
        return {}
    if client_factory is None:
        from dcc.houdini.client import HoudiniClient
        client_factory = lambda port: HoudiniClient(port=port)  # noqa: E731
    code = build_refresh_code(project, shots)
    out: dict[int, object] = {}
    try:
        found = (ports or _connected_ports)()
    except Exception as exc:  # noqa: BLE001 — best effort
        log.warning("Houdini scan for shot stage sync failed: %s", exc)
        return out
    for port in found:
        try:
            res = client_factory(port).run(code, timeout=RUN_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — one bad session must not stop the others
            res = {"ok": False, "error": str(exc)}
        out[port] = res
        if isinstance(res, dict) and res.get("ok") is False:
            log.warning("Houdini :%s did not follow the new shot stages: %s", port, res.get("error"))
        else:
            log.info("Houdini :%s shot stage sync: %s", port, res.get("result") if isinstance(res, dict) else res)
    return out


def notify_shot_stages_async(project: str, shots: Iterable[tuple[str, str]]) -> threading.Thread | None:
    """Fire-and-forget variant used by the Production save."""
    shots = list(shots)
    if not shots:
        return None
    thread = threading.Thread(target=notify_shot_stages, args=(project, shots),
                              name="flux-houdini-shot-sync", daemon=True)
    thread.start()
    return thread
