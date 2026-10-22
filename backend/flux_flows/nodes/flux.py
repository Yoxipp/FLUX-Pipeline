# flux.py — pipeline nodes (02_NODES §7). P2: notify, legacy_command.
#
# flux.legacy_command runs a v1 command (flux_core public API: get_command,
# cast_value) with a shim carrying ``.buffer.context``, the only part of the v1
# ActionQuery the commands read. flux_core itself is not modified. The command
# runs on its own event loop in a FLOWS pool thread: v1 commands block inside
# their ``async run``. Its dynamic ports come from ``params.ports`` (migration,
# 01 §15): inputs are v1 parameter names, outputs the keys it returns.

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict

from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

NOTIFY_LEVELS = ("info", "warn", "error")
NOTIFY_WHERE = ("toast", "activity", "both")


def _notify_args(inputs, params):
    text = inputs.get("text")
    if text is None or str(text) == "":
        raise NodeError("Notify attend `text` : relie un lien ou saisis un texte")
    level = params.get("level") or "info"
    where = params.get("where") or "toast"
    if level not in NOTIFY_LEVELS:
        raise NodeError(f"Niveau inconnu '{level}' ({', '.join(NOTIFY_LEVELS)})")
    if where not in NOTIFY_WHERE:
        raise NodeError(f"Destination inconnue '{where}' ({', '.join(NOTIFY_WHERE)})")
    path = inputs.get("path")
    return str(text), level, where, (str(path) if path else None)


def _simulate_notify(ctx, inputs, params):
    text, _level, where, path = _notify_args(inputs, params)
    lines = []
    if where in ("toast", "both"):
        lines.append({"kind": "notify", "text_fr": f"afficherait : {text}"})
    if where in ("activity", "both"):
        lines.append({"kind": "activity", "text_fr": f"ecrirait dans le fil Activite : {text}", "path": path})
    return {"lines": lines, "outputs": {}}


@flow_node("flux.notify", "Notify", icon="Bell",
           inputs=[port("exec", "exec", required=True),
                   port("text", "str", "Message", "Message", "Daily copie", required=True),
                   port("path", "path", "Chemin lie (optionnel)", "Related path (optional)")],
           outputs=[port("then", "exec"), port("on_error", "exec")],
           params=[port("level", "str", "info, warn ou error", "info, warn or error", "info", default="info"),
                   port("where", "str", "toast, activity ou both", "toast, activity or both", "toast",
                        default="toast")],
           effect=True, simulate=_simulate_notify, shelf=40, aliases=["toast", "message", "alerte"],
           doc_fr="Affiche un message dans FLUX (toast) et / ou le poste dans le fil Activite du projet.",
           doc_en="Shows a message in FLUX (toast) and / or posts it in the project Activity feed.")
def notify(ctx, inputs, params):
    text, level, where, path = _notify_args(inputs, params)
    if where in ("toast", "both"):
        ctx.notify(text, level, path)
    if where in ("activity", "both"):
        from features.activity.activity_writer import log_event

        project = ctx.context.get("project") or ""
        if not project:
            raise NodeError("Pas de projet : le fil Activite est celui d'un projet")
        if not log_event(ctx.context.get("user") or "unknown", "update", project, filename=text,
                         dest_folder=path):
            raise NodeError("Le fil Activite n'a pas pu etre ecrit")
    return {}


# -- legacy v1 command ----------------------------------------------------------

class _CtxLogger:
    """logging.Logger look-alike: v1 commands log into the node's log."""

    def __init__(self, ctx) -> None:
        self._ctx = ctx

    def _out(self, level: str, msg: Any, *args: Any) -> None:
        try:
            text = str(msg) % args if args else str(msg)
        except (TypeError, ValueError):
            text = " ".join(str(a) for a in (msg, *args))
        self._ctx.log(text, level)

    def debug(self, msg, *args, **kw):
        pass

    def info(self, msg, *args, **kw):
        self._out("info", msg, *args)

    def warning(self, msg, *args, **kw):
        self._out("warn", msg, *args)

    warn = warning

    def error(self, msg, *args, **kw):
        self._out("error", msg, *args)

    exception = error
    critical = error

    def log(self, level, msg, *args, **kw):
        self._out("info", msg, *args)


def _legacy_command(params):
    from flux_actions import commands  # noqa: F401 - registers the v1 commands
    from flux_core import CommandNotFound, get_command

    key = params.get("command") or ""
    try:
        return get_command(key)
    except CommandNotFound:
        raise NodeError(f"Commande v1 inconnue '{key}'") from None


def _legacy_values(cls, inputs, params) -> Dict[str, Any]:
    """v1 parameter values: declared defaults < params.params < linked inputs."""
    from flux_core import ParameterCastError, cast_value

    specs = cls.merged_parameters()
    literals = params.get("params") or {}
    linked = inputs.get("inputs") or {}
    if not isinstance(literals, dict) or not isinstance(linked, dict):
        raise NodeError("params et inputs de LegacyCommand sont des dictionnaires")
    names = set(specs) | set(literals) | set(linked) | {k for k in inputs if k not in ("exec", "inputs")}
    values: Dict[str, Any] = {}
    for name in sorted(names):
        raw = specs.get(name, {}).get("value")
        if name in literals:
            raw = literals[name]
        if name in linked:
            raw = linked[name]
        if inputs.get(name) is not None:
            raw = inputs[name]
        if raw is None:
            values[name] = None
            continue
        kind = specs.get(name, {}).get("type", "str")
        try:
            values[name] = cast_value(kind, raw)
        except ParameterCastError as exc:
            raise NodeError(f"Parametre `{name}` : {exc}") from None
    return values


def _legacy_context(ctx) -> Dict[str, Any]:
    c = dict(ctx.context)
    c.setdefault("project_name", c.get("project"))
    return c


def _simulate_legacy(ctx, inputs, params):
    key = params.get("command") or "?"
    return {"lines": [{"kind": "legacy", "text_fr": f"executerait la commande v1 `{key}` (non simulee)"}],
            "outputs": {"outputs": {}}}


@flow_node("flux.legacy_command", "LegacyCommand", icon="History",
           inputs=[port("exec", "exec", required=True),
                   port("inputs", "dict", "Valeurs des parametres v1", "v1 parameter values", {"source": "a.exr"})],
           outputs=[port("then", "exec"), port("on_error", "exec"),
                    port("outputs", "dict", "Sorties de la commande v1", "v1 command outputs")],
           params=[port("command", "str", "Cle de la commande v1", "v1 command key", "conform_texture", required=True),
                   port("params", "dict", "Valeurs fixes des parametres v1", "Fixed v1 parameter values")],
           destructive=True, simulate=_simulate_legacy, aliases=["v1", "commande", "legacy"],
           doc_fr="Execute une commande d'action v1 (flows migres). Effet inconnu : jamais lance en essai a blanc.",
           doc_en="Runs a v1 action command (migrated flows). Unknown effect: never run in a dry run.")
def legacy_command(ctx, inputs, params):
    cls = _legacy_command(params)
    values = _legacy_values(cls, inputs, params)
    logger = _CtxLogger(ctx)
    context = _legacy_context(ctx)
    if not cls.check_context_metadata(context, logger):
        raise NodeError(f"La commande `{cls.command_key}` demande : {', '.join(cls.required_metadata)}")
    shim = SimpleNamespace(buffer=SimpleNamespace(context=context))
    out = asyncio.run(cls().run(values, shim, logger)) or {}
    if not isinstance(out, dict):
        raise NodeError("La commande v1 n'a pas rendu de dictionnaire")
    return {**out, "outputs": dict(out)}
