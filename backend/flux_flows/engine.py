# engine.py — runs a Flow v2 (01_ARCHITECTURE §4, §5; 00_LOGIQUE §4, §14 n°1).
#
# Exec + data. One exec cursor follows the exec links (a link whose target port
# is ``exec``); when a node runs, each linked data input is PULLED:
#   * source without exec link in (pure node, or an ``exec?`` reader left out of
#     the chain): evaluated on demand, memoised per run and per loop turn;
#   * source already executed: its last outputs (those of the current loop turn);
#   * source in the exec chain but not executed yet: "donnee lue avant d'etre
#     produite"; a body node read after its End: refused (use End.results).
# Memo validity = the loop frames the value depends on are still the current
# ones, plus the variable write counter when a variable was read (01 §4).
#
# Blocks: ForEach, For, While (Begin / End paired by End.params.begin, BLOCK_ENDS);
# BreakLoop leaves the innermost loop; Sequence runs its outputs one after the
# other; If, Switch and any other branching node pick their exec output with the
# EXEC_KEY of their result. FlowCall runs another flow inline (child Run, depth 8).
# Params and unlinked literals go through resolver.py when the node runs; a
# value that came through a link is never resolved again (01 §11).
# Errors: on_error linked = error_handled (``error`` output, the flow follows it),
# else the run stops in ``error``. Timeouts: ``params.timeout_s``, 120 s (600 s for
# session / dcc nodes); a thread cannot be killed: abandoned, result ignored.
# Cancel: ``cancelled`` flag between nodes + CancelledError on the current await.
#
# Admission (RunManager): run_policy skip_if_running / queue (FIFO, 20 max per
# flow), 4 runs at once (propositions of 01 §4). Revalidation before the run is
# a minimal precheck until validate.py (P4): unknown node, missing event, V1 limits.
# Sync node bodies run in the FLOWS pool (core/executors.py), never on the loop.

from __future__ import annotations

import asyncio
import copy
import functools
import inspect
import logging
import socket
import threading
import time
import weakref
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flux_flows import events, resolver, runs
from flux_flows.model import SUBNET_TYPE, Flow
from flux_flows.nodes import registry
from flux_flows.nodes.contract import EXEC_KEY, NodeContext, NodeError
from flux_flows.nodes.data import cast_literal
from flux_flows.nodes.operator import (BLOCK_ENDS, BREAK_LOOP, CONDITION_KEY, FOR_BEGIN, FOREACH_BEGIN,
                                       ITEMS_KEY, LIMIT_KEY, SEQUENCE_KEY, WHILE_BEGIN)
from flux_flows.nodes.subflow import FLOW_CALL

log = logging.getLogger("flux.flows.engine")

DEFAULT_TIMEOUT_S = 120.0
DCC_TIMEOUT_S = 600.0
MAX_RUNNING = 4
MAX_QUEUE = 20
PUSH_TICK_S = 0.1          # node_state / link_value grouped: 10 pushes per second per run at most
WRITE_EVERY_S = 1.0        # record rewritten once per second at most
START_EVENTS = ("event.manual", "event.button")
DRY_LIMITS_FR = ("Essai a blanc : apres un effet simule, les lectures voient le disque reel ; "
                 "l'essai estime, il ne garantit pas.")

MAX_SUBFLOW_DEPTH = 8     # 01 §8, E_SUBFLOW_CYCLE beyond
END_TYPES = frozenset(BLOCK_ENDS.values())
_TEXT_TYPES = ("str", "path", "dir", "pattern", "any", "list[str]", "list[path]", "list[any]")

Frames = Tuple[Tuple[str, int], ...]


class _StopRun(Exception):
    def __init__(self, status: str, error: str) -> None:
        super().__init__(error)
        self.status, self.error = status, error


class _BreakLoop(Exception):
    """Raised by BreakLoop, caught by the innermost running loop."""


def _pool():
    from core.executors import FLOWS

    return FLOWS


def _message(exc: BaseException) -> str:
    if isinstance(exc, NodeError):
        return exc.message
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def base_context(user: Optional[str], project: Optional[str], flow: str, run_id: str) -> Dict[str, Any]:
    """Context keys of 01 §11 (date and time stable during the run)."""
    now = datetime.now()
    project_path = None
    if project:
        try:
            from core.paths import get_project_path

            project_path = str(get_project_path(project))
        except Exception:   # no FLUX_ROOT (tests, first launch)
            project_path = None
    return {"project": project, "project_path": project_path, "user": user, "host": socket.gethostname(),
            "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H-%M-%S"), "flow": flow, "run_id": run_id}


