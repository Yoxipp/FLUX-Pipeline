# scheduler.py — the background task of the Flows: active flows and their events
# (01_ARCHITECTURE §9; 00_LOGIQUE §4, n°2, n°22).
#
# start() in the lifespan of backend/main.py (in a try/except), stop() after its yield.
# FLUX_FLOWS_SCHEDULER=0 turns it off (read at start). Idle while FLUX_ROOT or the user
# is missing (first launch): checked again at each beat. No service: no FLUX open = no run.
#
# Main loop, one beat every BEAT_S (20 s):
#   * host lock election (hosts.py);
#   * active flows read again every REFRESH_S (60 s) and at each (de)activation
#     (request_refresh): team CONFIG/extensions/flows, every DOSSIER_PROJETS/*/_flux_setup/flows,
#     the perso flows of the local user. Each runs its ``active_version``;
#   * watchers (re)armed: global events (schedule, new_file, when) only on the lock
#     holder for team / project flows, always for perso flows; scene_opened is local
#     (one poller per soft); at most MAX_WATCHERS. on_publish listens to events.publish_done.
# Lock lost: global watchers disarmed, the global runs they started end ``interrupted``.
#
# schedule: the slot is noted in state.json (last_schedule {node: {slot, ran_at}}) BEFORE
# the run under the flow lock: a backend that sees it noted does not fire (idempotent).
# Only the last elapsed slot counts: missed slots fire once (catch_up_once) or are noted
# without firing (skip). Activation notes the last elapsed slot (no catch up before it).
# new_file: first scan = baseline (seen files kept in runs/<flow>/seen_<node>.json), one
# run per new file, size stable on 2 scans (wait_stable). when: the pure subgraph of
# ``condition`` is evaluated each tick; fires on false -> true, first value = baseline.

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from flux_flows import events, hosts, runs

log = logging.getLogger("flux.flows.scheduler")

SWITCH_ENV = "FLUX_FLOWS_SCHEDULER"
REFRESH_S = 60.0
MAX_WATCHERS = 50
SCHEDULE_TICK_S = 15.0
ON_TIME_S = 120.0          # a slot fired within 2 min of its time is not a catch up
MIN_EVERY_S = 5.0
MIN_SCENE_EVERY_S = 2.0
GLOBAL_EVENTS = ("event.schedule", "event.new_file", "event.when")
SCENE_OPENED = "event.scene_opened"
SCENE_SOFTS = {"maya": "Maya", "houdini": "Houdini"}
_FALSE = {"0", "false", "no", "off"}
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def enabled() -> bool:
    """False when FLUX_FLOWS_SCHEDULER is falsey."""
    return os.environ.get(SWITCH_ENV, "1").strip().lower() not in _FALSE


# -- schedule slots -------------------------------------------------------------------

def parse_days(value: Any) -> Set[int]:
    """'daily' / empty = every day; else names separated by commas or spaces."""
    text = str(value or "daily").strip().lower()
    if text in ("daily", "*", "all"):
        return set(range(7))
    out = set()
    for part in text.replace(",", " ").split():
        if part not in DAY_NAMES:
            raise ValueError(part)
        out.add(DAY_NAMES.index(part))
    if not out:
        raise ValueError(text)
    return out


def parse_time(value: Any) -> Tuple[int, int]:
    text = str(value or "").strip()
    hh, sep, mm = text.partition(":")
    if not sep or not hh.isdigit() or not mm.isdigit() or len(mm) != 2:
        raise ValueError(text)
    h, m = int(hh), int(mm)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(text)
    return h, m


