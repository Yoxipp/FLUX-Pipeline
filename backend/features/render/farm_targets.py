"""Farm targeting and throttling for Tractor jobs (pure functions, no Tractor import).

* Blade states from the bridge 'blades' verb: free / busy / nimby / offline.
* Machine targeting (list of PCs, room groups, team groups, exclusions) -> a Tractor
  service key expression. A blade name is a valid service key: validated on a real farm on
  2026-10-23 (echo job 34026, -service {<blade name>}, ran on that blade).
* "X % of the farm" -> a job maxactive (max chunks running at once, 1 slot per blade on that farm).
* No team cap: the engine's Shares (limits.config) share the farm between teams (2026-10-23).
* Rooms: only when the studio environment gives a room_pattern (studio_env), otherwise no grouping.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from features.render import studio_env

FLUX_HOST_TARGETING_VERIFIED = True
# Blade seen by the engine within this delay = alive (heartbeat every few minutes).
ALIVE_MINUTES = 15
SHARE_BASES = ("alive", "free")
_HOST = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
OTHER_GROUP = "autres"


def _heartbeat(value) -> Optional[datetime]:
    # Tractor: "2026-10-23 10:55:54.02258+02" (local engine time); the offset is ignored.
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})", str(value or ""))
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def room_of(name: str, pattern: str = "") -> str:
    """Room of a blade from the studio room_pattern. "" = no pattern (no grouping), OTHER_GROUP = no match."""
    if not pattern:
        return ""
    return studio_env.room_of(name, pattern) or OTHER_GROUP


def blade_state(blade: dict, now: Optional[datetime] = None) -> str:
    if blade.get("busy"):
        return "busy"
    seen = _heartbeat(blade.get("heartbeattime"))
    now = now or datetime.now()
    if seen is None or now - seen > timedelta(minutes=ALIVE_MINUTES):
        return "offline"
    if blade.get("nimby"):
        return "nimby"
    return "free"


def classify(blades: Iterable[dict], now: Optional[datetime] = None, room_pattern: str = "") -> List[dict]:
    """Blades sorted by name with state and room group (room "" when the studio has no room_pattern)."""
    out = []
    for b in blades:
        name = str(b.get("name") or "")
        if not name:
            continue
        busy = b.get("busy") or None
        out.append({"name": name, "state": blade_state(b, now), "room": room_of(name, room_pattern),
                    "slots": int(b.get("numslots") or 1), "nimby": str(b.get("nimby") or ""),
                    "job": busy.get("jid") if busy else None, "project": busy.get("project") if busy else None,
                    "heartbeat": str(b.get("heartbeattime") or "")})
    return sorted(out, key=lambda x: x["name"])


def counts(classified: Iterable[dict]) -> Dict[str, int]:
    c = {"free": 0, "busy": 0, "nimby": 0, "offline": 0}
    for b in classified:
        c[b["state"]] = c.get(b["state"], 0) + 1
    c["alive"] = c["free"] + c["busy"] + c["nimby"]
    return c


def rooms(classified: Iterable[dict]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for b in classified:
        if b["state"] != "offline" and b["room"]:
            groups.setdefault(b["room"], []).append(b["name"])
    return dict(sorted(groups.items()))


def check_host(name: str) -> str:
    if not _HOST.match(name or ""):
        raise ValueError(f"nom de machine invalide : '{name}'")
    return name


def resolve_hosts(hosts: Iterable[str], groups: Iterable[str], team_groups: Dict[str, List[str]],
                  room_groups: Dict[str, List[str]]) -> List[str]:
    """Picked PCs plus the PCs of the picked groups (team groups first, then rooms)."""
    out: List[str] = []
    for h in hosts:
        out.append(check_host(h))
    for g in groups:
        members = team_groups.get(g)
        if members is None:
            members = room_groups.get(g)
        if members is None:
            raise ValueError(f"groupe de machines inconnu : '{g}'")
        out.extend(check_host(h) for h in members)
    return sorted(set(out))


def service_expression(base: str, include: Iterable[str], exclude: Iterable[str]) -> str:
    """Tractor service key expression: base && (A || B) && !C."""
    inc = sorted({check_host(h) for h in include})
    exc = sorted({check_host(h) for h in exclude} - set(inc))
    parts = [f"({base})"] if base and (inc or exc) else ([base] if base else [])
    if inc:
        parts.append("(" + " || ".join(inc) + ")" if len(inc) > 1 else inc[0])
    parts += [f"!{h}" for h in exc]
    return " && ".join(parts)


def cap_from_percent(percent: int, base: str, farm_counts: Dict[str, int]) -> int:
    """maxactive for 'percent' of the alive (or currently free) blades. 0 = no cap. Never below 1."""
    if not percent:
        return 0
    if base not in SHARE_BASES:
        raise ValueError(f"base de pourcentage inconnue : '{base}' ({', '.join(SHARE_BASES)})")
    pool = farm_counts.get(base, 0)
    return max(1, math.floor(pool * percent / 100))


