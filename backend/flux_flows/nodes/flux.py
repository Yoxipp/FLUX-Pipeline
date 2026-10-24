# flux.py — pipeline nodes (02_NODES §7). P2: notify, legacy_command. P3: the rest
# of the family (find_publishes ... refresh_shot_stage), refuse_publish is P8.
#
# flux.legacy_command runs a v1 command (flux_core public API: get_command,
# cast_value) with a shim carrying ``.buffer.context``, the only part of the v1
# ActionQuery the commands read. flux_core itself is not modified. The command
# runs on its own event loop in a FLOWS pool thread: v1 commands block inside
# their ``async run``. Its dynamic ports come from ``params.ports`` (migration,
# 01 §15): inputs are v1 parameter names, outputs the keys it returns.
#
# The P3 nodes reuse the v1 bodies the same way (_run_v1: usd_check, usd_flatten,
# refresh_*) or the v1 runner (publish, conform, proxy); v2 adds on top: never
# overwrite by default, containment of overwrite (common.check_destructive_target),
# a simulate() that writes nothing. publish_core is not touched (zone a risque).
#
# A publish record (type ``publish``) is a dict: path, dir, file, name, version,
# user, date, time, soft, type, ext. The activity log keeps neither soft, type nor
# version (02 §7 note 1): they are deduced from the file name and extension (V1).

from __future__ import annotations

import asyncio
import inspect
import re
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from flux_flows.nodes.common import (
    archive_into_project, archive_preview, as_bool, as_path, check_destructive_target,
)
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
           params=[port("level", "str", "info, warn ou error", "info, warn or error", "info", default="info",
                        choices=NOTIFY_LEVELS),
                   port("where", "str", "toast, activity ou both", "toast, activity or both", "toast",
                        default="toast", choices=NOTIFY_WHERE)],
           effect=True, simulate=_simulate_notify, shelf=40,
           aliases=["toast", "message", "alerte", "notification", "prevenir", "envoyer", "notifier"],
           doc_fr="Affiche un message dans FLUX (toast, seulement dans les fenetres FLUX du poste qui execute) et / "
                  "ou le poste dans le fil Activite du projet (vu par toute l'equipe : where activity ou both).",
           doc_en="Shows a message in FLUX (toast, only in the FLUX windows of the executing workstation) and / or "
                  "posts it in the project Activity feed (seen by the whole team: where activity or both).")
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


