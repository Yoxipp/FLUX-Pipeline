# utility.py - general-purpose nodes for the action editor (B6, 2026-09-28).
#
# Small building blocks an artist wires into a brick: files, folders, text, JSON,
# USD, images, activity, component / shot stage refresh. Each one is a thin wrapper
# (no pipeline logic re-implemented) and runs inside FLUX: no DCC, no license.
# ``doc_fr`` is the French doc shown when the UI is in French.

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict

from flux_core import CommandBase, register


def _ctx(action_query: Any) -> Dict[str, Any]:
    return getattr(action_query.buffer, "context", {}) or {}


def _path(value: Any, action_query: Any) -> Path:
    """A path typed in the graph: relative = relative to the project folder."""
    p = Path(str(value))
    root = _ctx(action_query).get("project_path")
    return p if p.is_absolute() or not root else Path(root) / p


@register("project_context")
class ProjectContext(CommandBase):
    """Expose the run context (project folder, project name, user) as outputs."""
    doc_fr = "Donne le contexte du lancement (dossier du projet, nom du projet, utilisateur) en sorties."

    async def run(self, parameters, action_query, logger):
        ctx = _ctx(action_query)
        return {"project_path": ctx.get("project_path"), "project_name": ctx.get("project_name"),
                "user": ctx.get("user")}


@register("log_message")
class LogMessage(CommandBase):
    """Write a message in the FLUX log (debug a brick step by step)."""
    doc_fr = "Ecrit un message dans le log de FLUX (pour suivre une brique etape par etape)."
    parameters = {"text": {"type": "str", "label": "Message"},
                  "level": {"type": "select", "value": "info", "label": "Niveau (info, warning, error)"}}

    async def run(self, parameters, action_query, logger: logging.Logger):
        getattr(logger, str(parameters.get("level") or "info"), logger.info)("%s", parameters.get("text") or "")
        return {"text": parameters.get("text") or ""}


@register("format_text")
class FormatText(CommandBase):
    """Build a text from a template: "{name}_{version}" filled with the values dict."""
    doc_fr = "Construit un texte depuis un modele : \"{name}_{version}\" rempli avec le dict de valeurs."
    parameters = {"template": {"type": "str", "label": "Modele"},
                  "values": {"type": "dict", "value": {}, "label": "Valeurs"}}

    async def run(self, parameters, action_query, logger):
        values = {**_ctx(action_query), **(parameters.get("values") or {})}
        return {"text": str(parameters.get("template") or "").format(**values)}


@register("join_path")
class JoinPath(CommandBase):
    """Join a base folder and sub-parts into one path."""
    doc_fr = "Assemble un dossier de base et des sous-parties en un chemin."
    parameters = {"base": {"type": "str", "label": "Dossier de base"},
                  "parts": {"type": "list", "value": [], "label": "Sous-parties"}}

    async def run(self, parameters, action_query, logger):
        path = _path(parameters.get("base") or ".", action_query)
        for part in parameters.get("parts") or []:
            path = path / str(part)
        return {"path": str(path)}


@register("make_folder")
class MakeFolder(CommandBase):
    """Create a folder (and its parents); nothing happens when it exists."""
    doc_fr = "Cree un dossier (et ses parents) ; rien ne se passe s'il existe deja."
    parameters = {"path": {"type": "str", "label": "Dossier"}}

    async def run(self, parameters, action_query, logger):
        path = _path(parameters["path"], action_query)
        path.mkdir(parents=True, exist_ok=True)
        return {"path": str(path)}


