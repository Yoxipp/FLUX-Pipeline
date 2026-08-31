# routers/logs.py — in-memory log feed for the Flux UI console.

from __future__ import annotations

from fastapi import APIRouter, Query

from core.logger import clear_logs, get_recent_logs

router = APIRouter()


@router.get("")
def read_logs(
    after: int = Query(0, ge=0, description="Return only records with id greater than this"),
    level: str | None = Query(None, description="Minimum level name (DEBUG/INFO/WARNING/ERROR)"),
) -> dict:
    """Return buffered backend log records for the Flux console.

    The frontend polls with the highest id it already has (`after`) so each call
    only returns new lines.
    """
    return {"records": get_recent_logs(after=after, min_level=level)}


@router.delete("")
def purge_logs() -> dict:
    """Clear the in-memory log buffer (console 'Clear' button)."""
    clear_logs()
    return {"ok": True}
