"""Farm targeting and throttling for Tractor jobs (pure functions, no Tractor import).

* Blade states from the bridge 'blades' verb: free / busy / nimby / offline.
* Machine targeting (list of PCs, room groups, team groups, exclusions) -> a Tractor
  service key expression. A blade name is a valid service key: validated at school on
  2026-10-23 (echo job 34026, -service {ROOM0321}, ran on ROOM0321).
* "X % of the farm" -> a job maxactive (max chunks running at once, 1 slot per blade at school).
* Team cap: one budget shared by every FLUX job of the team, split into per-job maxactive.
  Deterministic, so every FLUX window of the team computes the same split.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

FLUX_HOST_TARGETING_VERIFIED = True
# Blade seen by the engine within this delay = alive (heartbeat every few minutes).
ALIVE_MINUTES = 15
SHARE_BASES = ("alive", "free")
_HOST = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# School names: TLSS + 2 digit room + desk (ROOM1720 = room 17, ROOM17PROF = teacher desk), confirmed by 2026-10-23.
_ROOM = re.compile(r"^([A-Za-z]+)(\d{2})[A-Za-z0-9]+$")
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


def room_of(name: str) -> str:
    m = _ROOM.match(name or "")
    return f"{m.group(1).upper()}{m.group(2)}" if m else OTHER_GROUP


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


def classify(blades: Iterable[dict], now: Optional[datetime] = None) -> List[dict]:
    """Blades sorted by name with state and room group."""
    out = []
    for b in blades:
        name = str(b.get("name") or "")
        if not name:
            continue
        busy = b.get("busy") or None
        out.append({"name": name, "state": blade_state(b, now), "room": room_of(name),
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
        if b["state"] != "offline":
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


def split_team_cap(cap: int, jobs: List[dict]) -> Dict[int, int]:
    """Share a team budget between its unfinished FLUX jobs: {jid: maxactive}.

    jobs: {"jid", "remaining" (tasks not done), "cap" (own job cap, 0 = none)}.
    Oldest jid first gets the remainder; every job keeps at least 1 so none starves.
    """
    live = sorted((j for j in jobs if j.get("remaining", 0) > 0), key=lambda j: j["jid"])
    if cap <= 0 or not live:
        return {}
    out: Dict[int, int] = {}
    budget = max(cap, len(live))
    pending = list(live)
    # Water filling: jobs that need less than an even share (remaining or own cap) release the rest.
    while pending:
        even = budget // len(pending)
        small = [j for j in pending if _need(j) <= even]
        if not small:
            extra = budget - even * len(pending)
            for i, j in enumerate(pending):
                out[j["jid"]] = max(1, even + (1 if i < extra else 0))
            break
        for j in small:
            out[j["jid"]] = max(1, _need(j))
            budget -= out[j["jid"]]
            pending.remove(j)
        budget = max(budget, len(pending))
    return out


def _need(job: dict) -> int:
    remaining = int(job.get("remaining") or 0)
    own = int(job.get("cap") or 0)
    return min(remaining, own) if own > 0 else remaining