@register("copy_file")
class CopyFile(CommandBase):
    """Copy a file or a folder. Refuses to overwrite unless asked."""
    doc_fr = "Copie un fichier ou un dossier. N'ecrase rien sauf si demande."
    parameters = {"source": {"type": "str", "label": "Source"},
                  "destination": {"type": "str", "label": "Destination (fichier ou dossier)"},
                  "overwrite": {"type": "bool", "value": False, "label": "Ecraser"}}

    async def run(self, parameters, action_query, logger):
        src = _path(parameters["source"], action_query)
        dst = _path(parameters["destination"], action_query)
        if dst.is_dir() and src.is_file():
            dst = dst / src.name
        if dst.exists() and not parameters.get("overwrite"):
            raise ValueError(f"existe deja : {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            await asyncio.to_thread(shutil.copytree, src, dst, dirs_exist_ok=bool(parameters.get("overwrite")))
        else:
            await asyncio.to_thread(shutil.copy2, src, dst)
        return {"path": str(dst)}


@register("move_file")
class MoveFile(CommandBase):
    """Move (or rename) a file or a folder. Never overwrites."""
    doc_fr = "Deplace (ou renomme) un fichier ou un dossier. N'ecrase jamais."
    parameters = {"source": {"type": "str", "label": "Source"},
                  "destination": {"type": "str", "label": "Destination"}}

    async def run(self, parameters, action_query, logger):
        src = _path(parameters["source"], action_query)
        dst = _path(parameters["destination"], action_query)
        if dst.is_dir():
            dst = dst / src.name
        if dst.exists():
            raise ValueError(f"existe deja : {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(src), str(dst))
        return {"path": str(dst)}


@register("list_files")
class ListFiles(CommandBase):
    """List the files of a folder matching a pattern (*.usd, *_LAST.*...)."""
    doc_fr = "Liste les fichiers d'un dossier qui correspondent a un motif (*.usd, *_LAST.*...)."
    parameters = {"folder": {"type": "str", "label": "Dossier"},
                  "pattern": {"type": "str", "value": "*", "label": "Motif"},
                  "recursive": {"type": "bool", "value": False, "label": "Sous-dossiers aussi"}}

    async def run(self, parameters, action_query, logger):
        folder = _path(parameters["folder"], action_query)
        pattern = parameters.get("pattern") or "*"
        walk = folder.rglob("*") if parameters.get("recursive") else folder.glob("*")
        files = sorted(str(p) for p in walk if p.is_file() and fnmatch.fnmatch(p.name, pattern))
        return {"files": files, "count": len(files), "first": files[0] if files else None}


@register("read_json")
class ReadJson(CommandBase):
    """Read a JSON file (config, log, production.json...)."""
    doc_fr = "Lit un fichier JSON (config, log, production.json...)."
    parameters = {"path": {"type": "str", "label": "Fichier JSON"}}

    async def run(self, parameters, action_query, logger):
        path = _path(parameters["path"], action_query)
        return {"data": json.loads(path.read_text(encoding="utf-8"))}


@register("write_json")
class WriteJson(CommandBase):
    """Write data to a JSON file (written next to it first, then swapped in)."""
    doc_fr = "Ecrit des donnees dans un fichier JSON (ecrit a cote puis remplace)."
    parameters = {"path": {"type": "str", "label": "Fichier JSON"},
                  "data": {"type": "any", "label": "Donnees"}}

    async def run(self, parameters, action_query, logger):
        path = _path(parameters["path"], action_query)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(parameters.get("data"), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return {"path": str(path)}


@register("write_text")
class WriteText(CommandBase):
    """Write a text file (note, report, readme...)."""
    doc_fr = "Ecrit un fichier texte (note, rapport, readme...)."
    parameters = {"path": {"type": "str", "label": "Fichier"},
                  "text": {"type": "text", "label": "Texte"},
                  "append": {"type": "bool", "value": False, "label": "Ajouter a la fin"}}

    async def run(self, parameters, action_query, logger):
        path = _path(parameters["path"], action_query)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a" if parameters.get("append") else "w", encoding="utf-8") as fh:
            fh.write(str(parameters.get("text") or ""))
        return {"path": str(path)}


@register("zip_folder")
class ZipFolder(CommandBase):
    """Zip a folder (delivery, backup before a risky change)."""
    doc_fr = "Zippe un dossier (livraison, sauvegarde avant une modif risquee)."
    parameters = {"folder": {"type": "str", "label": "Dossier"},
                  "destination": {"type": "str", "label": "Zip (sans .zip)"}}

    async def run(self, parameters, action_query, logger):
        folder = _path(parameters["folder"], action_query)
        dest = _path(parameters.get("destination") or str(folder), action_query)
        out = await asyncio.to_thread(shutil.make_archive, str(dest), "zip", str(folder))
        return {"zip_path": out}


@register("usd_flatten")
class UsdFlatten(CommandBase):
    """Flatten a USD stage (all layers, references, variants) into one file."""
    doc_fr = "Aplatit un stage USD (couches, references, variantes) en un seul fichier."
    parameters = {"source": {"type": "str", "label": "USD source"},
                  "destination": {"type": "str", "label": "USD aplati (.usda / .usdc)"}}

    async def run(self, parameters, action_query, logger):
        from pxr import Usd

        src = _path(parameters["source"], action_query)
        dst = _path(parameters["destination"], action_query)
        stage = Usd.Stage.Open(str(src))
        if stage is None:
            raise ValueError(f"USD illisible : {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        stage.Export(str(dst))
        return {"path": str(dst)}


@register("usd_check")
class UsdCheck(CommandBase):
    """Run the FLUX USD contract check (R3) on a published USD; lists the findings."""
    doc_fr = "Lance le controle USD de FLUX (R3) sur un USD publie ; liste ce qui ne va pas."
    parameters = {"source": {"type": "str", "label": "USD publie"}}

    async def run(self, parameters, action_query, logger):
        from features.usd_assembler.validate.publish_check import check_published_usd

        src = _path(parameters["source"], action_query)
        root = _ctx(action_query).get("project_path")
        issues = check_published_usd(src, src.stem, Path(root) if root else None)
        found = [str(getattr(i, "message", i)) for i in issues]
        return {"issues": found, "count": len(found), "ok": not found}


@register("convert_image")
class ConvertImage(CommandBase):
    """Convert an image to another format (exr, png, tif, jpg) with OpenImageIO."""
    doc_fr = "Convertit une image dans un autre format (exr, png, tif, jpg) avec OpenImageIO."
    parameters = {"source": {"type": "str", "label": "Image source"},
                  "destination": {"type": "str", "label": "Image de sortie (l'extension choisit le format)"}}

    async def run(self, parameters, action_query, logger):
        import OpenImageIO as oiio

        src = _path(parameters["source"], action_query)
        dst = _path(parameters["destination"], action_query)
        dst.parent.mkdir(parents=True, exist_ok=True)
        buf = oiio.ImageBuf(str(src))
        if buf.has_error or not buf.write(str(dst)):
            raise ValueError(f"conversion impossible : {buf.geterror() or src}")
        return {"path": str(dst)}


@register("notify_activity")
class NotifyActivity(CommandBase):
    """Post an event in the Activity feed of the project (seen by the team)."""
    doc_fr = "Poste un evenement dans le fil Activite du projet (vu par l'equipe)."
    parameters = {"text": {"type": "str", "label": "Texte (nom de fichier ou message)"},
                  "folder": {"type": "str", "label": "Dossier lie (optionnel)"}}

    async def run(self, parameters, action_query, logger):
        from features.activity.activity_writer import log_event

        ctx = _ctx(action_query)
        folder = parameters.get("folder")
        ok = log_event(ctx.get("user") or "unknown", "update", ctx.get("project_name") or "",
                       filename=parameters.get("text") or "",
                       dest_folder=_path(folder, action_query) if folder else None)
        return {"posted": bool(ok)}


@register("refresh_component")
class RefreshComponent(CommandBase):
    """Update the asset component (USD) from a publish folder, like after a publish."""
    doc_fr = "Met a jour le component USD de l'asset depuis un dossier de publish, comme apres un publish."
    parameters = {"folder": {"type": "str", "label": "Dossier du publish"},
                  "base": {"type": "str", "label": "Nom de base du publish"},
                  "ext": {"type": "str", "value": ".usd", "label": "Extension"}}

    async def run(self, parameters, action_query, logger):
        from features.usd_assembler.component_auto import refresh_from_publish_folder

        res = refresh_from_publish_folder(_path(parameters["folder"], action_query), parameters["base"],
                                          parameters.get("ext") or ".usd", user=_ctx(action_query).get("user") or "")
        return {"result": res, "updated": bool(res)}


@register("refresh_shot_stage")
class RefreshShotStage(CommandBase):
    """Regenerate the shot stage from a shot department publish folder."""
    doc_fr = "Regenere le stage du shot depuis un dossier de publish d'un departement de shot."
    parameters = {"folder": {"type": "str", "label": "Dossier du publish"},
                  "base": {"type": "str", "label": "Nom de base du publish"},
                  "ext": {"type": "str", "value": ".usd", "label": "Extension"}}

    async def run(self, parameters, action_query, logger):
        from features.usd_assembler.shot_stage import refresh_from_publish_folder

        res = refresh_from_publish_folder(_path(parameters["folder"], action_query), parameters["base"],
                                          parameters.get("ext") or ".usd", user=_ctx(action_query).get("user") or "")
        return {"result": res, "updated": bool(res)}