def _run_v1(ctx, key: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Run the v1 command *key* as the body of a v2 node (same shim as LegacyCommand)."""
    cls = _legacy_command({"command": key})
    shim = SimpleNamespace(buffer=SimpleNamespace(context=_legacy_context(ctx)))
    try:
        out = asyncio.run(cls().run(values, shim, _CtxLogger(ctx))) or {}
    except NodeError:
        raise
    except FileNotFoundError as exc:
        raise NodeError(f"{key} : introuvable ({exc.filename or exc})") from None
    except (ValueError, OSError, RuntimeError) as exc:
        raise NodeError(f"{key} : {exc}") from None
    return out if isinstance(out, dict) else {}


# -- P3 helpers -----------------------------------------------------------------

_EXEC = port("exec", "exec", required=True)
_EXITS = [port("then", "exec", "Suite si reussi", "Next step on success"),
          port("on_error", "exec", "Suite en cas d'erreur", "Next step on error")]
# ``exec?`` readers (02 §1): not linked, the node is pure; linked, it runs there.
_OPT_EXEC = port("exec", "exec", "Optionnel : relie, la lecture se fait a cet endroit du flow",
                 "Optional: linked, the read runs at this point of the flow")
_OPT_THEN = port("then", "exec", "Suite (si exec est relie)", "Next step (when exec is linked)")
_PROJECT = port("project", "str", "Projet (vide : celui du flow)", "Project (empty: the flow's one)", "DEMO")

# Soft of a published file, from its extension (soft ids of 02 §1).
SOFT_BY_EXT: Dict[str, str] = {
    ".ma": "maya", ".mb": "maya",
    ".hip": "houdini", ".hipnc": "houdini", ".hiplc": "houdini",
    ".nk": "nuke", ".nknc": "nuke",
    ".spp": "painter", ".sbs": "designer", ".sbsar": "designer",
    ".zpr": "zbrush", ".ztl": "zbrush",
    ".zprj": "marvelous", ".zpac": "marvelous",
}
_IMAGE_EXTS = (".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".hdr", ".bmp", ".dpx")
_VIDEO_EXTS = (".mov", ".mp4", ".avi", ".mkv", ".webm")
# Type of a published file: image, video, scene, usd, cache, texture or other.
TYPE_BY_EXT: Dict[str, str] = {
    **{e: "image" for e in _IMAGE_EXTS}, **{e: "video" for e in _VIDEO_EXTS},
    **{e: "scene" for e in SOFT_BY_EXT},
    ".usd": "usd", ".usda": "usd", ".usdc": "usd", ".usdz": "usd",
    ".abc": "cache", ".vdb": "cache", ".bgeo": "cache", ".bgeo.sc": "cache", ".fbx": "cache", ".obj": "cache",
    ".tx": "texture", ".rat": "texture",
}
_ITER_RE = re.compile(r"_(LAST|v\d+)$", re.IGNORECASE)
_ITER_PARAM_RE = re.compile(r"^(LAST|v\d+)$", re.IGNORECASE)
LOG_ACTIONS = ("update", "import", "error")


def _line(kind: str, text: str, path: Any = None) -> Dict[str, Any]:
    return {"kind": kind, "text_fr": text, "path": str(path) if path is not None else None}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _required_text(value: Any, what: str) -> str:
    text = _text(value)
    if not text:
        raise NodeError(f"{what} manquant", code="E_PARAM_INVALID")
    return text


def _project(ctx, value: Any) -> Tuple[str, Path]:
    """(name, folder) of the project asked, the run's project when empty."""
    c = ctx.context or {}
    name = _text(value) or _text(c.get("project"))
    if not name:
        raise NodeError("Pas de projet : relie `project` ou lance le flow dans un projet")
    if name == c.get("project") and c.get("project_path"):
        return name, Path(c["project_path"])
    from core.paths import get_project_path

    try:
        path = get_project_path(name)
    except Exception as exc:  # noqa: BLE001 - FLUX_ROOT missing: say it on the node
        raise NodeError(f"Projet `{name}` introuvable : {exc}") from None
    if not path.is_dir():
        raise NodeError(f"Projet introuvable : {name} ({path})")
    return name, path


def _mask(pattern: Any, names: List[str], what: str) -> List[bool]:
    """Houdini style pattern over *names*. An empty / absent filter keeps everything
    (an empty pattern keeps nothing in patterns.py: here it means "no filter")."""
    text = _text(pattern)
    if not text:
        return [True] * len(names)
    from flux_flows.patterns import PatternError, mask

    try:
        return mask(text, names)
    except PatternError as exc:
        raise NodeError(f"Motif `{what}` invalide : {exc.message}", code="E_PARAM_INVALID") from None


def _ext_of(name: str) -> str:
    low = name.lower()
    return ".bgeo.sc" if low.endswith(".bgeo.sc") else Path(low).suffix


def publish_record(path: Any, **meta: Any) -> Dict[str, Any]:
    """The ``publish`` record of a published file. soft, type and version are
    deduced from the name and the extension (02 §7 note 1)."""
    p = Path(str(path))
    ext = _ext_of(p.name)
    stem = p.name[: len(p.name) - len(ext)] if ext else p.name
    m = _ITER_RE.search(stem)
    base = stem[: m.start()] if m else stem
    version = int(m.group(1)[1:]) if m and m.group(1).lower().startswith("v") else None
    return {"id": meta.get("id") or "", "path": str(p), "dir": str(p.parent), "file": p.name, "name": base,
            "version": version, "user": meta.get("user") or "", "date": meta.get("date") or "",
            "time": meta.get("time") or "", "soft": SOFT_BY_EXT.get(ext, ""), "type": TYPE_BY_EXT.get(ext, "other"),
            "ext": ext}


# R1 retakes 3 and 10: one "infos" dict for PublishRequest and OnPublish, read by the
# data.publish_infos node and by the OnPublish filters. Tokens come from the FLUX name
# (features/folder_manager/naming_validator.parse_filename, read only): asset
# CLASS_TYPE_NAME_INSTANCE, shot SEQ_SHOT_TYPE_VARIANTE. task = the TYPE token (department
# of the asset, task of the shot). soft: given by the caller, else from the extension.
PUBLISH_INFO_KEYS = ("mode", "project", "soft", "user", "task", "class", "asset", "seq", "shot", "instance",
                     "variant", "version", "file_type", "ext", "file", "path")


def publish_infos(file_name: Any, *, soft: str = "", project: str = "", user: str = "", path: Any = "",
                  version: Any = None) -> Dict[str, Any]:
    """The infos of a publish (asked or done). Unknown fields are "" (version None)."""
    from features.folder_manager.naming_validator import parse_filename

    name = Path(str(file_name or path or "")).name
    record = publish_record(path or name) if (path or name) else {}
    parsed = parse_filename(name) if name else None
    shot = bool(parsed and parsed.get("is_shot"))
    out: Dict[str, Any] = {k: "" for k in PUBLISH_INFO_KEYS}
    out.update({"mode": ("shot" if shot else "asset") if parsed else "", "project": project or "",
                "soft": soft or record.get("soft") or "", "user": user or "",
                "file_type": record.get("type") or "", "ext": record.get("ext") or "",
                "file": record.get("file") or "", "path": str(path) if path else "",
                "version": version if version is not None else record.get("version")})
    if parsed:
        out.update({"task": parsed.get("TYPE") or "", "instance": parsed.get("INSTANCE") or "",
                    "variant": parsed.get("VARIANTE") or ""})
        if shot:
            out.update({"seq": parsed.get("SEQ") or "", "shot": parsed.get("SHOT") or ""})
        else:
            out.update({"class": parsed.get("CLASS") or "", "asset": parsed.get("NAME") or ""})
    return out


def _type_tags(record: Dict[str, Any]) -> List[str]:
    kind = record.get("type") or "other"
    return [kind, "capture"] if kind in ("image", "video") else [kind]


# -- flux.find_publishes / publish_fields -------------------------------------------

def _day(value: Any, what: str, default: date) -> date:
    text = _text(value).lower()
    if not text:
        return default
    if text == "today":
        return date.today()
    if text == "yesterday":
        return date.today() - timedelta(days=1)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise NodeError(f"{what} : date attendue (today, yesterday ou AAAA-MM-JJ), recu `{value}`",
                        code="E_PARAM_INVALID") from None


def _dest_folder(raw: Any) -> Optional[Path]:
    text = _text(raw)
    if not text:
        return None
    from core.paths import from_flux_token

    try:
        return Path(from_flux_token(text))
    except Exception:  # noqa: BLE001 - no FLUX_ROOT: keep the stored value
        return Path(text)


def _keep_publishes(records: List[Dict[str, Any]], params) -> List[Dict[str, Any]]:
    keep = [True] * len(records)
    # soft: an image or a video has no known soft in V1 (the log does not keep it):
    # the soft filter keeps it, else "playblasts Maya et Houdini" finds nothing.
    softs = _mask(params.get("soft"), [r["soft"] for r in records], "soft")
    keep = [k and (s or (not r["soft"] and "capture" in _type_tags(r))) for k, r, s in zip(keep, records, softs)]
    if _text(params.get("type")):
        keep = [k and any(_mask(params.get("type"), _type_tags(r), "type")) for k, r in zip(keep, records)]
    names = _mask(params.get("name"), [r["file"] for r in records], "name")
    users = _mask(params.get("user"), [r["user"] for r in records], "user")
    return [r for r, k, n, u in zip(records, keep, names, users) if k and n and u]


@flow_node("flux.find_publishes", "FindPublishes", icon="PackageSearch",
           inputs=[_OPT_EXEC, _PROJECT],
           outputs=[_OPT_THEN,
                    port("items", "list[publish]", "Publishs trouves, du plus ancien au plus recent",
                         "Publishes found, oldest first"),
                    port("count", "int", "Nombre de publishs", "Number of publishes", 3),
                    port("first", "publish", "Premier publish (vide si aucun)", "First publish (empty when none)")],
           params=[port("date", "str", "Jour : today, yesterday ou AAAA-MM-JJ", "Day: today, yesterday or YYYY-MM-DD",
                        "today", default="today"),
                   port("date_to", "str", "Dernier jour de la plage (vide : le meme jour)",
                        "Last day of the range (empty: the same day)", "2026-10-23"),
                   port("soft", "pattern", "Logiciels (maya, houdini...) ; une image ou video est gardee",
                        "Softs (maya, houdini...); an image or video is kept", "maya houdini"),
                   port("type", "pattern", "Types : scene, usd, cache, texture, image, video, capture",
                        "Types: scene, usd, cache, texture, image, video, capture", "capture"),
                   port("name", "pattern", "Motif sur le nom du fichier", "Pattern on the file name", "*_anim_* ^*_tmp*"),
                   port("user", "pattern", "Motif sur l'artiste", "Pattern on the artist", "ADAM*")],
           shelf=41, aliases=["publishs", "playblast", "daily", "recherche publish"],
           doc_fr="Liste les publishs du projet sur une date ou une plage, filtres par logiciel, type, nom ou "
                  "artiste. Soft, type et version sont deduits du nom et de l'extension. Lecture.",
           doc_en="Lists the project publishes on a day or a range, filtered by soft, type, name or artist. "
                  "Soft, type and version come from the name and the extension. Read only.")
def find_publishes(ctx, inputs, params):
    from features.calendar.publishes import publishes_between

    name, _path = _project(ctx, inputs.get("project"))
    start = _day(params.get("date"), "date", date.today())
    end = _day(params.get("date_to"), "date_to", start)
    try:
        events = publishes_between(name, start.isoformat(), end.isoformat())
    except ValueError as exc:
        raise NodeError(f"Plage de dates : {exc}", code="E_PARAM_INVALID") from None
    records = []
    for ev in events:
        folder = _dest_folder(ev.get("dest_folder"))
        file = _text(ev.get("file"))
        path = folder / file if folder is not None else Path(file)
        records.append(publish_record(path, id=ev.get("id"), user=ev.get("user"), date=ev.get("date"),
                                      time=ev.get("time")))
    items = _keep_publishes(records, params)
    return {"items": items, "count": len(items), "first": items[0] if items else None}


@flow_node("flux.publish_fields", "PublishFields", icon="Tags",
           inputs=[port("publish", "publish", "Un publish (FindPublishes, PublishFile)",
                        "A publish (FindPublishes, PublishFile)", required=True)],
           outputs=[port("path", "path", "Fichier publie", "Published file"),
                    port("dir", "dir", "Dossier du publish", "Publish folder"),
                    port("name", "str", "Nom de base (sans LAST / vNNN)", "Base name (without LAST / vNNN)",
                         "CHAR_MOD_HERO_null"),
                    port("version", "int", "Version (vide pour LAST)", "Version (empty for LAST)", 3),
                    port("user", "str", "Artiste", "Artist", "ADAM"),
                    port("date", "str", "Date du publish", "Publish date", "2026-10-23"),
                    port("soft", "str", "Logiciel (deduit de l'extension)", "Soft (from the extension)", "maya"),
                    port("type", "str", "Type (deduit de l'extension)", "Type (from the extension)", "video")],
           shelf=42, aliases=["champs publish", "chemin publish", "publish path"],
           doc_fr="Lit les champs d'un publish : chemin, dossier, nom, version, artiste, date, logiciel, type.",
           doc_en="Reads the fields of a publish: path, folder, name, version, artist, date, soft, type.")
def publish_fields(ctx, inputs, params):
    value = inputs.get("publish")
    if isinstance(value, dict):
        if not value.get("path"):
            raise NodeError("Publish sans chemin")
        record = {**publish_record(value["path"]), **{k: v for k, v in value.items() if v not in (None, "")}}
    elif _text(value):
        record = publish_record(as_path(ctx, value, "publish"))
    else:
        raise NodeError("PublishFields attend un publish : relie FindPublishes ou PublishFile")
    return {k: record.get(k) for k in ("path", "dir", "name", "version", "user", "date", "soft", "type")}


# -- flux.resolve_path --------------------------------------------------------------

@flow_node("flux.resolve_path", "ResolvePath", icon="Link",
           inputs=[_OPT_EXEC],
           outputs=[_OPT_THEN,
                    port("path", "path", "Fichier LAST ou vNNN (vide si absent)", "LAST or vNNN file (empty when missing)"),
                    port("dir", "dir", "Dossier du publish", "Publish folder"),
                    port("exists", "bool", "Le fichier existe", "The file exists", True)],
           params=[port("project", "str", "Projet (vide : celui du flow)", "Project (empty: the flow's one)", "DEMO"),
                   port("class", "str", "Classe (token CLASS)", "Class (CLASS token)", "CHAR", tokens="CLASS"),
                   port("type", "str", "Type / departement (token TYPE)", "Type / department (TYPE token)", "MOD",
                        tokens="TYPE"),
                   port("name", "str", "Nom de l'asset", "Asset name", "HERO", tokens="NAME"),
                   port("instance", "str", "Instance", "Instance", "null", default="null", tokens="INSTANCE"),
                   port("variant", "str", "Variante (optionnelle)", "Variant (optional)", ""),
                   port("iter", "str", "LAST ou vNNN", "LAST or vNNN", "LAST", default="LAST")],
           shelf=43, aliases=["chemin asset", "resoudre", "path", "last"],
           doc_fr="Donne le chemin publie d'un asset (dossier du publish, fichier LAST ou d'une version). Lecture.",
           doc_en="Gives the published path of an asset (publish folder, LAST or version file). Read only.")
def resolve_path(ctx, inputs, params):
    from features.publisher.publish_core import resolve_publish_path
    from features.publisher.publish_layout import find_last_file, find_version_file

    _name, project_path = _project(ctx, params.get("project"))
    parts = [_required_text(params.get(k), k).upper() for k in ("class", "type", "name")]
    parts.append(_text(params.get("instance")) or "null")
    if _text(params.get("variant")):
        parts.append(_text(params.get("variant")).upper())
    iteration = _text(params.get("iter")) or "LAST"
    if not _ITER_PARAM_RE.match(iteration):
        raise NodeError(f"iter : LAST ou vNNN attendu, recu `{iteration}`", code="E_PARAM_INVALID")
    base = "_".join(parts)
    folder = resolve_publish_path(project_path, f"{base}_LAST.usd")
    if folder is None:
        raise NodeError(f"`{base}` ne se resout pas dans le projet (tokens CLASS / NAME / TYPE)")
    if iteration.upper() == "LAST":
        found = find_last_file(folder, base)
    else:
        found = find_version_file(folder, base, iteration)
    return {"path": str(found) if found else None, "dir": str(folder), "exists": bool(found and found.exists())}


# -- project / production readers ---------------------------------------------------

@flow_node("flux.project_info", "ProjectInfo", icon="FolderKanban",
           inputs=[_PROJECT],
           outputs=[port("name", "str", "Nom du projet", "Project name", "DEMO"),
                    port("path", "dir", "Dossier du projet", "Project folder"),
                    port("tokens", "dict", "Tokens du projet (tokens.json)", "Project tokens (tokens.json)")],
           shelf=44, aliases=["projet", "project", "tokens"],
           doc_fr="Donne le nom, le dossier et les tokens d'un projet.",
           doc_en="Gives the name, folder and tokens of a project.")
def project_info(ctx, inputs, params):
    from features.folder_manager.tokens import load_tokens

    name, path = _project(ctx, inputs.get("project"))
    return {"name": name, "path": str(path), "tokens": load_tokens(path)}


def _production(name: str) -> Dict[str, Any]:
    from features.production.production_store import load_production

    return load_production(name)


def _entity_folder(path: Path, kind: str, **keys: str) -> Optional[str]:
    from features.production.archive import resolve_entity_rel

    rel = resolve_entity_rel(path, kind, **keys)
    return str(path / rel) if rel else None


def _seq_names(data: Dict[str, Any]) -> Dict[str, str]:
    return {s.get("id"): str(s.get("name") or "") for s in data.get("sequences") or []}


@flow_node("flux.asset_info", "AssetInfo", icon="Box",
           inputs=[_PROJECT,
                   port("asset", "str", "Asset : NOM ou CLASSE/NOM", "Asset: NAME or CLASS/NAME", "CHAR/HERO",
                        required=True)],
           outputs=[port("found", "bool", "L'asset existe dans la Production", "The asset exists in Production", True),
                    port("class", "str", "Classe", "Class", "CHAR"),
                    port("folder", "dir", "Dossier de l'asset", "Asset folder"),
                    port("record", "dict", "Fiche Production de l'asset", "Production record of the asset")],
           shelf=45, aliases=["asset", "fiche asset"],
           doc_fr="Lit la fiche Production d'un asset et son dossier.",
           doc_en="Reads the Production record of an asset and its folder.")
def asset_info(ctx, inputs, params):
    name, path = _project(ctx, inputs.get("project"))
    cls, _, nm = _required_text(inputs.get("asset"), "asset").upper().replace("\\", "/").rpartition("/")
    hits = [a for a in _production(name).get("assets") or []
            if str(a.get("name") or "").upper() == nm and (not cls or str(a.get("class") or "").upper() == cls)]
    if len(hits) > 1:
        classes = ", ".join(sorted(str(a.get("class")) for a in hits))
        raise NodeError(f"Asset `{nm}` ambigu ({classes}) : ecris CLASSE/NOM", code="E_PARAM_INVALID")
    if not hits:
        return {"found": False, "class": cls or None, "folder": None, "record": {}}
    record = hits[0]
    klass = str(record.get("class") or "")
    return {"found": True, "class": klass, "record": dict(record),
            "folder": _entity_folder(path, "asset", class_token=klass, name=nm)}


@flow_node("flux.shot_info", "ShotInfo", icon="Clapperboard",
           inputs=[_PROJECT,
                   port("seq", "str", "Sequence", "Sequence", "SEQ010", required=True, tokens="SEQ"),
                   port("shot", "str", "Plan", "Shot", "SHOT010", required=True, tokens="SHOT")],
           outputs=[port("found", "bool", "Le plan existe dans la Production", "The shot exists in Production", True),
                    port("folder", "dir", "Dossier du plan", "Shot folder"),
                    port("record", "dict", "Fiche Production du plan", "Production record of the shot")],
           shelf=46, aliases=["plan", "shot", "fiche plan"],
           doc_fr="Lit la fiche Production d'un plan et son dossier.",
           doc_en="Reads the Production record of a shot and its folder.")
def shot_info(ctx, inputs, params):
    name, path = _project(ctx, inputs.get("project"))
    seq = _required_text(inputs.get("seq"), "seq").upper()
    shot = _required_text(inputs.get("shot"), "shot").upper()
    data = _production(name)
    seq_ids = {i for i, n in _seq_names(data).items() if n.upper() == seq}
    hits = [s for s in data.get("shots") or []
            if s.get("seq_id") in seq_ids and str(s.get("name") or "").upper() == shot]
    if not hits:
        return {"found": False, "folder": None, "record": {}}
    return {"found": True, "record": {**hits[0], "seq": seq},
            "folder": _entity_folder(path, "shot", seq=seq, shot=shot)}


@flow_node("flux.list_assets", "ListAssets", icon="Boxes",
           inputs=[_PROJECT],
           outputs=[port("names", "list[str]", "Noms des assets", "Asset names", ["HERO", "TREE"]),
                    port("records", "list[dict]", "Fiches Production", "Production records"),
                    port("count", "int", "Nombre d'assets", "Number of assets", 2)],
           params=[port("class", "pattern", "Motif sur la classe (vide : toutes)", "Pattern on the class (empty: all)",
                        "CHAR PROP")],
           shelf=47, aliases=["assets", "liste assets"],
           doc_fr="Liste les assets de la Production, filtres par classe.",
           doc_en="Lists the Production assets, filtered by class.")
def list_assets(ctx, inputs, params):
    name, _path = _project(ctx, inputs.get("project"))
    assets = list(_production(name).get("assets") or [])
    keep = _mask(params.get("class"), [str(a.get("class") or "") for a in assets], "class")
    records = [dict(a) for a, k in zip(assets, keep) if k]
    return {"names": [str(a.get("name") or "") for a in records], "records": records, "count": len(records)}


@flow_node("flux.list_shots", "ListShots", icon="Film",
           inputs=[_PROJECT],
           outputs=[port("names", "list[str]", "Plans SEQ/SHOT", "Shots SEQ/SHOT", ["SEQ010/SHOT010"]),
                    port("records", "list[dict]", "Fiches Production (avec seq)", "Production records (with seq)"),
                    port("count", "int", "Nombre de plans", "Number of shots", 1)],
           params=[port("seq", "pattern", "Motif sur la sequence (vide : toutes)",
                        "Pattern on the sequence (empty: all)", "SEQ01*")],
           shelf=48, aliases=["plans", "shots", "liste plans"],
           doc_fr="Liste les plans de la Production (SEQ/SHOT), filtres par sequence.",
           doc_en="Lists the Production shots (SEQ/SHOT), filtered by sequence.")
def list_shots(ctx, inputs, params):
    name, _path = _project(ctx, inputs.get("project"))
    data = _production(name)
    seqs = _seq_names(data)
    shots = [{**s, "seq": seqs.get(s.get("seq_id"), "")} for s in data.get("shots") or []]
    keep = _mask(params.get("seq"), [s["seq"] for s in shots], "seq")
    records = [s for s, k in zip(shots, keep) if k]
    return {"names": [f"{s['seq']}/{s.get('name') or ''}" for s in records], "records": records,
            "count": len(records)}


# -- flux.ping / log_activity -------------------------------------------------------

def _ping_args(ctx, inputs) -> Tuple[str, str, str]:
    from features.activity.chat_manager import get_user_list

    user = _required_text(inputs.get("user"), "user").lstrip("@")
    text = _required_text(inputs.get("text"), "text")
    project = _text((ctx.context or {}).get("project"))
    if not project:
        raise NodeError("Pas de projet : le chat est celui d'un projet")
    known = {u.lower(): u for u in get_user_list()}
    if user.lower() not in known:
        hint = f" ({', '.join(sorted(known.values())[:8])})" if known else ""
        raise NodeError(f"Utilisateur inconnu `{user}`{hint}", code="E_PARAM_INVALID")
    return known[user.lower()], text, project


def _simulate_ping(ctx, inputs, params):
    user, text, _project_ = _ping_args(ctx, inputs)
    return {"lines": [_line("ping", f"pinguerait @{user} : {text}")], "outputs": {}}


@flow_node("flux.ping", "Ping", icon="AtSign",
           inputs=[_EXEC,
                   port("user", "str", "Artiste a pinguer", "Artist to ping", "ADAM", required=True),
                   port("text", "str", "Message", "Message", "Le daily est pret", required=True)],
           outputs=list(_EXITS),
           effect=True, simulate=_simulate_ping, shelf=49, aliases=["mention", "@", "chat", "prevenir"],
           doc_fr="Ecrit un message dans le chat du projet avec @artiste : il recoit une mention non lue.",
           doc_en="Writes a message in the project chat with @artist: they get an unread mention.")
def ping(ctx, inputs, params):
    from features.activity.chat_manager import send_message

    user, text, project = _ping_args(ctx, inputs)
    if not send_message((ctx.context or {}).get("user") or "unknown", f"@{user} {text}", project):
        raise NodeError("Le message n'a pas pu etre ecrit dans le chat")
    return {}


def _log_args(ctx, inputs, params) -> Tuple[str, str, Optional[Path], str]:
    text = _required_text(inputs.get("text"), "text")
    action = (_text(params.get("action")) or "update").lower()
    if action == "publish":
        raise NodeError("action `publish` reservee au Publisher (le calendrier la lit)", code="E_PARAM_INVALID")
    if action not in LOG_ACTIONS:
        raise NodeError(f"Action inconnue '{action}' ({', '.join(LOG_ACTIONS)})", code="E_PARAM_INVALID")
    project = _text((ctx.context or {}).get("project"))
    if not project:
        raise NodeError("Pas de projet : le fil Activite est celui d'un projet")
    folder = as_path(ctx, inputs.get("folder"), "dossier") if _text(inputs.get("folder")) else None
    return text, action, folder, project


def _simulate_log_activity(ctx, inputs, params):
    text, action, folder, _project_ = _log_args(ctx, inputs, params)
    return {"lines": [_line("activity", f"ecrirait dans le fil Activite ({action}) : {text}", folder)],
            "outputs": {}}


@flow_node("flux.log_activity", "LogActivity", icon="ScrollText",
           inputs=[_EXEC,
                   port("text", "str", "Texte (nom de fichier ou message)", "Text (file name or message)",
                        "Daily copie", required=True),
                   port("folder", "dir", "Dossier lie (optionnel)", "Related folder (optional)")],
           outputs=list(_EXITS),
           params=[port("action", "str", "update, import ou error", "update, import or error", "update",
                        default="update", choices=LOG_ACTIONS)],
           effect=True, simulate=_simulate_log_activity, shelf=80, aliases=["activite", "journal", "log"],
           doc_fr="Poste un evenement dans le fil Activite du projet (vu par l'equipe).",
           doc_en="Posts an event in the project Activity feed (seen by the team).")
def log_activity(ctx, inputs, params):
    from features.activity.activity_writer import log_event

    text, action, folder, project = _log_args(ctx, inputs, params)
    if not log_event((ctx.context or {}).get("user") or "unknown", action, project, filename=text,
                     dest_folder=folder):
        raise NodeError("Le fil Activite n'a pas pu etre ecrit")
    return {}


# -- flux.archive -------------------------------------------------------------------

def _simulate_archive(ctx, inputs, params):
    path = as_path(ctx, inputs.get("path"), "chemin a archiver")
    dest = archive_preview(ctx, path)
    lines = [_line("archive", f"archiverait {path} vers {dest}", path)]
    if not path.exists():
        lines.append(_line("warn", f"{path} n'existe pas encore", path))
    return {"lines": lines, "outputs": {"archived_to": str(dest)}}


@flow_node("flux.archive", "Archive", icon="Archive",
           inputs=[_EXEC, port("path", "path", "Fichier ou dossier du projet", "Project file or folder",
                               "shot/SEQ010/SH010/tmp", required=True)],
           outputs=[*_EXITS, port("archived_to", "path", "Ou il a ete archive", "Where it was archived")],
           effect=True, simulate=_simulate_archive, shelf=81, aliases=["archiver", "ranger", "corbeille"],
           doc_fr="Deplace un fichier ou un dossier du projet dans ARCHIVE/<date>_<ARTISTE>/. N'efface jamais.",
           doc_en="Moves a project file or folder into ARCHIVE/<date>_<ARTIST>/. Never erases.")
def archive(ctx, inputs, params):
    path = as_path(ctx, inputs.get("path"), "chemin a archiver")
    dest = archive_into_project(ctx, path)
    ctx.log(f"archive : {path} -> {dest}")
    return {"archived_to": str(dest)}


# -- flux.publish_file --------------------------------------------------------------

def _publish_args(ctx, inputs, params) -> Tuple[Path, Optional[str], str, str, Path]:
    source = as_path(ctx, inputs.get("source"), "fichier a publier")
    target = _text(params.get("target_name")) or None
    c = ctx.context or {}
    project, project_path = _project(ctx, None)
    return source, target, _text(c.get("user")) or "unknown", project, project_path


def _simulate_publish_file(ctx, inputs, params):
    from features.publisher.publish_layout import next_publish_version
    from flux_actions.runner import preview_publish_action

    source, target, user, project, project_path = _publish_args(ctx, inputs, params)
    dest = preview_publish_action(source, project_path, user, project, target, logger=_CtxLogger(ctx))
    if dest is None:
        raise NodeError(f"`{target or source.name}` ne se resout pas dans le projet (nom non conforme aux tokens)")
    rec = publish_record(Path(dest) / (target or source.name))
    ext = rec["ext"] or source.suffix
    version = next_publish_version(Path(dest), rec["name"], ext) if Path(dest).is_dir() else 1
    path = Path(dest) / f"{rec['name']}_LAST{ext}"
    lines = [_line("publish", f"publierait {source} comme {rec['name']} v{version:03d} dans {dest}", path)]
    if not source.exists():
        lines.append(_line("warn", f"{source} n'existe pas encore", source))
    return {"lines": lines, "outputs": {"publish": publish_record(path, user=user), "path": str(path)}}


@flow_node("flux.publish_file", "PublishFile", icon="PackagePlus",
           inputs=[_EXEC, port("source", "path", "Fichier a publier", "File to publish",
                               "work/CHAR_MOD_HERO_null.usd", required=True)],
           outputs=[*_EXITS, port("publish", "publish", "Le publish cree", "The publish made"),
                    port("path", "path", "Fichier LAST publie", "Published LAST file")],
           params=[port("target_name", "str", "Nom FLUX du publish (vide : nom du fichier)",
                        "FLUX name of the publish (empty: file name)", "CHAR_MOD_HERO_null.usd"),
                   port("description", "str", "Description du publish", "Publish description", "Retake lumiere",
                        default="")],
           effect=True, simulate=_simulate_publish_file, shelf=82, aliases=["publier", "publish", "version"],
           doc_fr="Publie un fichier dans le layout FLUX (nouvelle vNNN et LAST), comme le Publisher.",
           doc_en="Publishes a file into the FLUX layout (new vNNN and LAST), like the Publisher.")
def publish_file(ctx, inputs, params):
    from flux_actions.runner import run_publish_action

    source, target, user, project, project_path = _publish_args(ctx, inputs, params)
    if not source.is_file():
        raise NodeError(f"Fichier a publier introuvable : {source}")
    dest = run_publish_action(source, project_path, _text(params.get("description")), user, project, target,
                              logger=_CtxLogger(ctx))
    if dest is None:
        raise NodeError(f"Le publish de {source.name} a echoue (voir le journal du node)")
    c = ctx.context or {}
    record = publish_record(dest, user=user, date=c.get("date"), time=c.get("time"))
    ctx.log(f"publie : {source} -> {dest}")
    return {"publish": record, "path": str(dest)}


# -- flux.call_function -------------------------------------------------------------

def _function_ref(params) -> Tuple[str, str]:
    from flux_actions.commands.call_function import check_function_ref

    ref = _text(params.get("function"))
    try:
        return check_function_ref(ref)
    except ValueError as exc:
        raise NodeError(str(exc), code="E_PARAM_INVALID") from None


def _call_args(inputs) -> Dict[str, Any]:
    args = inputs.get("args")
    if args is None:
        return {}
    if not isinstance(args, dict):
        raise NodeError(f"args : dictionnaire attendu, recu {type(args).__name__}")
    return dict(args)


def _simulate_call_function(ctx, inputs, params):
    module, name = _function_ref(params)
    args = _call_args(inputs)
    return {"lines": [_line("call", f"appellerait {module}:{name}({', '.join(sorted(args))}) (non execute)")],
            "outputs": {"result": None}}


@flow_node("flux.call_function", "CallFunction", icon="SquareFunction",
           inputs=[_EXEC, port("args", "dict", "Arguments de la fonction", "Function arguments",
                               {"project_name": "DEMO"})],
           outputs=[*_EXITS, port("result", "any", "Ce que la fonction renvoie", "What the function returns")],
           params=[port("function", "str", "package.module:fonction (packages features, core, dcc de FLUX)",
                        "package.module:function (FLUX packages features, core, dcc)",
                        "features.production.production_store:load_production", required=True)],
           destructive=True, simulate=_simulate_call_function, shelf=83, aliases=["fonction", "python", "api"],
           doc_fr="Appelle une fonction du code de FLUX (features, core, dcc). Code libre : jamais lance en essai "
                  "a blanc. Un argument absent prend la valeur du contexte du meme nom.",
           doc_en="Calls a function of the FLUX code (features, core, dcc). Free code: never run in a dry run. "
                  "A missing argument takes the context value of the same name.")
def call_function(ctx, inputs, params):
    from flux_actions.commands.call_function import _coerce, resolve_function

    _function_ref(params)
    ref = _text(params.get("function"))
    try:
        func = resolve_function(ref)
    except (ValueError, ImportError) as exc:
        raise NodeError(f"Fonction introuvable `{ref}` : {exc}", code="E_PARAM_INVALID") from None
    args = _call_args(inputs)
    sig = inspect.signature(func)
    takes_kw = any(a.kind == a.VAR_KEYWORD for a in sig.parameters.values())
    unknown = [k for k in args if k not in sig.parameters and not takes_kw]
    if unknown:
        raise NodeError(f"`{ref}` n'a pas d'argument {', '.join(sorted(unknown))}", code="E_PARAM_INVALID")
    context = _legacy_context(ctx)
    kwargs: Dict[str, Any] = {}
    for name, arg in sig.parameters.items():
        if arg.kind in (arg.VAR_POSITIONAL, arg.VAR_KEYWORD):
            continue
        value = args.get(name)
        if value is None and name in context:
            value = context[name]
        if value is not None:
            kwargs[name] = _coerce(value, arg.annotation)
    kwargs.update({k: v for k, v in args.items() if k not in sig.parameters})
    ctx.log(f"appel : {ref}({', '.join(kwargs)})")
    result = func(**kwargs)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    return {"result": result}


# -- flux.conform_texture / generate_proxy ------------------------------------------

def _conform_args(ctx, inputs, params) -> Dict[str, Any]:
    source = as_path(ctx, inputs.get("source"), "texture source")
    out_dir = as_path(ctx, params.get("out_dir"), "dossier de sortie") if _text(params.get("out_dir")) else None
    force = as_bool(params.get("force"), False)
    if force:   # re-conversion overwrites the .tx already there
        check_destructive_target(out_dir or (source if source.is_dir() else source.parent))
    return {"source": source, "out_dir": out_dir, "colorconvert": as_bool(params.get("colorconvert"), True),
            "color_in": _text(params.get("color_in")) or None, "color_out": _text(params.get("color_out")) or None,
            "force": force}


def _simulate_conform(ctx, inputs, params):
    from features.publisher.texture_conform import expand_inputs

    a = _conform_args(ctx, inputs, params)
    sources = expand_inputs(str(a["source"]))
    tx = [str((a["out_dir"] or s.parent) / f"{s.stem}.tx") for s in sources]
    where = a["out_dir"] or "a cote des sources"
    lines = [_line("conform", f"convertirait {len(sources)} textures en .tx ({where})", a["source"])]
    if not sources:
        lines.append(_line("warn", f"aucune texture trouvee pour {a['source']}", a["source"]))
    return {"lines": lines, "outputs": {"tx_paths": tx, "converted": len(sources), "skipped": 0}}


@flow_node("flux.conform_texture", "ConformTexture", icon="Palette",
           inputs=[_EXEC, port("source", "path", "Texture, dossier ou motif UDIM (<UDIM>)",
                               "Texture, folder or UDIM pattern (<UDIM>)", "tex/HERO_BaseColor.<UDIM>.exr",
                               required=True)],
           outputs=[*_EXITS, port("tx_paths", "list[path]", "Fichiers .tx", ".tx files"),
                    port("converted", "int", "Textures converties", "Textures converted", 4),
                    port("skipped", "int", "Textures deja a jour", "Textures already up to date", 0)],
           params=[port("out_dir", "dir", "Dossier de sortie (vide : a cote des sources)",
                        "Output folder (empty: next to the sources)"),
                   port("colorconvert", "bool", "Convertir l'espace couleur (sRGB vers lineaire)",
                        "Convert the color space (sRGB to linear)", True, default=True),
                   port("color_in", "str", "Espace d'entree des maps couleur", "Input space of color maps",
                        "srgb_texture"),
                   port("color_out", "str", "Espace de sortie des maps couleur", "Output space of color maps",
                        "scene_linear"),
                   port("force", "bool", "Reconvertir meme a jour (ecrase les .tx)",
                        "Reconvert even when up to date (overwrites the .tx)", False, default=False)],
           destructive={"param": "force", "equals": True}, simulate=_simulate_conform, shelf=84,
           aliases=["tx", "texture", "mipmap", "karma"],
           doc_fr="Convertit une texture ou un set UDIM en .tx mipmappes pour Karma (OpenImageIO, aucune licence).",
           doc_en="Converts a texture or a UDIM set to mipped .tx for Karma (OpenImageIO, no license).")
def conform_texture(ctx, inputs, params):
    from flux_actions.runner import run_conform_texture_action

    a = _conform_args(ctx, inputs, params)
    out = run_conform_texture_action(a["source"], a["out_dir"], a["colorconvert"], a["color_in"], a["color_out"],
                                     a["force"], logger=_CtxLogger(ctx))
    if out is None:
        raise NodeError(f"Conversion .tx echouee pour {a['source']} (voir le journal du node)")
    return {"tx_paths": list(out.get("tx_paths") or []), "converted": int(out.get("converted") or 0),
            "skipped": int(out.get("skipped") or 0)}


def _number(value: Any, kind: type, what: str) -> Any:
    if value is None or value == "":
        return None
    try:
        return kind(value)
    except (TypeError, ValueError):
        raise NodeError(f"{what} : nombre attendu, recu {value!r}", code="E_PARAM_INVALID") from None


def _proxy_args(ctx, inputs, params) -> Dict[str, Any]:
    source = as_path(ctx, inputs.get("source"), "USD source")
    out = as_path(ctx, params.get("out"), "proxy") if _text(params.get("out")) else source.with_suffix(".proxy.usda")
    force = as_bool(params.get("force"), False)
    if force:
        check_destructive_target(out)
    return {"source": source, "out": out, "force": force,
            "target_reduction": _number(params.get("target_reduction"), float, "target_reduction"),
            "min_tris": _number(params.get("min_tris"), int, "min_tris")}


def _simulate_proxy(ctx, inputs, params):
    a = _proxy_args(ctx, inputs, params)
    lines = [_line("proxy", f"genererait le proxy de {a['source']} vers {a['out']}", a["out"])]
    if not a["source"].is_file():
        lines.append(_line("warn", f"{a['source']} n'existe pas encore", a["source"]))
    return {"lines": lines, "outputs": {"proxy_path": str(a["out"]), "mesh_count": 0, "tri_count": 0}}


@flow_node("flux.generate_proxy", "GenerateProxy", icon="Shrink",
           inputs=[_EXEC, port("source", "path", "Asset USD source", "Source USD asset",
                               "assets/CHR/HERO/HERO_LAST.usd", required=True)],
           outputs=[*_EXITS, port("proxy_path", "path", "Layer proxy ecrit", "Written proxy layer"),
                    port("mesh_count", "int", "Meshes traites", "Meshes processed", 12),
                    port("tri_count", "int", "Triangles du proxy", "Proxy triangles", 4800)],
           params=[port("out", "path", "Layer proxy (vide : <source>.proxy.usda)", "Proxy layer (empty: <source>.proxy.usda)"),
                   port("target_reduction", "float", "Fraction de triangles retires", "Fraction of triangles removed",
                        0.9),
                   port("min_tris", "int", "Seuil sous lequel on ne decime pas", "Threshold under which nothing is decimated",
                        500),
                   port("force", "bool", "Regenerer meme a jour (ecrase le proxy)",
                        "Regenerate even when up to date (overwrites the proxy)", False, default=False)],
           destructive={"param": "force", "equals": True}, simulate=_simulate_proxy, shelf=85,
           aliases=["proxy", "decimer", "lod"],
           doc_fr="Cree un proxy decime (purpose=proxy) des meshes d'un USD, en Python (pas de Houdini, aucune licence).",
           doc_en="Creates a decimated proxy (purpose=proxy) of the meshes of a USD, in Python (no Houdini, no license).")
def generate_proxy(ctx, inputs, params):
    from flux_actions.runner import run_generate_proxy_action

    a = _proxy_args(ctx, inputs, params)
    if not a["source"].is_file():
        raise NodeError(f"USD source introuvable : {a['source']}")
    out = run_generate_proxy_action(a["source"], a["out"], a["target_reduction"], a["min_tris"], a["force"],
                                    logger=_CtxLogger(ctx))
    if out is None:
        raise NodeError(f"Generation du proxy echouee pour {a['source']} (voir le journal du node)")
    return {"proxy_path": out.get("proxy_path"), "mesh_count": int(out.get("meshes") or 0),
            "tri_count": int(out.get("tris_out") or 0)}


# -- flux.usd_check / usd_flatten ---------------------------------------------------

_USD_EXTS = (".usd", ".usda", ".usdc")


@flow_node("flux.usd_check", "UsdCheck", icon="ShieldCheck",
           inputs=[_EXEC, port("source", "path", "USD publie", "Published USD", "assets/CHR/HERO/HERO_LAST.usd",
                               required=True)],
           outputs=[*_EXITS, port("issues", "list[str]", "Ce qui ne va pas", "What is wrong"),
                    port("count", "int", "Nombre de problemes", "Number of issues", 0),
                    port("ok", "bool", "Aucun probleme", "No issue", True)],
           shelf=86, aliases=["usd", "controle", "validate", "check"],
           doc_fr="Lance le controle USD de FLUX sur un USD publie et liste ce qui ne va pas. Lecture.",
           doc_en="Runs the FLUX USD check on a published USD and lists what is wrong. Read only.")
def usd_check(ctx, inputs, params):
    source = as_path(ctx, inputs.get("source"), "USD")
    if not source.is_file():
        raise NodeError(f"USD introuvable : {source}")
    out = _run_v1(ctx, "usd_check", {"source": str(source)})
    issues = [str(i) for i in out.get("issues") or []]
    return {"issues": issues, "count": len(issues), "ok": not issues}


def _flatten_args(ctx, inputs, params) -> Tuple[Path, Path, bool]:
    source = as_path(ctx, inputs.get("source"), "USD source")
    dest = as_path(ctx, inputs.get("dest"), "USD aplati")
    if dest.suffix.lower() not in _USD_EXTS:
        raise NodeError(f"dest : extension USD attendue ({', '.join(_USD_EXTS)}), recu `{dest.name}`",
                        code="E_PARAM_INVALID")
    overwrite = as_bool(params.get("overwrite"), False)
    if dest.exists():
        if not overwrite:
            raise NodeError(f"Refus : `{dest}` existe deja (overwrite pour ecraser)", code="E_EXISTS")
        check_destructive_target(dest)
    return source, dest, overwrite


def _unresolved(source: Path) -> List[str]:
    """Asset paths the stage of *source* points to but that do not resolve (T1: a shot stage
    whose character LAST was archived flattens without it, silently). Read only."""
    from pxr import UsdUtils

    try:
        _layers, _assets, missing = UsdUtils.ComputeAllDependencies(str(source))
    except Exception:  # noqa: BLE001 - an unreadable stage is reported by the flatten itself
        return []
    return sorted({str(m).replace("\\", "/") for m in missing})


def _simulate_flatten(ctx, inputs, params):
    source, dest, _overwrite = _flatten_args(ctx, inputs, params)
    text = f"aplatirait {source} vers {dest}" + (" (ecrase l'existant)" if dest.exists() else "")
    lines = [_line("flatten", text, dest)]
    missing: List[str] = []
    if not source.is_file():
        lines.append(_line("warn", f"{source} n'existe pas encore", source))
    else:
        missing = _unresolved(source)
        lines += [_line("warn", f"reference introuvable, absente du fichier aplati : {m}", m) for m in missing]
    return {"lines": lines, "outputs": {"path": str(dest), "missing": missing, "complete": not missing}}


@flow_node("flux.usd_flatten", "UsdFlatten", icon="Layers",
           inputs=[_EXEC,
                   port("source", "path", "USD source", "Source USD", "shot/SEQ010/SH010/stage.usda", required=True),
                   port("dest", "path", "USD aplati (.usda / .usdc)", "Flattened USD (.usda / .usdc)",
                        "deliver/SH010_flat.usdc", required=True)],
           outputs=[*_EXITS, port("path", "path", "Fichier ecrit", "Written file"),
                    port("missing", "list[str]", "References introuvables, absentes du fichier aplati",
                         "References that do not resolve, missing from the flattened file",
                         ["assets/chara/HERO/usd/HERO_LAST.usda"]),
                    port("complete", "bool", "Toutes les references ont ete trouvees", "Every reference was found",
                         True)],
           params=[port("overwrite", "bool", "Ecraser dest s'il existe", "Overwrite dest when it exists", False,
                        default=False)],
           destructive={"param": "overwrite", "equals": True}, simulate=_simulate_flatten, shelf=87,
           aliases=["flatten", "aplatir", "usd"],
           doc_fr="Aplatit un stage USD (couches, references, variantes) en un seul fichier. N'ecrase qu'avec overwrite.",
           doc_en="Flattens a USD stage (layers, references, variants) into one file. Overwrites only with overwrite.")
def usd_flatten(ctx, inputs, params):
    source, dest, _overwrite = _flatten_args(ctx, inputs, params)
    if not source.is_file():
        raise NodeError(f"USD source introuvable : {source}")
    out = _run_v1(ctx, "usd_flatten", {"source": str(source), "destination": str(dest)})
    missing = _unresolved(source)
    for m in missing:
        ctx.log(f"reference introuvable, absente du fichier aplati : {m}", "warn")
    return {"path": out.get("path") or str(dest), "missing": missing, "complete": not missing}


# -- flux.refresh_component / refresh_shot_stage ------------------------------------

def _refresh_args(ctx, inputs, params) -> Tuple[Path, str, str]:
    folder = as_path(ctx, inputs.get("folder"), "dossier du publish")
    base = _required_text(params.get("base"), "base")
    ext = _text(params.get("ext")) or ".usd"
    return folder, base, ext if ext.startswith(".") else f".{ext}"


def _refresh_node(key: str, verb_fr: str):
    def simulate(ctx, inputs, params):
        folder, base, ext = _refresh_args(ctx, inputs, params)
        return {"lines": [_line("refresh", f"{verb_fr} depuis {folder} ({base}{ext})", folder)],
                "outputs": {"updated": True}}

    def body(ctx, inputs, params):
        folder, base, ext = _refresh_args(ctx, inputs, params)
        if not folder.is_dir():
            raise NodeError(f"Dossier du publish introuvable : {folder}")
        out = _run_v1(ctx, key, {"folder": str(folder), "base": base, "ext": ext})
        return {"updated": bool(out.get("updated"))}

    return simulate, body


_REFRESH_PORTS = dict(
    inputs=[_EXEC, port("folder", "dir", "Dossier du publish", "Publish folder", "assets/CHR/HERO/mod/null",
                        required=True)],
    outputs=[*_EXITS, port("updated", "bool", "Quelque chose a ete mis a jour", "Something was updated", True)],
    params=[port("base", "str", "Nom de base du publish", "Publish base name", "CHAR_MOD_HERO_null", required=True),
            port("ext", "str", "Extension", "Extension", ".usd", default=".usd")],
)

_sim_component, _body_component = _refresh_node("refresh_component", "mettrait a jour le component")
refresh_component = flow_node(
    "flux.refresh_component", "RefreshComponent", icon="RefreshCcw", **_REFRESH_PORTS,
    effect=True, simulate=_sim_component, shelf=88, aliases=["component", "usd asset", "mettre a jour"],
    doc_fr="Met a jour le component USD de l'asset depuis un dossier de publish, comme apres un publish.",
    doc_en="Updates the asset USD component from a publish folder, like after a publish.")(_body_component)

_sim_stage, _body_stage = _refresh_node("refresh_shot_stage", "regenererait le stage du shot")
refresh_shot_stage = flow_node(
    "flux.refresh_shot_stage", "RefreshShotStage", icon="RefreshCcw", **_REFRESH_PORTS,
    effect=True, simulate=_sim_stage, shelf=89, aliases=["stage", "shot stage", "usd plan"],
    doc_fr="Regenere le stage USD du plan depuis un dossier de publish d'un departement de plan.",
    doc_en="Regenerates the shot USD stage from a publish folder of a shot department.")(_body_stage)
