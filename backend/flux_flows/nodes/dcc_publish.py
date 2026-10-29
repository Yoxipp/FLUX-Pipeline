# dcc_publish.py — mayPublish / houPublish, the publish black boxes (02_NODES §8, 01 §13,
# decision 9). P6a. Registered as the cores dcc.<p>_publish_core of the locked subflows
# shipped/dcc/<soft>/<p>_publish.flow.yml (node_type dcc.<p>_publish, dcc_nodes.py).
#
# They call the SAME code as the Publisher, nothing is cut: run_maya_publish_action /
# run_houdini_publish_action (flux_actions/runner.py, publish_core.py untouched). The runner
# calls asyncio.run: the body is a plain function, run in the FLOWS pool, never on the loop.
# log_publish (inside) emits event.on_publish (P5). Never destructive (immutable vNNN + LAST).
# Live only: the Maya action talks to the commandPort of the session; the Houdini action
# cooks in the instance chosen in FLUX (its singleton client), so a session on another
# Houdini instance is refused instead of publishing from the wrong scene.
# The dry run computes the destination (resolve_publish_path, read only) and the next version.
# P8 (ADR 0070): a run started by flux_flows/publish_runner.py carries a probe dict in its
# context; each core calls core_starting() right before the Publisher function, so the runner
# knows a failure came before the core (fallback to v1) or after (never: no double publish).
# No engine timeout for the cores (engine._timeout, n°1): the soft client's own timeout stays.

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flux_flows.nodes import dcc_common as dc
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

_DESCRIPTION = port("description", "str", "Description du publish (journal)", "Publish description (log)",
                    "retopo finie", default="")
_FRAMES = port("frame_range", "str", "Plage (caches, anim) : 1001-1050", "Range (caches, anim): 1001-1050", "1001-1050")
_PROJECT = port("project", "str", "Projet (vide = celui du flow)", "Project (empty = the flow's)", "MYPROJ")


PROBE_KEY = "publish_probe"       # run context key: shared dict {core_started, refused}
REFUSED_CODE = "E_PUBLISH_REFUSED"


def core_starting(ctx) -> None:
    """Right before the Publisher function: a refused publish stops, else the core is marked started."""
    probe = (ctx.context or {}).get(PROBE_KEY)
    if not isinstance(probe, dict):
        return
    if probe.get("refused"):
        raise NodeError(str(probe["refused"]), code=REFUSED_CODE)
    probe["core_started"] = True


def _user(ctx) -> str:
    """User of the run, else the FLUX user, else unknown (same as the v1 routes, n°5)."""
    user = str((ctx.context or {}).get("user") or "").strip()
    if user:
        return user
    try:
        from core import config

        return str(config.get_current_user() or "").strip() or "unknown"
    except Exception:  # noqa: BLE001 - no FLUX config (tests, first launch)
        return "unknown"


def _logger(ctx):
    from flux_flows.nodes.flux import _CtxLogger

    return _CtxLogger(ctx)


def _project(ctx, params) -> Tuple[str, Path]:
    from core.paths import get_project_path

    name = str(params.get("project") or (ctx.context or {}).get("project") or "").strip()
    if not name:
        raise NodeError("Pas de projet : lance le flow dans un projet ou renseigne `project`")
    path = Path(get_project_path(name))
    if not path.is_dir():
        raise NodeError(f"Projet introuvable : {name}")
    return name, path


