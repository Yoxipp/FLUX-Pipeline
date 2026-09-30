# publishes.py - the publishes of a project between two dates, for the team calendar.
#
# 2026-09-30: a checkbox in the calendar shows every publish on its day (one band
# per day, unfolded into time / person / file). Read-only view of the activity log: the
# hot file plus the monthly archives of the months shown (the hot file is rotated).

from __future__ import annotations

from datetime import date

from core.constants import ARCHIVE_STEM_ACTIVITY
from core.logger import get_logger
from core.paths import get_activity_path, get_archive_path
from core.repository_factory import get_repository
from features.activity.activity_reader import get_all_events

log = get_logger(__name__)

_ARCHIVE_COLLECTION = "feed_archive"
MAX_DAYS = 400          # one calendar screen is 42 days; this only bounds a bad request


def _months(start: str, end: str) -> list[str]:
    """['202609', '202610'] for 2026-09-12 .. 2026-10-03."""
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _archived(start: str, end: str) -> list[dict]:
    repo = get_repository()
    events: list[dict] = []
    for yyyymm in _months(start, end):
        try:
            data = repo.get(_ARCHIVE_COLLECTION, str(get_archive_path(ARCHIVE_STEM_ACTIVITY, yyyymm)))
        except Exception as exc:  # noqa: BLE001 - an unreadable archive only hides old publishes
            log.warning("Calendar: archive %s unreadable: %s", yyyymm, exc)
            continue
        if isinstance(data, list):
            events.extend(data)
    return events


def publishes_between(project: str, start: str, end: str) -> list[dict]:
    """Publishes of *project* from *start* to *end* (YYYY-MM-DD, inclusive), oldest first:
    [{id, date, time, user, file, dest_folder}]. Raises ValueError on bad dates."""
    s, e = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    if e < s:
        s, e = e, s
    if (e - s).days > MAX_DAYS:
        raise ValueError(f"Plage trop longue (> {MAX_DAYS} jours)")
    start, end = s.isoformat(), e.isoformat()
    try:
        hot = get_all_events(limit=1_000_000, action="publish", project=project, path=get_activity_path())
    except RuntimeError:          # FLUX_ROOT not set yet
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for ev in hot + _archived(start, end):
        if ev.get("action") != "publish" or ev.get("project") != project:
            continue
        d = str(ev.get("date", ""))
        if not (start <= d <= end):
            continue
        key = str(ev.get("id") or (d, ev.get("time"), ev.get("user"), ev.get("file")))
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": key, "date": d, "time": ev.get("time", ""), "user": ev.get("user", ""),
                    "file": ev.get("file", ""), "dest_folder": ev.get("dest_folder", "")})
    out.sort(key=lambda p: (p["date"], p["time"]))
    return out