def precheck(flow: Flow, event: Optional[str], mode: str = "real",
             project: Optional[str] = None) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """(start event id, blocking issues): the validation of 01 §8 (P4). A type mismatch
    does not block a dry run (ADR 0058, 5); warnings never block."""
    from flux_flows import validate

    found = validate.validate(flow, validate.Env(project=project))
    issues: List[Dict[str, Any]] = [i.to_dict() for i in validate.errors(found, dry_run=mode == "dry")
                                    if i.code != "E_NO_EVENT"]
    event_ids = [nid for nid, n in flow.nodes.items() if n.type.startswith("event.")]
    if event is not None:
        if event not in event_ids:
            issues.append({"level": "error", "code": "E_NO_EVENT", "node": event, "port": None,
                           "message_fr": f"`{event}` n'est pas un node evenement de ce flow"})
            return None, issues
        return event, issues
    if not event_ids:
        issues.append({"level": "error", "code": "E_NO_EVENT", "node": None, "port": None,
                       "message_fr": "Ce flow n'a pas de node de depart"})
        return None, issues
    event_ids.sort(key=lambda nid: (flow.nodes[nid].type not in START_EVENTS, nid))
    return event_ids[0], issues


class Run:
    """One run of one flow. Created by RunManager.submit."""

    def __init__(self, flow: Flow, *, scope: str, project: Optional[str], user: Optional[str],
                 mode: str = "real", draft: bool = False, version: Optional[int] = None,
                 base_revision: Optional[int] = None, event: Optional[str] = None,
                 values: Optional[Dict[str, Any]] = None, folder=None,
                 context: Optional[Dict[str, Any]] = None, depth: int = 0,
                 call_stack: Tuple[str, ...] = (), flow_loader=None,
                 payload: Optional[Dict[str, Any]] = None, checked: bool = True) -> None:
        if mode not in ("real", "dry"):
            raise ValueError(f"mode inconnu '{mode}'")
        self.flow = flow
        self.flow_name = flow.name
        self.scope, self.project, self.user, self.mode = scope, project, user, mode
        self.folder = folder
        self.run_id = runs.make_run_id(user)
        self.cancelled = threading.Event()
        self.task: Optional[asyncio.Task] = None
        # checked=False: a probe of the scheduler (event inputs), never a real run.
        self.event_id, self.issues = precheck(flow, event, mode, project) if checked else (event, [])
        self.values = dict(values or {})
        # Payload of the event that started the run (scheduler, hooks: 01 §9), read by event nodes.
        self.payload = dict(payload or {})
        self.interrupted: Optional[str] = None   # reason when the scheduler stops the run (lock lost, stop)
        self.record = runs.new_record(run_id=self.run_id, flow=flow.name, scope=scope, project=project,
                                      version=version, draft=draft, mode=mode, user=user,
                                      base_revision=base_revision,
                                      trigger={"event": self.event_id, "values": self.values,
                                               **({"payload": {k: runs.preview(v) for k, v in self.payload.items()}}
                                                  if self.payload else {})})
        self.context = base_context(user, project, flow.name, self.run_id)
        if context:
            self.context.update(context)
        self.interface = {i.id: i.default for i in flow.interface.inputs}
        for key, val in self.values.items():
            if key in self.interface:
                self.interface[key] = val
        self._var_types = {v.name: v.type for v in flow.variables}
        self._variables = {v.name: v.default for v in flow.variables if v.default is not None}
        self._var_writes = 0
        self.depth, self.call_stack = depth, tuple(call_stack)
        self._flow_loader = flow_loader       # (name, version) -> Flow ; None = the store
        self._outputs: Dict[str, Any] = {}    # subflow.flow_output values
        self._loops = 0                       # loops running (BreakLoop outside one = error)
        self._stop: Optional[str] = None      # End the current chain stops at
        # Indexes of the top level network (a subnet does not run yet).
        self.nodes = flow.nodes
        self._exec_next: Dict[Tuple[str, str], str] = {}
        self._data_in: Dict[Tuple[str, str], Tuple[str, str]] = {}
        self._data_ports: Dict[str, List[str]] = defaultdict(list)
        self._exec_targets: set = set()
        for link in flow.links:
            src, sport = link.from_.split(".", 1)
            dst, dport = link.to.split(".", 1)
            if dport == "exec":
                self._exec_next.setdefault((src, sport), dst)    # one link per exec output (A3)
                self._exec_targets.add(dst)
            else:
                if (dst, dport) not in self._data_in:
                    self._data_ports[dst].append(dport)
                self._data_in[(dst, dport)] = (src, sport)
        self._frames: List[Tuple[str, int]] = []
        self._exec_out: Dict[str, Tuple[Frames, Dict[str, Any]]] = {}
        self._memo: Dict[str, Tuple[Frames, Optional[int], Dict[str, Any]]] = {}
        self._dep_stack: List[Dict[str, Any]] = []
        self._evaluating: set = set()
        self._lock = threading.Lock()
        self._pending: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._dirty = True
        self._t0 = 0.0
        self.record["nodes"] = {nid: {"state": "idle"} for nid in flow.nodes}
        if mode == "dry":
            self.record["report"].append({"node": None, "kind": "limits", "text_fr": DRY_LIMITS_FR})

    # -- record and push --------------------------------------------------------
    def _msg(self, kind: str, **fields: Any) -> Dict[str, Any]:
        return {"type": kind, "run_id": self.run_id, "flow": self.flow_name, **fields}

    def _node(self, nid: str) -> Dict[str, Any]:
        return self.record["nodes"].setdefault(nid, {"state": "idle"})

    def _set_state(self, nid: str, state: str, error: Optional[str] = None,
                   values: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            entry = self._node(nid)
            now = runs.now_iso()
            entry["state"] = state
            if state == "running":
                entry["started"] = now
                entry.pop("ended", None)
                entry["count"] = entry.get("count", 0) + 1
            else:
                entry["ended"] = now
            if error is not None:
                entry["error"] = error
            if values is not None:
                entry["values"] = {k: runs.preview(v) for k, v in values.items()}
            msg = self._msg("node_state", node=nid, state=state, started=entry.get("started"),
                            ended=entry.get("ended"), count=entry.get("count", 0))
            if error is not None:
                msg["error"] = error
            self._pending[("node", nid)] = msg
            self._dirty = True

    def _link_value(self, key: str, value: Any) -> None:
        with self._lock:
            entry = self.record["links"].setdefault(key, {"count": 0})
            entry["value"] = runs.clip_value(value)
            entry["count"] += 1
            self._pending[("link", key)] = self._msg("link_value", link=key, preview=runs.preview(value),
                                                    count=entry["count"])
            self._dirty = True

    def node_log(self, nid: str, level: str, text: str) -> None:
        line = {"at": runs.now_iso(), "level": level, "text": str(text)}
        with self._lock:
            runs.add_log(self._node(nid), line)
            self._dirty = True
        events.emit(self._msg("log", node=nid, level=level, text=str(text)))

    def notify(self, nid: str, level: str, text: str, path: Optional[str]) -> None:
        self.node_log(nid, level, f"notification : {text}")
        events.emit(self._msg("notify", node=nid, level=level, text=text, path=path, user=self.user))

    def _flush_pushes(self) -> None:
        with self._lock:
            pending, self._pending = list(self._pending.values()), {}
        for msg in pending:
            events.emit(msg)

    def _snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._dirty = False
            return copy.deepcopy(self.record)

    async def _write(self) -> None:
        if self.folder is None:
            self._dirty = False
            return
        snap = self._snapshot()
        try:
            await asyncio.to_thread(runs.write_record, self.folder, snap)
        except OSError as exc:
            log.warning("run %s: record not written: %s", self.run_id, exc)

    async def _ticker(self) -> None:
        last_write = time.monotonic()
        while True:
            await asyncio.sleep(PUSH_TICK_S)
            self._flush_pushes()
            if self._dirty and time.monotonic() - last_write >= WRITE_EVERY_S:
                last_write = time.monotonic()
                await self._write()

    # -- variables ---------------------------------------------------------------
    def get_variable(self, name: str) -> Any:
        if name not in self._var_types:
            raise NodeError(f"Variable inconnue `{name}` : declare-la dans le flow")
        self._note_dep((), True)
        if name not in self._variables:
            raise NodeError(f"La variable `{name}` est lue mais jamais ecrite")
        return self._variables[name]

    def set_variable(self, name: str, value: Any) -> Any:
        kind = self._var_types.get(name)
        if kind is None:
            raise NodeError(f"Variable inconnue `{name}` : declare-la dans le flow")
        converted = value if kind in ("any",) or kind.startswith("session") else cast_literal(
            "list" if kind.startswith("list[") else kind, value)
        self._variables[name] = converted
        self._var_writes += 1
        return converted

    # -- resolver (01 §11) ---------------------------------------------------------
    def _lookup_var(self, name: str) -> Any:
        """${name}: flow variable first, then interface value; KeyError if neither."""
        if name in self._var_types:
            return self.get_variable(name)
        if name in self.interface:
            return self.interface[name]
        raise KeyError(name)

    def resolve_text(self, text: Any, path_field: bool = False,
                     extra: Optional[Dict[str, Any]] = None) -> Any:
        context = {**self.context, **extra} if extra else self.context
        return resolver.resolve(text, context, self._lookup_var,
                                list(self._var_types) + list(self.interface), path_field=path_field)

    def _params(self, node, spec) -> Dict[str, Any]:
        """The node's params with their texts resolved (spec.raw names left as typed)."""
        kinds = {p.name: p.type for p in (*spec.params, *spec.inputs)}
        out: Dict[str, Any] = {}
        for key, val in node.params.items():
            kind = kinds.get(key, "any")
            if key in spec.raw or kind not in _TEXT_TYPES:
                out[key] = val
            elif isinstance(val, str):
                out[key] = self.resolve_text(val, path_field=kind in ("path", "dir"))
            elif isinstance(val, list) and kind.startswith("list[") and all(isinstance(v, str) for v in val):
                out[key] = [self.resolve_text(v, path_field=kind == "list[path]") for v in val]
            else:
                out[key] = val
        return out

    async def evaluate_inputs(self, nid: str) -> Dict[str, Any]:
        """Inputs of node *nid* pulled from their pure sources (event.when condition,
        event.new_file folder): the scheduler probes an event without running the flow."""
        node, spec = self._spec(nid)
        got: Dict[str, Any] = {}
        params = self._params(node, spec)
        await self._inputs(nid, node, spec, got, params)
        return {**params, **got}

    # -- subflows (02 §10) ---------------------------------------------------------
    def set_output(self, ident: str, value: Any) -> None:
        declared = {o.id for o in self.flow.interface.outputs}
        if ident not in declared:
            raise NodeError(f"La sortie `{ident}` n'est pas declaree dans interface.outputs du flow")
        self._outputs[ident] = value

    def _load_flow(self, name: str, version: Any) -> Flow:
        if self._flow_loader is not None:
            return self._flow_loader(name, version)
        from flux_flows import locations, store

        roots = locations.roots_for(user=self.user, project=self.project)
        scope = store.resolve(roots, name)
        if scope is None:
            raise NodeError(f"Flow `{name}` introuvable (perso, projet, equipe, livre)")
        number = None if version in (None, "", "current") else int(version)
        return store.read_flow(roots, scope, name, number)["flow"]

    async def call_flow(self, nid: str, name: str, version: Any, values: Dict[str, Any]) -> Dict[str, Any]:
        chain = self.call_stack + (self.flow_name,)
        if name in chain:
            raise NodeError(f"Sous-flow en boucle : {' > '.join(chain + (name,))}", code="E_SUBFLOW_CYCLE")
        if self.depth + 1 > MAX_SUBFLOW_DEPTH:
            raise NodeError(f"Plus de {MAX_SUBFLOW_DEPTH} sous-flows imbriques", code="E_SUBFLOW_CYCLE")
        try:
            flow = await asyncio.to_thread(self._load_flow, name, version)
        except NodeError:
            raise
        except Exception as exc:
            raise NodeError(f"Flow `{name}` illisible : {_message(exc)}") from None
        manual = sorted(nid_ for nid_, n in flow.nodes.items() if n.type == "event.manual")
        if not manual:
            raise NodeError(f"Le flow `{name}` n'a pas de node Manual : il ne peut pas etre appele")
        context = {k: v for k, v in self.context.items() if k not in ("flow", "run_id")}
        child = Run(flow, scope=self.scope, project=self.project, user=self.user, mode=self.mode,
                    event=manual[0], values=values, folder=None, context=context, depth=self.depth + 1,
                    call_stack=chain, flow_loader=self._flow_loader)
        child.cancelled = self.cancelled
        errors = [i for i in child.issues if i.get("level") == "error"]
        if errors:
            raise NodeError(f"Le flow `{name}` a des erreurs : {errors[0]['message_fr']}")
        self.node_log(nid, "info", f"appelle {name} (run {child.run_id})")
        try:
            await child._chain(child.event_id)
        except _StopRun as stop:
            raise NodeError(f"sous-flow {name} : {stop.error}") from None
        finally:
            for line in child.record["report"]:
                if line.get("kind") != "limits":
                    self.record["report"].append({**line, "node": f"{nid}/{line.get('node')}"})
        return {"run_id": child.run_id, **child._outputs}

    # -- memo dependencies -------------------------------------------------------
    def _note_dep(self, frames: Frames, reads_vars: bool) -> None:
        if not self._dep_stack:
            return
        top = self._dep_stack[-1]
        if len(frames) > len(top["frames"]):
            top["frames"] = frames
        top["vars"] = top["vars"] or reads_vars

    def _frames_valid(self, frames: Frames) -> bool:
        return tuple(self._frames[: len(frames)]) == frames

    # -- calling a body ------------------------------------------------------------
    def _spec(self, nid: str):
        node = self.nodes.get(nid)
        if node is None:
            raise NodeError(f"Le node `{nid}` n'existe pas")
        if node.type == SUBNET_TYPE:
            raise NodeError("Un subnet ne s'execute pas encore (P3)")
        spec = registry.get_node(node.type)
        if spec is None:
            raise NodeError(f"Le node `{node.type}` est introuvable ou casse")
        return node, spec

    def _timeout(self, node, spec) -> Optional[float]:
        raw = node.params.get("timeout_s")
        try:
            if raw is not None and float(raw) > 0:
                return float(raw)
        except (TypeError, ValueError):
            pass
        if spec.type == FLOW_CALL:
            return None     # the called flow's nodes have their own timeouts
        return DCC_TIMEOUT_S if spec.family in ("session", "dcc") else DEFAULT_TIMEOUT_S

    async def _invoke(self, nid: str, node, spec, inputs: Dict[str, Any],
                      params: Dict[str, Any]) -> Dict[str, Any]:
        ctx = NodeContext(self, nid)
        if self.mode == "dry" and spec.effect:
            fn = spec.simulate
        else:
            fn = spec.func
        timeout = self._timeout(node, spec)
        threaded = not inspect.iscoroutinefunction(fn)
        if threaded:
            loop = asyncio.get_running_loop()
            pending = loop.run_in_executor(_pool(), functools.partial(fn, ctx, inputs, dict(params)))
        else:
            pending = fn(ctx, inputs, dict(params))
        try:
            result = await asyncio.wait_for(pending, timeout)
        except asyncio.TimeoutError:
            if threaded:
                self.node_log(nid, "warn", "le thread du node est abandonne : son resultat sera ignore")
            raise NodeError(f"timeout ({timeout:g} s)") from None
        result = result or {}
        if not isinstance(result, dict):
            raise NodeError("le node n'a pas rendu de dictionnaire de sorties")
        if self.mode == "dry" and spec.effect:
            for line in result.get("lines") or []:
                self.record["report"].append({"node": nid, **line})
            if nid not in self.record["nodes_simulated"]:
                self.record["nodes_simulated"].append(nid)
            return dict(result.get("outputs") or {})
        return result

    async def _inputs(self, nid: str, node, spec, got: Dict[str, Any],
                      params: Dict[str, Any]) -> Dict[str, Any]:
        declared = {p.name: p for p in spec.inputs if p.type != "exec"}
        params_of = {p.name for p in spec.params}
        for name in list(declared) + [p for p in self._data_ports.get(nid, []) if p not in declared]:
            if (nid, name) in self._data_in:
                got[name] = await self._pull(nid, name)
                if name not in declared and name in params_of:
                    params[name] = got[name]          # promoted param: the body reads params
            elif name in params:
                got[name] = params[name]
            else:
                got[name] = declared[name].default if name in declared else None
        for p in declared.values():
            if p.required and got.get(p.name) in (None, ""):
                raise NodeError(f"{spec.label} attend `{p.name}` : relie un lien ou saisis une valeur")
        return got

    # -- data -------------------------------------------------------------------------
    async def _pull(self, nid: str, port: str) -> Any:
        snode, sport = self._data_in[(nid, port)]
        outputs = await self._source_outputs(snode, nid)
        value = outputs.get(sport)
        self._link_value(f"{snode}.{sport}->{nid}.{port}", value)
        return value

    async def _source_outputs(self, snode: str, reader: str) -> Dict[str, Any]:
        if snode in self._exec_out:
            frames, outs = self._exec_out[snode]
            if not self._frames_valid(frames):
                raise NodeError(f"{reader} lit {snode}, d'un autre tour de boucle ou d'une boucle finie : "
                                "utilise results de End")
            self._note_dep(frames, False)
            return outs
        node, spec = self._spec(snode)
        if spec.family == "event":
            raise NodeError(f"{reader} lit l'evenement {snode}, qui n'a pas declenche ce run")
        if snode in self._exec_targets:
            raise NodeError(f"{reader} lit {snode}, qui n'est pas execute avant lui (donnee lue avant d'etre produite)")
        return await self._eval_pure(snode, node, spec)

    async def _eval_pure(self, nid: str, node, spec) -> Dict[str, Any]:
        if node.bypass:
            return {}
        memo = self._memo.get(nid)
        if memo is not None:
            frames, var_count, outs = memo
            if self._frames_valid(frames) and (var_count is None or var_count == self._var_writes):
                self._note_dep(frames, var_count is not None)
                return outs
        if nid in self._evaluating:
            raise NodeError(f"Boucle de liens data autour de {nid}")
        self._evaluating.add(nid)
        self._dep_stack.append({"frames": (), "vars": False})
        self._set_state(nid, "running")
        got: Dict[str, Any] = {}
        try:
            params = self._params(node, spec)
            await self._inputs(nid, node, spec, got, params)
            outs = await self._invoke(nid, node, spec, got, params)
        except asyncio.CancelledError:
            self._set_state(nid, "cancelled")
            raise
        except Exception as exc:
            msg = _message(exc)
            self._set_state(nid, "error", msg, got)
            raise NodeError(f"{nid} a echoue : {msg}") from None
        finally:
            self._evaluating.discard(nid)
            dep = self._dep_stack.pop()
        self._memo[nid] = (dep["frames"], self._var_writes if dep["vars"] else None, outs)
        self._note_dep(dep["frames"], dep["vars"])
        self._set_state(nid, "ok")
        return outs

    # -- exec -------------------------------------------------------------------------
    def _check_cancel(self) -> None:
        if self.cancelled.is_set():
            raise asyncio.CancelledError()

    async def _chain(self, start: Optional[str], stop_at: Optional[str] = None) -> None:
        seen: set = set()
        current = start
        saved, self._stop = self._stop, stop_at
        try:
            while current is not None and current != stop_at:
                if current in seen:
                    raise _StopRun("error", f"{current} : boucle de liens exec hors d'un bloc")
                seen.add(current)
                self._check_cancel()
                current = await self._exec_node(current)
        finally:
            self._stop = saved

    def _fail(self, nid: str, exc: BaseException, got: Dict[str, Any]) -> Optional[str]:
        msg = _message(exc)
        handler = self._exec_next.get((nid, "on_error"))
        if handler is not None:
            self._set_state(nid, "error_handled", msg, got)
            self._exec_out[nid] = (tuple(self._frames), {"error": msg})
            self.node_log(nid, "error", f"erreur geree : {msg}")
            return handler
        self._set_state(nid, "error", msg, got)
        self.node_log(nid, "error", msg)
        raise _StopRun("error", f"{nid} : {msg}")

    async def _exec_node(self, nid: str) -> Optional[str]:
        got: Dict[str, Any] = {}
        try:
            node, spec = self._spec(nid)
        except NodeError as exc:
            self._set_state(nid, "running")
            return self._fail(nid, exc, got)
        if node.bypass:
            self._set_state(nid, "skipped")
            self._exec_out[nid] = (tuple(self._frames), {})
            return self._exec_next.get((nid, "then"))
        if node.type in END_TYPES:
            self._set_state(nid, "running")
            return self._fail(nid, NodeError(f"{spec.label} atteint hors de sa boucle"), got)
        self._set_state(nid, "running")
        try:
            params = self._params(node, spec)
            await self._inputs(nid, node, spec, got, params)
            outs = await self._invoke(nid, node, spec, got, params)
        except asyncio.CancelledError:
            self._set_state(nid, "cancelled")
            raise
        except Exception as exc:
            return self._fail(nid, exc, got)
        branch = outs.pop(EXEC_KEY, None) or "then"
        if node.type in BLOCK_ENDS:
            return await self._loop(nid, node, outs, got)
        if node.type == BREAK_LOOP:
            if not self._loops:
                return self._fail(nid, NodeError("BreakLoop hors d'une boucle"), got)
            self._set_state(nid, "ok")
            raise _BreakLoop()
        sequence = outs.pop(SEQUENCE_KEY, None)
        self._exec_out[nid] = (tuple(self._frames), outs)
        self._set_state(nid, "ok")
        if sequence is not None:
            # operator.sequence: each output in order, one after the other (A3).
            for out_port in sequence:
                nxt = self._exec_next.get((nid, out_port))
                if nxt is not None:
                    await self._chain(nxt, stop_at=self._stop)
            return None
        return self._exec_next.get((nid, branch))

    def _end_of(self, begin: str, begin_type: str) -> Optional[str]:
        end_type = BLOCK_ENDS[begin_type]
        ends = sorted(nid for nid, n in self.nodes.items()
                      if n.type == end_type and n.params.get("begin") == begin)
        return ends[0] if ends else None

    async def _condition(self, bid: str, node) -> bool:
        if (bid, "condition") in self._data_in:
            value = await self._pull(bid, "condition")
        else:
            value = node.params.get("condition")
        if not isinstance(value, bool):
            raise NodeError(f"While attend un booleen, recu {value!r} : utilise Compare")
        return value

    async def _loop(self, bid: str, node, outs: Dict[str, Any], got: Dict[str, Any]) -> Optional[str]:
        """ForEach, For and While blocks: body = chain from ``loop`` up to the End."""
        kind = node.type
        end = self._end_of(bid, kind)
        if end is None:
            return self._fail(bid, NodeError(f"Le bloc {bid} n'a pas de End"), got)
        body = self._exec_next.get((bid, "loop"))
        items: List[Any] = outs.pop(ITEMS_KEY, None) or []
        cond = bool(outs.pop(CONDITION_KEY, False))
        limit = int(outs.pop(LIMIT_KEY, 0) or 0)
        collect = kind == FOREACH_BEGIN and (end, "collect") in self._data_in
        results: List[Any] = []
        if kind != WHILE_BEGIN:
            self.node_log(bid, "info", f"{len(items)} tour(s)")
        index = 0
        self._loops += 1
        try:
            while True:
                if kind == WHILE_BEGIN:
                    if not cond:
                        break
                    if self.mode == "dry" and index >= 1:   # 02 §5: evaluated once, never loops
                        self.record["report"].append({"node": bid, "kind": "loop",
                                                      "text_fr": "essai a blanc : un seul tour du While"})
                        break
                    if index >= limit:
                        return self._fail(bid, NodeError(
                            f"While : {limit} tours sans sortie (max_iterations) : la condition reste vraie"), got)
                    turn: Dict[str, Any] = {"index": index}
                elif index >= len(items):
                    break
                elif kind == FOR_BEGIN:
                    turn = {"index": items[index]}
                else:
                    turn = {"item": items[index], "index": index, "count": len(items)}
                self._check_cancel()
                self._frames.append((bid, index))
                broke = False
                try:
                    self._exec_out[bid] = (tuple(self._frames), turn)
                    try:
                        if body is not None and body != end:
                            await self._chain(body, stop_at=end)
                    except _BreakLoop:
                        broke = True
                        self.node_log(bid, "info", f"BreakLoop au tour {index}")
                    if not broke:
                        try:
                            if collect:
                                results.append(await self._pull(end, "collect"))
                            if kind == WHILE_BEGIN:
                                cond = await self._condition(bid, node)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            self._set_state(end, "running")
                            return self._fail(end, exc, {})
                finally:
                    self._frames.pop()
                index += 1
                if broke:
                    break
        finally:
            self._loops -= 1
        final = {"count": len(items)} if kind == FOREACH_BEGIN else {"index": index}
        self._exec_out[bid] = (tuple(self._frames), final)
        self._set_state(bid, "ok")
        self._set_state(end, "running")
        self._exec_out[end] = (tuple(self._frames), {"results": results} if kind == FOREACH_BEGIN else {})
        self._set_state(end, "ok")
        return self._exec_next.get((end, "done"))

    # -- lifecycle --------------------------------------------------------------------
    def _close(self, status: str, error: Optional[str] = None) -> None:
        with self._lock:
            self.record["status"] = status
            self.record["error"] = error
            self.record["ended"] = runs.now_iso()
            if self._t0:
                self.record["duration_ms"] = int((time.monotonic() - self._t0) * 1000)
            self._dirty = True

    def _finished_msg(self) -> Dict[str, Any]:
        return self._msg("run_finished", status=self.record["status"], duration_ms=self.record["duration_ms"],
                         error=self.record["error"], mode=self.mode)

    async def refuse(self, status: str, error: str) -> None:
        """Close a run that never started (refused, skipped)."""
        self.record["issues"] = self.issues
        self._close(status, error)
        await self._write()
        events.emit(self._finished_msg())

    async def execute(self) -> None:
        self._t0 = time.monotonic()
        with self._lock:
            self.record["status"] = "running"
            self.record["started"] = runs.now_iso()
        events.emit(self._msg("run_started", scope=self.scope, mode=self.mode, user=self.user,
                              trigger=self.record["trigger"], version=self.record["version"],
                              draft=self.record["draft"]))
        await self._write()
        ticker = asyncio.create_task(self._ticker())
        status, error = "ok", None
        try:
            await self._chain(self.event_id)
        except _StopRun as stop:
            status, error = stop.status, stop.error
        except asyncio.CancelledError:
            status, error = ("interrupted", self.interrupted) if self.interrupted else ("cancelled", "annule")
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            with self._lock:
                for entry in self.record["nodes"].values():
                    if entry.get("state") == "running":
                        entry["state"] = "cancelled"
        except Exception as exc:   # engine bug: the run reports it, the backend lives on
            log.exception("run %s crashed", self.run_id)
            status, error = "error", f"erreur interne du moteur : {_message(exc)}"
        finally:
            ticker.cancel()
            self._close(status, error)
            self._flush_pushes()
            await self._write()
            events.emit(self._finished_msg())

    def stop_reason(self) -> Tuple[str, str]:
        """(status, error) of a run stopped before its start."""
        return ("interrupted", self.interrupted) if self.interrupted else ("cancelled", "annule avant le depart")

    def interrupt(self, reason: str) -> None:
        """Stop the run as ``interrupted`` (host lock lost, backend stop: 01 §9)."""
        self.interrupted = reason
        self.cancel()

    def cancel(self) -> None:
        self.cancelled.set()
        if self.task is not None and not self.task.done():
            self.task.cancel()


class RunManager:
    """Admission and concurrency of the runs of one event loop."""

    def __init__(self, max_running: int = MAX_RUNNING, max_queue: int = MAX_QUEUE) -> None:
        self.max_queue = max_queue
        self._slots = asyncio.Semaphore(max_running)
        self._flow_locks: Dict[str, asyncio.Lock] = {}
        self._by_flow: Dict[str, List[Run]] = defaultdict(list)
        self.live: Dict[str, Run] = {}
        self.finished: Dict[str, Dict[str, Any]] = {}   # recent records, for runs without a folder

    @staticmethod
    def _key(run: Run) -> str:
        return f"{run.scope}|{run.project or ''}|{run.flow_name}"

    async def submit(self, run: Run) -> Dict[str, Any]:
        """Admit *run*: refused / skipped records are closed at once, else it is queued."""
        if run.event_id is None or any(i.get("level") == "error" for i in run.issues):
            await run.refuse("refused", "le flow a des erreurs")
            self._remember(run)
            return run.record
        key = self._key(run)
        busy = self._by_flow[key]
        if busy and (run.flow.run_policy == "skip_if_running" or len(busy) > self.max_queue):
            why = "deja en cours (run_policy skip_if_running)" if run.flow.run_policy == "skip_if_running" \
                else f"file pleine ({self.max_queue} runs en attente)"
            await run.refuse("skipped", why)
            self._remember(run)
            return run.record
        busy.append(run)
        self.live[run.run_id] = run
        run.task = asyncio.create_task(self._drive(run, key))
        return run.record

    async def _drive(self, run: Run, key: str) -> None:
        lock = self._flow_locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                async with self._slots:
                    if run.cancelled.is_set():
                        await run.refuse(*run.stop_reason())
                    else:
                        await run.execute()
        except asyncio.CancelledError:    # cancelled while queued
            await run.refuse(*run.stop_reason())
        finally:
            if run in self._by_flow[key]:
                self._by_flow[key].remove(run)
            self.live.pop(run.run_id, None)
            self._remember(run)
            if run.folder is not None:
                try:
                    await asyncio.to_thread(runs.purge, run.folder, run.flow_name)
                except OSError:
                    pass

    def _remember(self, run: Run) -> None:
        self.finished[run.run_id] = run.record
        while len(self.finished) > 100:
            self.finished.pop(next(iter(self.finished)))

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = self.live.get(run_id)
        if run is not None:
            with run._lock:
                return copy.deepcopy(run.record)
        return self.finished.get(run_id)

    def run(self, run_id: str) -> Optional[Run]:
        return self.live.get(run_id)

    def cancel(self, run_id: str) -> Optional[str]:
        run = self.live.get(run_id)
        if run is None or run.record["status"] not in runs.LIVE_STATUSES:
            return None
        run.cancel()
        return "cancelling"

    def running(self) -> List[Dict[str, Any]]:
        return [runs.summary(r.record) for r in self.live.values()]

    async def wait(self, run_id: str) -> Dict[str, Any]:
        """Wait for a run to close (tests)."""
        run = self.live.get(run_id)
        if run is not None and run.task is not None:
            await asyncio.shield(run.task)
        return self.get(run_id) or {}


_MANAGERS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, RunManager]" = weakref.WeakKeyDictionary()


def manager() -> RunManager:
    """The RunManager of the running loop (one backend = one loop; tests get one per loop)."""
    loop = asyncio.get_running_loop()
    mgr = _MANAGERS.get(loop)
    if mgr is None:
        mgr = _MANAGERS[loop] = RunManager()
    return mgr
