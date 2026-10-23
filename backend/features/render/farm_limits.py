"""Farm Shares from the engine's limits.config (read only, FLUX never writes it).

The school sets the teams and their share of the farm once a year in limits.config (Tractor Limits,
"Shares" per limit tag: nominal = fair share, cap = max part of the farm). Tractor balances the
teams itself at each dispatch, nothing killed. A job whose Tractor project is not one of the
Shares falls in "default" (cap 0.1 at school on 2026-10-23): FLUX only warns about that.

The engine serves its config files over HTTP (as it does for the blades):
http://<engine>/Tractor/config?file=limits.config (read at school on 2026-10-23).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from typing import Dict, Optional

# FLUX runs husk on the blades: its commands count in the "husk" limit (implicit tag = application name).
RENDER_TAG = "husk"
DEFAULT_SHARE = "default"
_TTL_S = 600.0        # set once a year: one read per 10 min is plenty
_FAIL_TTL_S = 60.0    # engine down: do not retry on every call
_TIMEOUT_S = 3.0
_cache: Dict[str, dict] = {}
_lock = threading.Lock()


def config_url(engine: str) -> Optional[str]:
    """http://host[:port]/Tractor/config?file=limits.config, None without an engine."""
    engine = (engine or "").strip()
    if not engine:
        return None
    if not re.match(r"^[A-Za-z0-9_.-]+(:\d{1,5})?$", engine):
        return None
    return f"http://{engine}/Tractor/config?file=limits.config"


def _strip_comments(text: str) -> str:
    # Tractor's config is JSON with '#' and '//' comment lines and the odd trailing comma.
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", "//"))]
    return re.sub(r",(\s*[}\]])", r"\1", "\n".join(lines))


def parse_shares(text: str) -> Dict[str, Dict[str, dict]]:
    """{limit tag: {team: {"nominal": float, "cap": float}}} for every limit that has Shares."""
    try:
        data = json.loads(_strip_comments(text))
    except ValueError:
        return {}
    limits = data.get("Limits") if isinstance(data, dict) else None
    out: Dict[str, Dict[str, dict]] = {}
    for tag, spec in (limits or {}).items():
        shares = spec.get("Shares") if isinstance(spec, dict) else None
        if not isinstance(shares, dict):
            continue
        out[tag] = {team: {"nominal": _num(v.get("nominal")), "cap": _num(v.get("cap"))}
                    for team, v in shares.items() if isinstance(v, dict)}
    return out


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_shares(engine: str) -> Optional[Dict[str, Dict[str, dict]]]:
    """Shares of the engine, cached. None = unknown (no engine, unreachable, unreadable)."""
    url = config_url(engine)
    if url is None:
        return None
    with _lock:
        hit = _cache.get(url)
        if hit and time.time() - hit["at"] < (_TTL_S if hit["shares"] is not None else _FAIL_TTL_S):
            return hit["shares"]
    shares = None
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as resp:  # read only GET on the school engine
            shares = parse_shares(resp.read().decode("utf-8", errors="replace")) or None
    except (OSError, ValueError):
        shares = None
    with _lock:
        _cache[url] = {"at": time.time(), "shares": shares}
    return shares


def teams(shares: Optional[Dict[str, Dict[str, dict]]], tag: str = RENDER_TAG) -> list:
    """Team names of the render tag (the Shares of FLUX's commands), 'default' excluded."""
    return sorted(t for t in ((shares or {}).get(tag) or {}) if t != DEFAULT_SHARE)


def team_warning(team: str, shares: Optional[Dict[str, Dict[str, dict]]], tag: str = RENDER_TAG) -> Optional[str]:
    """Warning when the team is not one of the Shares of FLUX's commands. None = fine or unknown."""
    by_team = (shares or {}).get(tag)
    if not by_team or team in by_team:
        return None
    names = teams(shares, tag)
    close = next((n for n in names if n.lower() == (team or "").lower()), None)
    if close:
        return (f"Equipe sur la farm '{team}' : la farm attend '{close}' (majuscules comprises). "
                f"Sinon les rendus passent dans '{DEFAULT_SHARE}'.")
    cap = (by_team.get(DEFAULT_SHARE) or {}).get("cap")
    limit = f", plafonnee a {round(cap * 100)} % de la farm" if cap is not None else ""
    return (f"Equipe sur la farm '{team}' inconnue de la farm (limits.config : {', '.join(names)}). "
            f"Les rendus passent dans la part '{DEFAULT_SHARE}'{limit}.")
