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


def _result(path: Path, ext: str, user: str) -> Dict[str, Any]:
    from flux_flows.nodes.flux import publish_record

    _folder, version = next_version_of_existing(path, ext)
    record = publish_record(path, user=user)
    record["version"] = version
    return {"publish": record, "path": str(path), "version": version}


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
        empty = {"publish": None, "path": "", "version": 0}
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
                "outputs": {"publish": None, "path": str(target), "version": version}}
    return simulate


_OUTS = [dc.THEN, dc.ERR, port("publish", "publish", "Le publish (PublishFields pour le lire)", "The publish"),
         port("path", "path", "Fichier LAST publie", "Published LAST file"),
         port("version", "int", "Version ecrite", "Written version", 3)]


@flow_node("dcc.may_publish_core", "mayPublishCore", icon="PackagePlus", internal=True,
           inputs=[dc.EXEC, dc.session_port("maya", "Maya"),
                   port("name", "str", "Nom FLUX du publish (tokens, sans version)", "FLUX publish name (tokens, no version)",
                        "CHAR_MODEL_chair_null", required=True)],
           outputs=_OUTS,
           params=[port("format", "str", "Extension : .ma .mb .abc .fbx .obj .usd", "Extension", ".ma", default=".ma"),
                   port("scope", "str", "scene ou selection", "scene or selection", "scene", default="scene",
                        choices=("scene", "selection")),
                   _DESCRIPTION, _FRAMES,
                   port("options", "dict", "Options d'export du Publisher", "Publisher export options", {}), _PROJECT],
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
    fr = dc.frame_range(params.get("frame_range"))
    user = str((ctx.context or {}).get("user") or "")
    dest = run_maya_publish_action(base_name=name, extension=ext, scope=str(params.get("scope") or "scene"),
                                   project_path=project_path, description=str(params.get("description") or ""),
                                   user=user, project_name=project, port=int(s.port),
                                   frame_range=list(fr[:2]) if fr else None, options=params.get("options") or None)
    if dest is None:
        raise NodeError("publish Maya echoue (voir le journal FLUX)")
    return _result(Path(dest), ext, user)


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
    name = str(inputs.get("name") or "").strip() or (node.rsplit("/", 1)[-1] if node else "")
    if not name:
        raise NodeError("houPublish attend `name` ou `node`")
    ext = _ext(params.get("format"))
    project, project_path = _project(ctx, params)
    fr = dc.frame_range(params.get("frame_range"))
    user = str((ctx.context or {}).get("user") or "")
    got = run_houdini_publish_action(base_name=name, extension=ext, project_path=project_path,
                                     description=str(params.get("description") or ""), user=user, project_name=project,
                                     rop_node_path=node, is_sequence=bool(params.get("sequence")),
                                     frame_range=list(fr) if fr else None, options=params.get("options") or None)
    if not got or not got.get("ok"):
        raise NodeError("publish Houdini echoue (voir le journal FLUX)")
    from flux_flows.nodes.flux import publish_record

    record = publish_record(got["path"], user=user)
    record["version"] = got.get("version")
    return {"publish": record, "path": str(got["path"]), "version": got.get("version") or 0}