def _ext(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise NodeError("`format` vide (ex. .ma, .abc, .usd)")
    return text if text.startswith(".") else "." + text


def next_version(project_path: Path, name: str, ext: str) -> Tuple[Optional[Path], int]:
    """(destination folder, next version number) of *name* + *ext*, read only."""
    from features.publisher.publish_core import resolve_publish_path

    folder = resolve_publish_path(project_path, f"{name}{ext}")
    if folder is None:
        return None, 0
    base = re.sub(r"_(LAST|v\d+)$", "", name, flags=re.IGNORECASE)
    nums = [int(m.group(1)) for f in (folder.glob(f"{base}_v*{ext}") if folder.is_dir() else [])
            if (m := re.match(rf"^{re.escape(base)}_v(\d+){re.escape(ext)}$", f.name, re.IGNORECASE))]
    return folder, (max(nums) + 1 if nums else 1)


def _result(path: Path, ext: str, user: str, planned: int = 0) -> Dict[str, Any]:
    from flux_flows.nodes.flux import publish_record

    _folder, version = next_version_of_existing(path, ext)
    version = version or planned or None
    record = publish_record(path, user=user)
    record["version"] = version
    return {"publish": record, "path": str(path), "version": version, "files": [str(path)], "warnings": []}


def version_of(path: Any) -> Optional[int]:
    """Version of a published file: its own _vNNN, else the highest vNNN next to it (n°6)."""
    if not path:
        return None
    p = Path(str(path))
    m = re.search(r"_v(\d+)", p.name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    try:
        _folder, found = next_version_of_existing(p, "".join(p.suffixes))
    except OSError:
        return None
    return found or None


def next_version_of_existing(path: Path, ext: str) -> Tuple[Path, int]:
    """Version just written next to the LAST *path* (highest vNNN of its base)."""
    folder = path.parent
    base = re.sub(r"_(LAST|v\d+)$", "", path.name[: len(path.name) - len(ext)] if path.name.lower().endswith(ext)
                  else path.stem, flags=re.IGNORECASE)
    nums = [int(m.group(1)) for f in folder.glob(f"{base}_v*") if (m := re.search(r"_v(\d+)", f.name))]
    return folder, (max(nums) if nums else 0)


def _sim(soft: str):
    def simulate(ctx, inputs, params):
        name = str(inputs.get("name") or (inputs.get("node") or "").rsplit("/", 1)[-1] or "")
        empty = {"publish": None, "path": "", "version": 0, "files": [], "warnings": []}
        if inputs.get("session") is None:
            return {"lines": [{"kind": "skip", "text_fr": dc.SKIPPED_FR}], "outputs": empty}
        try:
            ext = _ext(params.get("format"))
            _proj, project_path = _project(ctx, params)
            folder, version = next_version(project_path, name, ext)
        except NodeError as exc:
            return {"lines": [{"kind": "publish", "text_fr": f"ne publierait pas : {exc.message}"}], "outputs": empty}
        if folder is None:
            return {"lines": [{"kind": "publish", "text_fr": f"ne publierait pas : nom `{name}` hors nomenclature"}],
                    "outputs": empty}
        target = folder / f"{name}_v{version:03d}{ext}"
        return {"lines": [{"kind": "publish", "text_fr": f"publierait {name} v{version:03d} ({soft})",
                           "path": str(target)}],
                "outputs": {"publish": None, "path": str(target), "version": version, "files": [str(target)],
                            "warnings": []}}
    return simulate


_OUTS = [dc.THEN, dc.ERR, port("publish", "publish", "Le publish (PublishFields pour le lire)", "The publish"),
         port("path", "path", "Fichier LAST publie", "Published LAST file"),
         port("version", "int", "Version ecrite", "Written version", 3),
         port("files", "list[path]", "Tous les fichiers publies", "Every published file"),
         port("warnings", "list[str]", "Avertissements du publish (rendus au Publisher)",
              "Publish warnings (shown in the Publisher)")]


@flow_node("dcc.may_publish_core", "mayPublishCore", icon="PackagePlus", internal=True,
           inputs=[dc.EXEC, dc.session_port("maya", "Maya"),
                   port("name", "str", "Nom FLUX du publish (tokens, sans version)", "FLUX publish name (tokens, no version)",
                        "CHAR_MODEL_chair_null", required=True)],
           outputs=_OUTS,
           params=[port("format", "str", "Extension : .ma .mb .abc .fbx .obj .usd", "Extension", ".ma", default=".ma"),
                   port("scope", "str", "scene ou selection", "scene or selection", "scene", default="scene",
                        choices=("scene", "selection")),
                   _DESCRIPTION, _FRAMES,
                   port("options", "dict", "Options d'export du Publisher", "Publisher export options", {}),
                   port("port", "int", "Port Maya vise (0 = celui de la session)", "Target Maya port (0 = the "
                        "session's)", 7001, default=0), _PROJECT],
           session="maya", live_only=True, effect=True, simulate=_sim("maya"), shelf=202,
           aliases=["publier", "publish", "version", "last"],
           doc_fr="Publie la scene ou la selection de Maya exactement comme le Publisher (vNNN immuable + LAST, "
                  "activite, flows OnPublish). Session Live.",
           doc_en="Publishes the Maya scene or selection exactly like the Publisher (immutable vNNN + LAST, activity, "
                  "OnPublish flows). Live session.")
def may_publish(ctx, inputs, params):
    from flux_actions.runner import run_maya_publish_action

    s = dc.need_session(ctx, inputs)
    if not s.live or not s.port:
        raise NodeError("mayPublish demande une session Live (commandPort)")
    name = dc.text_param(ctx, inputs.get("name"), "name")
    ext = _ext(params.get("format"))
    project, project_path = _project(ctx, params)
    fr = maya_frame_range(params.get("frame_range"))
    user = _user(ctx)
    target = int(params.get("port") or 0) or int(s.port)   # n°14: the instance the Publisher targets
    _folder, planned = next_version(project_path, name, ext)
    core_starting(ctx)
    dest = run_maya_publish_action(base_name=name, extension=ext, scope=str(params.get("scope") or "scene"),
                                   project_path=project_path, description=str(params.get("description") or ""),
                                   user=user, project_name=project, port=target, frame_range=fr,
                                   options=params.get("options") or None, logger=_logger(ctx))
    if dest is None:
        raise NodeError("publish Maya echoue (voir le journal FLUX)")
    return _result(Path(dest), ext, user, planned)


def maya_frame_range(value: Any) -> Optional[list]:
    """[start, end, step] for Maya, the step kept as a float (0.5 = sub frames, n°12); empty = None."""
    if value in (None, "", []):
        return None
    parts = list(value) if isinstance(value, (list, tuple)) else \
        str(value).replace(",", " ").replace("-", " ").split()
    try:
        nums = [float(p) for p in parts]
    except (TypeError, ValueError):
        raise NodeError(f"frame_range invalide `{value}` (ex. 1001-1050)") from None
    if len(nums) == 2:
        nums.append(1.0)
    if len(nums) != 3 or nums[2] <= 0:
        raise NodeError(f"frame_range invalide `{value}` (ex. 1001-1050)")
    return [int(nums[0]), int(nums[1]), nums[2]]


@flow_node("dcc.hou_publish_core", "houPublishCore", icon="PackagePlus", internal=True,
           inputs=[dc.EXEC, dc.session_port("houdini", "Houdini"),
                   port("name", "str", "Nom FLUX du publish (vide = nom du node)", "FLUX publish name (empty = node name)",
                        "FX_SIM_smoke_null"),
                   port("node", "dcc_node", "ROP ou node a publier (vide = selection)", "ROP or node to publish "
                        "(empty = selection)", "/out/smoke_cache")],
           outputs=_OUTS,
           params=[port("format", "str", "Extension : .bgeo.sc .abc .usd .vdb .hip ...", "Extension", ".abc", default=".abc"),
                   _DESCRIPTION, _FRAMES,
                   port("sequence", "bool", "Une image par frame (sequence)", "One file per frame (sequence)", False,
                        default=False),
                   port("options", "dict", "Parms du ROP (comme le Publisher)", "ROP parms (like the Publisher)", {}),
                   port("frame_padding", "int", "Chiffres du numero de frame (sequence)", "Frame number digits "
                        "(sequence)", 4, default=4),
                   port("attr_filter", "dict", "Filtre d'attributs {mode: keep|remove, names: [...]}",
                        "Attribute filter {mode: keep|remove, names: [...]}", {}),
                   _PROJECT],
           session="houdini", live_only=True, effect=True, simulate=_sim("houdini"), shelf=184,
           aliases=["publier", "publish", "version", "last", "rop"],
           doc_fr="Publie un ROP (ou la scene .hip) de Houdini exactement comme le Publisher (vNNN immuable + LAST, "
                  "activite, flows OnPublish). Session Live sur l'instance choisie dans FLUX.",
           doc_en="Publishes a Houdini ROP (or the .hip scene) exactly like the Publisher (immutable vNNN + LAST, "
                  "activity, OnPublish flows). Live session on the instance chosen in FLUX.")
def hou_publish(ctx, inputs, params):
    from core.dcc_instances import InstanceLostError, resolve_port
    from flux_actions.runner import run_houdini_publish_action

    s = dc.need_session(ctx, inputs)
    if not s.live or not s.port:
        raise NodeError("houPublish demande une session Live")
    try:
        active = resolve_port("Houdini")
    except InstanceLostError as exc:
        raise NodeError(str(exc)) from None
    if int(active) != int(s.port):
        raise NodeError(f"houPublish publie dans le Houdini choisi dans FLUX (port {active}), pas :{s.port} : "
                        "choisis cette instance dans FLUX ou utilise pick active")
    node = str(inputs.get("node") or "") or None
    name = str(inputs.get("name") or "").strip()
    if not name:   # n°11: required, like in the Publisher
        raise NodeError("houPublish attend `name` : le nom FLUX du publish (tokens, sans version)")
    ext = _ext(params.get("format"))
    project, project_path = _project(ctx, params)
    fr = dc.frame_range(params.get("frame_range"))
    user = _user(ctx)
    padding = params.get("frame_padding")
    core_starting(ctx)
    got = run_houdini_publish_action(base_name=name, extension=ext, project_path=project_path,
                                     description=str(params.get("description") or ""), user=user, project_name=project,
                                     rop_node_path=node, is_sequence=bool(params.get("sequence")),
                                     frame_range=list(fr) if fr else None,
                                     frame_padding=int(padding) if padding not in (None, "") else None,
                                     options=params.get("options") or None,
                                     attr_filter=params.get("attr_filter") or None, logger=_logger(ctx))
    if not got or not got.get("ok"):
        raise NodeError("publish Houdini echoue (voir le journal FLUX)")
    from flux_flows.nodes.flux import publish_record

    record = publish_record(got["path"], user=user)
    version = got.get("version") or version_of(got["path"])
    record["version"] = version
    return {"publish": record, "path": str(got["path"]), "version": version, "files": [str(got["path"])],
            "warnings": [str(w) for w in got.get("warnings") or []]}


# -- P6b: Nuke, Painter, Designer, Marvelous, ZBrush, Mari (01 §13 table) --------------------
# Each calls the soft's publish function of the Publisher in a worker thread. Those functions
# talk to the singleton client on the BASE port of the soft: a session on another instance
# is refused (same rule as houPublish) instead of publishing from the wrong one.

def _base_port_only(session, soft: str, label: str) -> None:
    from flux_flows.bridges import softs

    if not session.live:
        raise NodeError(f"{label}Publish demande une session Live")
    if soft in ("marvelous",):
        return
    base = softs.port_range(soft).start
    if session.port and int(session.port) != base:
        raise NodeError(f"{label}Publish publie dans l'instance du port {base} (celle du Publisher), pas :{session.port}")


def _from_result(res: Any, user: str) -> Dict[str, Any]:
    from flux_flows.nodes.flux import publish_record

    if not isinstance(res, dict) or not res.get("ok"):
        raise NodeError(f"publish echoue : {(res or {}).get('error') or 'voir le journal FLUX'}")
    paths = [str(p) for p in (res.get("published") or [])]
    path = str(res.get("path") or (paths[0] if paths else ""))
    record = publish_record(path, user=user) if path else None
    try:   # n°6: the function's version, else the record's, else the file's; never 0 (None = unknown)
        version = int(res.get("version") or (record or {}).get("version") or 0) or version_of(path)
    except (TypeError, ValueError):
        version = version_of(path)
    if record is not None:
        record["version"] = version
    return {"publish": record, "path": path, "version": version, "files": paths or ([path] if path else []),
            "warnings": [str(w) for w in res.get("warnings") or []]}


def _texture_tokens(inputs, params) -> Dict[str, Any]:
    out = {"class_tok": str(inputs.get("class") or "").strip(), "task_tok": str(inputs.get("task") or "").strip(),
           "name_tok": str(inputs.get("name") or "").strip(), "instance": str(params.get("instance") or "null")}
    if not (out["class_tok"] and out["task_tok"] and out["name_tok"]):
        raise NodeError("class, task et name sont obligatoires (tokens FLUX)")
    return out


_TEX_IN = [port("class", "str", "Token CLASS", "CLASS token", "PROP", required=True),
           port("task", "str", "Token TYPE (tache)", "TYPE token (task)", "TEXTURE", required=True),
           port("name", "str", "Token NAME", "NAME token", "chair", required=True)]
_TEX_OUTS = _OUTS


def _sim_soft(label: str):
    def simulate(ctx, inputs, params):
        if inputs.get("session") is None:
            return {"lines": [{"kind": "skip", "text_fr": dc.SKIPPED_FR}],
                    "outputs": {"publish": None, "path": "", "version": 0, "files": [], "warnings": []}}
        name = inputs.get("name") or ""
        return {"lines": [{"kind": "publish", "text_fr": f"publierait {name} depuis {label} (vNNN + LAST)"}],
                "outputs": {"publish": None, "path": "", "version": 0, "files": [], "warnings": []}}
    return simulate


@flow_node("dcc.nk_publish_core", "nkPublishCore", icon="PackagePlus", internal=True,
           inputs=[dc.EXEC, dc.session_port("nuke", "Nuke"),
                   port("name", "str", "Nom FLUX du publish", "FLUX publish name", "SEQ010_SH010_COMP_main", required=True),
                   port("node", "dcc_node", "Node a ecrire (vide = selection)", "Node to write (empty = selection)", "Merge1")],
           outputs=_TEX_OUTS,
           params=[port("format", "str", "Extension (.exr, .png, .mov...)", "Extension", ".exr", default=".exr"),
                   _FRAMES, port("sequence", "bool", "Une image par frame", "One file per frame", True, default=False),
                   _DESCRIPTION, port("options", "dict", "Knobs du Write", "Write knobs", {}),
                   port("colorspace", "str", "Espace couleur du Write (vide = defaut FLUX)", "Write colorspace", "")],
           session="nuke", live_only=True, effect=True, simulate=_sim_soft("Nuke"), shelf=219,
           doc_fr="Coeur de nkPublish : publish_from_nuke (Publisher Nuke).", doc_en="Core of nkPublish.")
def nk_publish(ctx, inputs, params):
    from dcc.nuke.nuke_publish import publish_from_nuke

    s = dc.need_session(ctx, inputs)
    _base_port_only(s, "nuke", "nk")
    project, _path = _project(ctx, params)
    fr = dc.frame_range(params.get("frame_range"))
    core_starting(ctx)
    res = publish_from_nuke(project, dc.text_param(ctx, inputs.get("name"), "name"), _ext(params.get("format")),
                            options=params.get("options") or None, is_sequence=bool(params.get("sequence")),
                            frame_range=(fr[0], fr[1]) if fr else None, node_name=str(inputs.get("node") or "") or None,
                            description=str(params.get("description") or ""), user=_user(ctx),
                            colorspace=str(params.get("colorspace") or "") or None)
    return _from_result(res, _user(ctx))


@flow_node("dcc.sp_publish_core", "spPublishCore", icon="PackagePlus", internal=True,
           inputs=[dc.EXEC, dc.session_port("painter", "Painter"), *_TEX_IN],
           outputs=_TEX_OUTS,
           params=[port("instance", "str", "Token INSTANCE", "INSTANCE token", "null", default="null"),
                   port("preset", "str", "Preset d'export", "Export preset", "PBR Metallic Roughness",
                        default="PBR Metallic Roughness"),
                   port("format", "str", "Format", "Format", "png", default="png"),
                   port("bit_depth", "str", "Profondeur", "Bit depth", "8", default="8"),
                   port("size", "int", "Largeur (vide = celle du texture set)", "Width", 2048),
                   port("maps", "list[str]", "Maps (vide = toutes)", "Maps (empty = all)", []),
                   port("conform_tx", "bool", "Ecrire aussi les .tx", "Also write the .tx", False, default=False),
                   _DESCRIPTION, port("extra", "dict", "Autres arguments de publish_painter", "Other publish_painter "
                                      "arguments", {})],
           session="painter", live_only=True, effect=True, simulate=_sim_soft("Painter"), shelf=233,
           doc_fr="Coeur de spPublish : publish_painter (Publisher Painter).", doc_en="Core of spPublish.")
def sp_publish(ctx, inputs, params):
    from dcc.substance_painter.substance_export import publish_painter

    s = dc.need_session(ctx, inputs)
    _base_port_only(s, "painter", "sp")
    project, _path = _project(ctx, params)
    core_starting(ctx)
    res = publish_painter(project, **_texture_tokens(inputs, params),
                          preset=str(params.get("preset") or "PBR Metallic Roughness"),
                          file_format=str(params.get("format") or "png"), bit_depth=str(params.get("bit_depth") or "8"),
                          conform_tx=bool(params.get("conform_tx")), description=str(params.get("description") or ""),
                          user=_user(ctx), size=params.get("size") or None, maps=params.get("maps") or None,
                          **(params.get("extra") or {}))
    return _from_result(res, _user(ctx))


@flow_node("dcc.sd_publish_core", "sdPublishCore", icon="PackagePlus", internal=True,
           inputs=[dc.EXEC, dc.session_port("designer", "Designer"), *_TEX_IN],
           outputs=_TEX_OUTS,
           params=[port("instance", "str", "Token INSTANCE", "INSTANCE token", "null", default="null"),
                   port("format", "str", "Format des maps", "Map format", "png", default="png"),
                   port("size", "int", "Largeur", "Width", 2048), port("bit_depth", "str", "Profondeur", "Bit depth", "16"),
                   port("maps", "bool", "Publier les maps", "Publish the maps", True, default=True),
                   port("sbsar", "bool", "Publier le .sbsar", "Publish the .sbsar", False, default=False),
                   port("sbs", "bool", "Publier le .sbs", "Publish the .sbs", False, default=False),
                   port("conform_tx", "bool", "Ecrire aussi les .tx", "Also write the .tx", False, default=False),
                   _DESCRIPTION, port("extra", "dict", "Autres arguments de publish_designer", "Other publish_designer "
                                      "arguments", {})],
           session="designer", live_only=True, effect=True, simulate=_sim_soft("Designer"), shelf=244,
           doc_fr="Coeur de sdPublish : publish_designer (Publisher Designer).", doc_en="Core of sdPublish.")
def sd_publish(ctx, inputs, params):
    from dcc.substance_designer.designer_export import publish_designer

    s = dc.need_session(ctx, inputs)
    _base_port_only(s, "designer", "sd")
    project, _path = _project(ctx, params)
    core_starting(ctx)
    res = publish_designer(project, **_texture_tokens(inputs, params), file_format=str(params.get("format") or "png"),
                           size=params.get("size") or None, bit_depth=str(params.get("bit_depth") or "") or None,
                           maps=params.get("maps", True) is not False, sbsar=bool(params.get("sbsar")),
                           sbs=bool(params.get("sbs")), conform_tx=bool(params.get("conform_tx")),
                           description=str(params.get("description") or ""), user=_user(ctx),
                           **(params.get("extra") or {}))
    return _from_result(res, _user(ctx))


@flow_node("dcc.mvd_publish_core", "mvdPublishCore", icon="PackagePlus", internal=True,
           inputs=[dc.EXEC, dc.session_port("marvelous", "Marvelous"),
                   port("name", "str", "Nom FLUX du publish", "FLUX publish name", "CHAR_CLOTH_dress_null", required=True)],
           outputs=_TEX_OUTS,
           params=[port("format", "str", "abc, obj, fbx, usd, zprj", "Format", "abc", default="abc"),
                   port("options", "dict", "Options d'export", "Export options", {}),
                   port("with_zprj", "bool", "Publier aussi le .zprj", "Also publish the .zprj", False, default=False),
                   _DESCRIPTION],
           session="marvelous", live_only=True, effect=True, simulate=_sim_soft("Marvelous"), shelf=254,
           doc_fr="Coeur de mvdPublish : publish_marvelous (Publisher Marvelous).", doc_en="Core of mvdPublish.")
def mvd_publish(ctx, inputs, params):
    from dcc.marvelous.marvelous_export import publish_marvelous

    s = dc.need_session(ctx, inputs)
    _base_port_only(s, "marvelous", "mvd")
    project, _path = _project(ctx, params)
    core_starting(ctx)
    res = publish_marvelous(project, dc.text_param(ctx, inputs.get("name"), "name"),
                            file_format=str(params.get("format") or "abc"), options=params.get("options") or None,
                            with_zprj=bool(params.get("with_zprj")), description=str(params.get("description") or ""),
                            user=_user(ctx))
    return _from_result(res, _user(ctx))


@flow_node("dcc.zb_publish_core", "zbPublishCore", icon="PackagePlus", internal=True,
           inputs=[dc.EXEC, dc.session_port("zbrush", "ZBrush"),
                   port("name", "str", "Nom FLUX du publish", "FLUX publish name", "CHAR_SCULPT_head_null", required=True)],
           outputs=_TEX_OUTS,
           params=[port("format", "str", ".ztl, .obj ou .fbx", ".ztl, .obj or .fbx", ".ztl", default=".ztl"),
                   port("options", "dict", "Options d'export", "Export options", {}), _DESCRIPTION],
           session="zbrush", live_only=True, effect=True, simulate=_sim_soft("ZBrush"), shelf=263,
           doc_fr="Coeur de zbPublish : publish_zbrush (Publisher ZBrush) ; ZBrush toujours relache.",
           doc_en="Core of zbPublish; ZBrush always released.")
def zb_publish(ctx, inputs, params):
    from dcc.zbrush.client import zbrush_client
    from dcc.zbrush.zbrush_export import publish_zbrush

    s = dc.need_session(ctx, inputs)
    _base_port_only(s, "zbrush", "zb")
    project, project_path = _project(ctx, params)
    ctx.add_cleanup(lambda: zbrush_client.release(timeout=2.0))
    core_starting(ctx)
    try:
        res = publish_zbrush(project_path, dc.text_param(ctx, inputs.get("name"), "name"), _ext(params.get("format")),
                             params.get("options") or {}, str(params.get("description") or ""), _user(ctx),
                             project_name=project)
    finally:
        try:
            zbrush_client.release(timeout=2.0)
        except Exception:  # noqa: BLE001 - the run's cleanup tries again
            pass
    return _from_result(res, _user(ctx))


@flow_node("dcc.mari_publish_core", "mariPublishCore", icon="PackagePlus", internal=True,
           inputs=[dc.EXEC, dc.session_port("mari", "Mari"), *_TEX_IN],
           outputs=_TEX_OUTS,
           params=[port("instance", "str", "Token INSTANCE", "INSTANCE token", "null", default="null"),
                   port("format", "str", "Format (tif, exr, png)", "Format", "tif", default="tif"),
                   port("channels", "list[str]", "Channels (vide = tous)", "Channels (empty = all)", []),
                   port("conform_tx", "bool", "Ecrire aussi les .tx", "Also write the .tx", False, default=False),
                   _DESCRIPTION, port("extra", "dict", "Autres arguments de publish_mari", "Other publish_mari arguments",
                                      {})],
           session="mari", live_only=True, effect=True, simulate=_sim_soft("Mari"), shelf=273,
           doc_fr="Coeur de mariPublish : publish_mari (Publisher Mari).", doc_en="Core of mariPublish.")
def mari_publish(ctx, inputs, params):
    from dcc.mari.mari_export import publish_mari

    s = dc.need_session(ctx, inputs)
    _base_port_only(s, "mari", "mari")
    project, _path = _project(ctx, params)
    core_starting(ctx)
    res = publish_mari(project, **_texture_tokens(inputs, params), file_format=str(params.get("format") or "tif"),
                       conform_tx=bool(params.get("conform_tx")), description=str(params.get("description") or ""),
                       user=_user(ctx), channels=params.get("channels") or None, **(params.get("extra") or {}))
    return _from_result(res, _user(ctx))
