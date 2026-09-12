# client.py — connection check for Photoshop over COM (V6 B6).
#
# Photoshop is driven from outside via COM, so there is no socket/plugin: "connected"
# means Photoshop is running and COM answers. Lazy-imports the library so the backend
# runs without it (returns not-connected).

from __future__ import annotations

from core.logger import get_logger

log = get_logger(__name__)


def ping() -> dict:
    """Return {ok, version} when Photoshop is reachable over COM, else {ok: False}."""
    try:
        import photoshop.api as ps  # lazy: Windows + Photoshop only
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"photoshop-python-api indisponible: {exc}"}
    try:
        app = ps.Application()
        return {"ok": True, "version": str(getattr(app, "version", ""))}
    except Exception as exc:  # noqa: BLE001 - Photoshop not running
        return {"ok": False, "error": str(exc)}