def schedule_param_error(name: str, value: Any) -> Optional[Tuple[str, str]]:
    """(fr, en) message when a Schedule param is invalid (validate.py), else None."""
    try:
        if name == "days":
            parse_days(value)
        elif name == "time":
            parse_time(value if value is not None else "08:00")
        elif name == "missed" and value not in (None, "", "catch_up_once", "skip"):
            return ("Creneau manque : catch_up_once ou skip", "Missed slot: catch_up_once or skip")
    except ValueError:
        if name == "days":
            return ("Jours : daily, ou mon,tue,wed,thu,fri,sat,sun", "Days: daily, or mon,tue,wed,thu,fri,sat,sun")
        return ("Heure attendue au format HH:MM (08:30)", "Time expected as HH:MM (08:30)")
    return None


def last_slot(now: datetime, days: Any, time_text: Any) -> Optional[datetime]:
    """Most recent slot <= *now* (None when the params are invalid)."""
    try:
        wanted, (h, m) = parse_days(days), parse_time(time_text or "08:00")
    except ValueError:
        return None
    for back in range(8):
        day = (now - timedelta(days=back)).replace(hour=h, minute=m, second=0, microsecond=0)
        if day <= now and day.weekday() in wanted:
            return day
    return None


def next_slot(now: datetime, days: Any, time_text: Any) -> Optional[datetime]:
    try:
        wanted, (h, m) = parse_days(days), parse_time(time_text or "08:00")
    except ValueError:
        return None
    for ahead in range(8):
        day = (now + timedelta(days=ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
        if day > now and day.weekday() in wanted:
            return day
    return None


def note_slot(root: Path, name: str, node: str, slot: datetime, *, ran: bool) -> bool:
    """Note *slot* for the Schedule *node* in state.json, unless this slot (or a later
    one) is already noted. True when this call noted it (= this backend fires)."""
    from flux_flows import store

    iso = slot.isoformat(timespec="seconds")

    def change(state: Dict[str, Any]) -> bool:
        noted = dict(state.get("last_schedule") or {})
        if str((noted.get(node) or {}).get("slot") or "") >= iso:
            return False
        noted[node] = {"slot": iso, "ran_at": datetime.now().isoformat(timespec="seconds") if ran else None}
        state["last_schedule"] = noted
        return True

    return store.update_state(root, name, change) is not None


def note_activation(root: Path, name: str, flow: Any, now: Optional[datetime] = None) -> None:
    """At activation: the last elapsed slot of each Schedule is noted (no catch up before)."""
    now = now or datetime.now()
    for nid, node in flow.nodes.items():
        if node.type == "event.schedule":
            slot = last_slot(now, node.params.get("days"), node.params.get("time"))
            if slot is not None:
                note_slot(root, name, nid, slot, ran=False)


# -- active flows ----------------------------------------------------------------------

@dataclass
class ActiveFlow:
    scope: str
    project: Optional[str]
    name: str
    version: int
    flow: Any
    root: Path

    @property
    def key(self) -> str:
        return f"{self.scope}|{self.project or ''}|{self.name}"


def scan_active(user: Optional[str]) -> List[ActiveFlow]:
    """Every active flow this backend may run (sync: call it in a thread)."""
    from flux_flows import locations, store

    folders: List[Tuple[str, Optional[str], Path]] = []
    try:
        folders.append(("team", None, locations.scope_dir("team")))
        if user:
            folders.append(("perso", None, locations.scope_dir("perso", user=user)))
        from core.constants import SETUP_DIR
        from core.paths import get_projects_dir

        projects = get_projects_dir()
        if projects.is_dir():
            for entry in sorted(projects.iterdir()):
                flows_dir = entry / SETUP_DIR / "flows"
                if entry.is_dir() and flows_dir.is_dir():
                    folders.append(("project", entry.name, flows_dir))
    except (RuntimeError, OSError) as exc:
        log.warning("active flows: %s", exc)
    found: List[ActiveFlow] = []
    for scope, project, root in folders:
        if not root.is_dir():
            continue
        for name, version in store.active_names(root):
            try:
                got = store.read_flow({scope: root}, scope, name, version)
            except Exception as exc:  # noqa: BLE001 - a broken flow never stops the others
                log.warning("active flow %s/%s v%s unreadable: %s", scope, name, version, exc)
                continue
            found.append(ActiveFlow(scope, project, name, version, got["flow"], root))
    return found


# -- watchers ----------------------------------------------------------------------------

@dataclass
class Watcher:
    key: str                       # <flow key>|<node id>
    kind: str                      # event type
    af: ActiveFlow
    node: str
    signature: str
    task: Optional[asyncio.Task] = None
    state: Dict[str, Any] = field(default_factory=dict)

    def info(self) -> Dict[str, Any]:
        return {"flow": self.af.name, "scope": self.af.scope, "project": self.af.project,
                "version": self.af.version, "node": self.node, "kind": self.kind,
                **{k: v for k, v in self.state.items() if k in ("next", "last_fire", "error", "folder")}}


def _every(params: Dict[str, Any], default: float, minimum: float) -> float:
    try:
        value = float(params.get("every_s") or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".seen_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def scan_folder(folder: Path, pattern: str, recursive: bool) -> Dict[str, int]:
    """{relative path: size} of the files of *folder* matching *pattern* (os.scandir)."""
    from flux_flows.patterns import mask

    out: Dict[str, int] = {}
    stack = [folder]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if recursive and not entry.name.startswith("."):
                        stack.append(Path(entry.path))
                elif entry.is_file():
                    out[str(Path(entry.path).relative_to(folder))] = entry.stat().st_size
            except OSError:
                continue
    names = list(out)
    keep = mask(pattern or "*", [Path(n).name for n in names])
    return {n: out[n] for n, k in zip(names, keep) if k}


# -- the scheduler -------------------------------------------------------------------------

class Scheduler:
    """One per backend. Everything injectable for the tests."""

    def __init__(self, *, user_fn: Optional[Callable[[], Optional[str]]] = None,
                 lock: Optional[hosts.HostLock] = None, scan_fn: Optional[Callable[..., List[ActiveFlow]]] = None,
                 now_fn: Callable[[], datetime] = datetime.now, beat_s: float = hosts.BEAT_S,
                 refresh_s: float = REFRESH_S, instances_fn: Optional[Callable[[str], List[dict]]] = None,
                 context_fn: Optional[Callable[[str, int], dict]] = None,
                 max_watchers: int = MAX_WATCHERS) -> None:
        self.user_fn = user_fn or _current_user
        self.lock = lock
        self.scan_fn = scan_fn or scan_active
        self.now_fn = now_fn
        self.beat_s, self.refresh_s = beat_s, refresh_s
        self.instances_fn = instances_fn or _scan_instances
        self.context_fn = context_fn or _instance_context
        self.max_watchers = max_watchers
        self.user: Optional[str] = None
        self.flows: List[ActiveFlow] = []
        self.watchers: Dict[str, Watcher] = {}
        self.skipped: List[str] = []              # watchers over the cap
        self.scene_pollers: Dict[str, asyncio.Task] = {}
        self.scene_state: Dict[str, Dict[str, Any]] = {}
        self.started_runs: Dict[str, Any] = {}    # run_id -> Run started by a global event
        self.running = False
        self.reason: Optional[str] = None          # why idle
        self._task: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()
        self._refresh_due = 0.0
        self._listener: Optional[tuple] = None

    # -- lifecycle -------------------------------------------------------------------
    def start(self) -> None:
        if self._task is None:
            self.running = True
            self._task = asyncio.get_running_loop().create_task(self._main())

    async def stop(self) -> None:
        self.running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except BaseException:   # noqa: BLE001 - cancelled, or the loop's last error
                pass
            self._task = None
        await self._disarm_all("arret du backend")
        if self._listener is not None:
            events.unlisten("publish_done", self._listener)
            self._listener = None
        if self.lock is not None:
            await asyncio.to_thread(self.lock.release)

    def request_refresh(self) -> None:
        """Read the active flows again now (activation, deactivation)."""
        self._refresh_due = 0.0
        self._wake.set()

    # -- main loop -----------------------------------------------------------------------
    def _ready(self) -> bool:
        from flux_flows import locations

        self.user = self.user_fn()
        if not self.user:
            self.reason = "pas d'utilisateur"
            return False
        try:
            locations.extensions_dir()
        except RuntimeError:
            self.reason = "FLUX_ROOT inconnu"
            return False
        self.reason = None
        return True

    async def _main(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                await self.beat(loop.time())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the scheduler never dies on one beat
                log.exception("scheduler beat failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), self.beat_s)
            except asyncio.TimeoutError:
                pass

    async def beat(self, now_m: float) -> None:
        """One step: election, then the active flows and the watchers if due."""
        if not self._ready():
            return
        if self.lock is None:
            path = hosts.lock_path()
            if path is None:
                return
            self.lock = hosts.HostLock(path, user=self.user)
        if self._listener is None:
            self._listener = events.listen("publish_done", self._on_publish)
        changed = await self.lock.tick()
        if changed:
            events.emit({"type": "host", **self.lock.info()})
            if not self.lock.holder:
                await self._interrupt_global("verrou perdu : un autre poste execute les flows actifs")
        if changed or now_m >= self._refresh_due:
            self._refresh_due = now_m + self.refresh_s
            await self.refresh()

    @property
    def holder(self) -> bool:
        return bool(self.lock and self.lock.holder)

    async def refresh(self) -> None:
        try:
            self.flows = await asyncio.to_thread(self.scan_fn, self.user)
        except Exception:  # noqa: BLE001
            log.exception("active flows unreadable")
            return
        await self._arm()

    # -- watchers --------------------------------------------------------------------------
    def _wanted(self) -> List[Watcher]:
        wanted: List[Watcher] = []
        for af in self.flows:
            for nid, node in af.flow.nodes.items():
                if node.bypass:
                    continue
                if node.type in GLOBAL_EVENTS and (af.scope == "perso" or self.holder):
                    pass
                elif node.type != SCENE_OPENED:
                    continue
                sig = json.dumps([af.version, node.type, node.params], sort_keys=True, default=str)
                wanted.append(Watcher(f"{af.key}|{nid}", node.type, af, nid, sig))
        return wanted

    async def _arm(self) -> None:
        wanted = self._wanted()
        self.skipped = [w.key for w in wanted[self.max_watchers:]]
        if self.skipped:
            log.warning("flows: %d surveillants au dela du plafond de %d ignores", len(self.skipped),
                        self.max_watchers)
        keep = {w.key: w for w in wanted[: self.max_watchers]}
        for key in [k for k in self.watchers if k not in keep or keep[k].signature != self.watchers[k].signature]:
            self._cancel(self.watchers.pop(key))
        for key, w in keep.items():
            if key in self.watchers:
                self.watchers[key].af = w.af     # same version and params: keep its state
                continue
            self.watchers[key] = w
            if w.kind != SCENE_OPENED:
                w.task = asyncio.get_running_loop().create_task(self._watch(w))
        self._arm_scene_pollers()

    def _cancel(self, w: Watcher) -> None:
        if w.task is not None:
            w.task.cancel()

    async def _disarm_all(self, reason: str) -> None:
        for w in list(self.watchers.values()):
            self._cancel(w)
        self.watchers.clear()
        for task in self.scene_pollers.values():
            task.cancel()
        self.scene_pollers.clear()
        await self._interrupt_global(reason)

    async def _interrupt_global(self, reason: str) -> None:
        for run in list(self.started_runs.values()):
            run.interrupt(reason)
        self.started_runs.clear()
        if not self.holder:
            for key in [k for k, w in self.watchers.items() if w.kind in GLOBAL_EVENTS and w.af.scope != "perso"]:
                self._cancel(self.watchers.pop(key))

    async def _watch(self, w: Watcher) -> None:
        body = {"event.schedule": self._watch_schedule, "event.new_file": self._watch_new_file,
                "event.when": self._watch_when}[w.kind]
        try:
            await body(w)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one watcher never takes the others down
            w.state["error"] = str(exc)
            log.exception("watcher %s stopped", w.key)

    # -- firing ------------------------------------------------------------------------------
    async def fire(self, af: ActiveFlow, nid: str, payload: Dict[str, Any], *, track: bool = False) -> Dict[str, Any]:
        """Start the active version of *af* from event *nid* with *payload*."""
        from flux_flows import engine

        folder = runs.runs_dir(af.scope, project=af.project, user=self.user)
        run = engine.Run(af.flow, scope=af.scope, project=af.project, user=self.user, version=af.version,
                         event=nid, payload=payload, folder=folder)
        record = await engine.manager().submit(run)
        if track and record["status"] in runs.LIVE_STATUSES and af.scope != "perso":
            self.started_runs[run.run_id] = run
            if run.task is not None:
                run.task.add_done_callback(lambda _t, rid=run.run_id: self.started_runs.pop(rid, None))
        return record

    async def _probe(self, af: ActiveFlow, nid: str) -> Dict[str, Any]:
        """Inputs of event *nid* evaluated from their pure sources (nothing runs)."""
        from flux_flows import engine

        probe = engine.Run(af.flow, scope=af.scope, project=af.project, user=self.user, mode="dry",
                           event=nid, folder=None, checked=False)
        return await probe.evaluate_inputs(nid)

    # -- event.schedule ------------------------------------------------------------------------
    async def schedule_tick(self, w: Watcher) -> Optional[Dict[str, Any]]:
        """Fire *w* if its last slot is not noted yet. Returns the run record, if any."""
        params = w.af.flow.nodes[w.node].params
        now = self.now_fn()
        w.state["next"] = (lambda s: s.isoformat(timespec="seconds") if s else None)(
            next_slot(now, params.get("days"), params.get("time")))
        slot = last_slot(now, params.get("days"), params.get("time"))
        if slot is None:
            return None
        missed = (now - slot).total_seconds() > ON_TIME_S
        skip = missed and str(params.get("missed") or "catch_up_once") == "skip"
        noted = await asyncio.to_thread(note_slot, w.af.root, w.af.name, w.node, slot, ran=not skip)
        if not noted or skip:
            return None
        w.state["last_fire"] = slot.isoformat(timespec="seconds")
        return await self.fire(w.af, w.node, {"fired_at": slot.isoformat(timespec="seconds"), "missed": missed},
                               track=True)

    async def _watch_schedule(self, w: Watcher) -> None:
        while True:
            await self.schedule_tick(w)
            await asyncio.sleep(SCHEDULE_TICK_S)

    # -- event.new_file --------------------------------------------------------------------------
    def _seen_path(self, w: Watcher) -> Optional[Path]:
        folder = runs.runs_dir(w.af.scope, project=w.af.project, user=self.user)
        return folder / w.af.name / f"seen_{w.node}.json" if folder is not None else None

    async def new_file_tick(self, w: Watcher) -> List[Dict[str, Any]]:
        """One scan. Returns the records of the runs started."""
        from core.executors import HEAVY

        inputs = await self._probe(w.af, w.node)
        folder = Path(str(inputs.get("folder") or ""))
        pattern = str(inputs.get("pattern") or "*")
        recursive = bool(inputs.get("recursive"))
        stable = inputs.get("wait_stable", True) is not False
        sig = f"{folder}|{pattern}|{recursive}"
        w.state["folder"] = str(folder)
        if not str(folder) or not folder.is_dir():
            w.state["error"] = f"dossier introuvable : {folder}"
            return []
        w.state.pop("error", None)
        loop = asyncio.get_running_loop()
        files = await loop.run_in_executor(HEAVY, scan_folder, folder, pattern, recursive)
        seen_path = self._seen_path(w)
        if "seen" not in w.state:   # from the file: files arrived while FLUX was closed fire now
            stored = None
            if seen_path is not None:
                try:
                    stored = json.loads(seen_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    stored = None
            if isinstance(stored, dict) and stored.get("sig") == sig and isinstance(stored.get("seen"), list):
                w.state["seen"], w.state["pending"] = set(stored["seen"]), {}
            else:                    # first scan = baseline, nothing fires
                w.state["seen"], w.state["pending"], w.state["sig"] = set(files), {}, sig
                await self._save_seen(seen_path, sig, w.state["seen"])
                return []
        seen: Set[str] = w.state["seen"]
        pending: Dict[str, int] = w.state["pending"]
        ready = []
        for rel, size in sorted(files.items()):
            if rel in seen:
                continue
            if not stable or pending.get(rel) == size:
                ready.append(rel)
                pending.pop(rel, None)
            else:
                pending[rel] = size
        for rel in list(pending):
            if rel not in files:
                pending.pop(rel)
        seen.intersection_update(files)     # a file deleted then dropped again fires again
        seen.update(ready)
        if ready:
            await self._save_seen(seen_path, sig, seen)
        started = []
        for rel in ready:
            path = folder / rel
            started.append(await self.fire(w.af, w.node, {"path": str(path)}, track=True))
            w.state["last_fire"] = str(path)
        return started

    async def _save_seen(self, path: Optional[Path], sig: str, seen: Set[str]) -> None:
        if path is None:
            return
        try:
            await asyncio.to_thread(_write_json, path, {"sig": sig, "seen": sorted(seen)})
        except OSError as exc:
            log.warning("seen files not saved (%s): %s", path, exc)

    async def _watch_new_file(self, w: Watcher) -> None:
        every = _every(w.af.flow.nodes[w.node].params, 30, MIN_EVERY_S)
        while True:
            try:
                await self.new_file_tick(w)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - logged, next tick tries again
                w.state["error"] = str(exc)
                log.warning("new_file %s: %s", w.key, exc)
            await asyncio.sleep(every)

    # -- event.when ---------------------------------------------------------------------------------
    async def when_tick(self, w: Watcher) -> Optional[Dict[str, Any]]:
        try:
            value = bool((await self._probe(w.af, w.node)).get("condition"))
        except Exception as exc:  # noqa: BLE001 - an error is logged, never fires
            w.state["error"] = str(exc)
            return None
        w.state.pop("error", None)
        previous = w.state.get("value")
        w.state["value"] = value
        if previous is False and value:
            w.state["last_fire"] = self.now_fn().isoformat(timespec="seconds")
            return await self.fire(w.af, w.node, {}, track=True)
        return None

    async def _watch_when(self, w: Watcher) -> None:
        every = _every(w.af.flow.nodes[w.node].params, 30, MIN_EVERY_S)
        while True:
            await self.when_tick(w)
            await asyncio.sleep(every)

    # -- event.scene_opened (local, one poller per soft) -----------------------------------------
    def scene_watchers(self, soft: str) -> List[Watcher]:
        return [w for w in self.watchers.values()
                if w.kind == SCENE_OPENED and str(w.af.flow.nodes[w.node].params.get("soft") or "maya") == soft]

    def _arm_scene_pollers(self) -> None:
        for soft in SCENE_SOFTS:
            wanted = bool(self.scene_watchers(soft))
            task = self.scene_pollers.get(soft)
            if wanted and task is None:
                self.scene_pollers[soft] = asyncio.get_running_loop().create_task(self._poll_scenes(soft))
            elif not wanted and task is not None:
                task.cancel()
                self.scene_pollers.pop(soft, None)
                self.scene_state.pop(soft, None)

    async def scene_tick(self, soft: str) -> List[Dict[str, Any]]:
        """One poll of every instance of *soft*. Returns the records of the runs started."""
        dcc = SCENE_SOFTS[soft]
        instances = await asyncio.to_thread(self.instances_fn, dcc)
        scenes: Dict[int, Tuple[str, Optional[int]]] = {}
        for inst in instances:
            ctx = await asyncio.to_thread(self.context_fn, dcc, int(inst["port"]))
            scenes[int(inst["port"])] = (str(ctx.get("scene") or ""), inst.get("pid"))
        state = self.scene_state.get(soft)
        self.scene_state[soft] = {port: scene for port, (scene, _pid) in scenes.items()}
        if state is None:   # first poll = baseline
            return []
        started = []
        for port, (scene, pid) in scenes.items():
            if scene and state.get(port) != scene:
                session = {"soft": soft, "port": port, "pid": pid}
                for w in self.scene_watchers(soft):
                    w.state["last_fire"] = scene
                    started.append(await self.fire(w.af, w.node, {"scene": scene, "soft": soft,
                                                                  "session": session}))
        return started

    async def _poll_scenes(self, soft: str) -> None:
        while True:
            try:
                await self.scene_tick(soft)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("scene_opened %s: %s", soft, exc)
            watchers = self.scene_watchers(soft)
            every = min((_every(w.af.flow.nodes[w.node].params, 5, MIN_SCENE_EVERY_S) for w in watchers),
                        default=5.0)
            await asyncio.sleep(every)

    # -- event.on_publish (local) -------------------------------------------------------------------
    def _on_publish(self, signal: Dict[str, Any]) -> None:
        """Listener of events.publish_done (on the loop): fire the matching OnPublish nodes."""
        from flux_flows import hooks

        try:
            matches = hooks.matching(self.flows, signal)
        except Exception:  # noqa: BLE001
            log.exception("on_publish matching failed")
            return
        for af, nid, payload in matches:
            asyncio.get_running_loop().create_task(self._fire_logged(af, nid, payload))

    async def _fire_logged(self, af: ActiveFlow, nid: str, payload: Dict[str, Any]) -> None:
        try:
            await self.fire(af, nid, payload)
        except Exception:  # noqa: BLE001
            log.exception("on_publish run of %s failed to start", af.key)

    # -- GET /flows/host -------------------------------------------------------------------------------
    def info(self) -> Dict[str, Any]:
        lock = self.lock.info() if self.lock is not None else {"holder": None, "me": None, "is_holder": False,
                                                               "since": None}
        return {**lock, "enabled": enabled(), "running": self.running, "idle_reason": self.reason,
                "active_flows": [{"flow": af.name, "scope": af.scope, "project": af.project, "version": af.version}
                                 for af in self.flows],
                "watchers": [w.info() for w in self.watchers.values()], "over_cap": self.skipped,
                "max_watchers": self.max_watchers}


def _current_user() -> Optional[str]:
    from core import config

    return config.get_current_user()


def _scan_instances(dcc: str) -> List[dict]:
    from core.dcc_instances import scan_instances

    return scan_instances(dcc)


def _instance_context(dcc: str, port: int) -> dict:
    from core.dcc_context import instance_context

    return instance_context(dcc, port)


# -- module singleton (main.py lifespan) -------------------------------------------------------------

_SCHEDULER: Optional[Scheduler] = None


def get() -> Optional[Scheduler]:
    return _SCHEDULER


def start() -> Optional[Scheduler]:
    """Called in the lifespan (inside a try/except). None when switched off."""
    global _SCHEDULER
    if not enabled():
        log.info("[FLUX] Flows scheduler off (%s=0)", SWITCH_ENV)
        return None
    if _SCHEDULER is None:
        _SCHEDULER = Scheduler()
    _SCHEDULER.start()
    return _SCHEDULER


async def stop() -> None:
    global _SCHEDULER
    if _SCHEDULER is not None:
        await _SCHEDULER.stop()
        _SCHEDULER = None


def request_refresh() -> None:
    if _SCHEDULER is not None:
        _SCHEDULER.request_refresh()
