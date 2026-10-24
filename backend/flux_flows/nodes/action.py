# action.py — file and system effects (02_NODES §6). P3.
#
# The file logic is shared with the v1 commands (flux_actions/commands/utility.py:
# copy_path, move_path, list_paths, write_json_atomic, write_text_file, zip_dir,
# convert_image_file, make_dir). This module adds what v2 asks on top of it:
# never overwrite by default, containment of every erase / overwrite
# (common.check_destructive_target), a dry run (simulate) that writes nothing,
# Houdini style patterns for list_files.
#
# Bodies are sync: they run in the FLOWS pool thread and may block.
# A relative path is relative to the run's project (common.as_path).

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

from flux_actions.commands.utility import (
    convert_image_file, copy_path, list_paths, make_dir, move_path, move_target, write_json_atomic,
    write_text_file, zip_dir,
)
from flux_flows.nodes.common import (
    archive_into_project, archive_preview, as_bool, as_path, check_destructive_target,
)
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.registry import flow_node, port

_EXEC = port("exec", "exec", required=True)
_EXITS = [port("then", "exec", "Suite si reussi", "Next step on success"),
          port("on_error", "exec", "Suite en cas d'erreur", "Next step on error")]

WRITE_MODES_JSON = ("create", "overwrite")
WRITE_MODES_TEXT = ("create", "overwrite", "append")
DELETE_MODES = ("archive", "erase")
LIST_KINDS = ("file", "dir", "both")
COPY_DEST_IS = ("auto", "folder", "file")
_NAME_FORBIDDEN = "/\\:"

# action.run: scene extension -> launcher key (features.launcher.launcher_core).
RUN_EXTENSIONS: Dict[str, str] = {
    ".ma": "maya", ".mb": "maya",
    ".hip": "houdini", ".hipnc": "houdini", ".hiplc": "houdini",
    ".nk": "nuke", ".nknc": "nuke",
    ".spp": "substance_painter",
    ".sbs": "substance_designer",
    ".zpr": "zbrush", ".ztl": "zbrush",
    ".zprj": "marvelous", ".zpac": "marvelous",
    ".psd": "photoshop",
    ".uproject": "unreal",
}
# Soft ids of the Flows params (02_NODES §1) -> launcher keys.
RUN_SOFTS: Dict[str, str] = {
    "maya": "maya", "houdini": "houdini", "nuke": "nuke",
    "painter": "substance_painter", "substance_painter": "substance_painter",
    "designer": "substance_designer", "substance_designer": "substance_designer",
    "zbrush": "zbrush", "marvelous": "marvelous", "mari": "mari",
    "photoshop": "photoshop", "unreal": "unreal",
}
RUN_SOFT_CHOICES: Tuple[str, ...] = ("auto", *RUN_SOFTS)


# -- helpers ------------------------------------------------------------------------

@contextmanager
def _fs_errors(what: str) -> Iterator[None]:
    """OSError / ValueError of the file helpers -> NodeError the artist can read."""
    try:
        yield
    except NodeError:
        raise
    except FileNotFoundError as exc:
        raise NodeError(f"{what} : introuvable ({exc.filename or exc})") from None
    except PermissionError as exc:
        raise NodeError(f"{what} : acces refuse ({exc.filename or exc})") from None
    except (OSError, ValueError) as exc:
        raise NodeError(f"{what} : {exc}") from None


def _existing(path: Path, what: str) -> Path:
    if not path.exists():
        raise NodeError(f"{what} introuvable : {path}")
    return path


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _files_of(path: Path) -> List[Path]:
    """The files a path stands for: itself, or every file under a folder."""
    if path.is_file():
        return [path]
    if path.is_dir():
        try:
            return [p for p in path.rglob("*") if p.is_file()]
        except OSError:
            return []
    return []


def _size_text(n: int) -> str:
    size = float(n)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{int(size)} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} o"


def _mode(params, allowed: Tuple[str, ...], default: str) -> str:
    mode = str(params.get("mode") or default).strip().lower()
    if mode not in allowed:
        raise NodeError(f"Mode inconnu '{mode}' ({', '.join(allowed)})", code="E_PARAM_INVALID")
    return mode


def _choice(values, name: str, allowed: Tuple[str, ...], default: str) -> str:
    got = str(values.get(name) or default).strip().lower()
    if got not in allowed:
        raise NodeError(f"{name} inconnu '{got}' ({', '.join(allowed)})", code="E_PARAM_INVALID")
    return got


def _line(kind: str, text: str, path: Any = None) -> Dict[str, Any]:
    return {"kind": kind, "text_fr": text, "path": str(path) if path is not None else None}


def _values(inputs, params) -> Dict[str, Any]:
    """Params with the value of a promoted (linked) param on top: the engine gives a
    linked param in ``inputs``, a typed one in ``params``."""
    return {**params, **{k: v for k, v in inputs.items() if k != "exec"}}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _file_name(name: str, what: str = "name") -> str:
    """A bare file name (no folder): else NodeError E_PARAM_INVALID."""
    if not name or name in (".", "..") or any(c in name for c in _NAME_FORBIDDEN):
        raise NodeError(f"{what} invalide `{name}` : un nom seul, sans dossier", code="E_PARAM_INVALID")
    return name


def _missing_dirs(folder: Path) -> List[Path]:
    """The folders of *folder* (itself included) that do not exist yet, top first."""
    out: List[Path] = []
    while not folder.exists() and folder.parent != folder:
        out.append(folder)
        folder = folder.parent
    return out[::-1]


def _check_parents(folder: Path, make_dirs: bool) -> List[Path]:
    """Missing folders of *folder*; refused when make_dirs is off."""
    missing = _missing_dirs(folder)
    if missing and not make_dirs:
        raise NodeError(f"Dossier introuvable : {missing[0]} (active make_dirs pour le creer)")
    if not missing and not folder.is_dir():
        raise NodeError(f"Refus : `{folder}` existe et c'est un fichier, pas un dossier")
    return missing


def _dirs_line(missing: List[Path]) -> List[Dict[str, Any]]:
    if not missing:
        return []
    return [_line("make_dir", f"creerait le dossier {missing[-1]}"
                  + (f" (et {len(missing) - 1} parents)" if len(missing) > 1 else ""), missing[-1])]


def _ends_with_sep(value: Any) -> bool:
    """The raw text of a path ends with / or \\ (as_path drops it): "a folder"."""
    if isinstance(value, dict):
        value = value.get("path")
    return _text(value).endswith(("/", "\\"))


# -- action.run ---------------------------------------------------------------------

def _run_args(ctx, inputs, params) -> Tuple[Path, str]:
    path = as_path(ctx, inputs.get("path"), "fichier a ouvrir")
    soft = str(params.get("soft") or "auto").strip().lower()
    if soft == "auto":
        key = RUN_EXTENSIONS.get(path.suffix.lower())
        if not key:
            raise NodeError(f"Pas de logiciel connu pour l'extension `{path.suffix or '(aucune)'}` : "
                            "choisis `soft` (maya, houdini, nuke...)", code="E_PARAM_INVALID")
        return path, key
    key = RUN_SOFTS.get(soft)
    if not key:
        raise NodeError(f"Logiciel inconnu '{soft}' (auto, {', '.join(sorted(set(RUN_SOFTS)))})",
                        code="E_PARAM_INVALID")
    return path, key


def _simulate_run(ctx, inputs, params):
    path, soft = _run_args(ctx, inputs, params)
    return {"lines": [_line("run", f"ouvrirait {path} avec {soft} (rien n'est lance)", path)],
            "outputs": {"launched": True}}


@flow_node("action.run", "Run", icon="Play",
           inputs=[_EXEC, port("path", "path", "Scene ou fichier a ouvrir", "Scene or file to open",
                               "assets/CHR/HERO/HERO_mod.ma", required=True)],
           outputs=[*_EXITS, port("launched", "bool", "Le logiciel a demarre", "The software started", True)],
           params=[port("soft", "str", "Logiciel : auto (par extension), maya, houdini, nuke, painter...",
                        "Software: auto (from the extension), maya, houdini, nuke, painter...", "auto",
                        default="auto", choices=RUN_SOFT_CHOICES)],
           effect=True, simulate=_simulate_run, shelf=50, aliases=["ouvrir", "open", "lancer", "launch"],
           doc_fr="Ouvre un fichier dans son logiciel (Maya, Houdini, Nuke...), detache de FLUX.",
           doc_en="Opens a file in its software (Maya, Houdini, Nuke...), detached from FLUX.")
def run(ctx, inputs, params):
    path, soft = _run_args(ctx, inputs, params)
    _existing(path, "Fichier")
    from features.launcher.launcher_core import launch_dcc

    if not launch_dcc(soft, str(path)):
        raise NodeError(f"{soft} n'a pas pu etre lance : logiciel introuvable sur ce poste "
                        "(Reglages > Logiciels)")
    ctx.log(f"{path} ouvert avec {soft}")
    return {"launched": True}


# -- action.rename ------------------------------------------------------------------

def _rename_args(ctx, inputs) -> Tuple[Path, Path]:
    path = as_path(ctx, inputs.get("path"), "chemin a renommer")
    name = "" if inputs.get("new_name") is None else str(inputs.get("new_name")).strip()
    if not name or name in (".", "..") or any(c in name for c in "/\\:"):
        raise NodeError(f"Nouveau nom invalide `{name}` : un nom seul, sans dossier", code="E_PARAM_INVALID")
    return path, path.with_name(name)


def _same_entry(a: Path, b: Path) -> bool:
    """b exists only as a case variant of a (Windows): renaming a to b is allowed."""
    try:
        return a.exists() and b.exists() and a.samefile(b) and a.name != b.name
    except OSError:
        return False


def _check_rename(path: Path, target: Path) -> None:
    if target.exists() and not _same_entry(path, target):
        raise NodeError(f"Refus : `{target}` existe deja (rename n'ecrase jamais)", code="E_EXISTS")


def _simulate_rename(ctx, inputs, params):
    path, target = _rename_args(ctx, inputs)
    _check_rename(path, target)
    lines = [_line("rename", f"renommerait {path} en {target.name}", path)]
    if not path.exists():
        lines.append(_line("warn", f"{path} n'existe pas encore", path))
    return {"lines": lines, "outputs": {"path": str(target)}}


@flow_node("action.rename", "Rename", icon="Pencil",
           inputs=[_EXEC,
                   port("path", "path", "Fichier ou dossier a renommer", "File or folder to rename",
                        "shot/SEQ010/SH010/notes.txt", required=True),
                   port("new_name", "str", "Nouveau nom (sans dossier)", "New name (no folder)",
                        "notes_old.txt", required=True)],
           outputs=[*_EXITS, port("path", "path", "Nouveau chemin", "New path")],
           effect=True, simulate=_simulate_rename, shelf=53, aliases=["renommer"],
           doc_fr="Renomme un fichier ou un dossier dans son dossier. N'ecrase jamais : erreur si le nom existe.",
           doc_en="Renames a file or a folder in place. Never overwrites: error when the name exists.")
def rename(ctx, inputs, params):
    path, target = _rename_args(ctx, inputs)
    _existing(path, "Source")
    _check_rename(path, target)
    with _fs_errors("Renommage"):
        if _same_entry(path, target):
            path.rename(target)
        else:
            target = move_path(path, target)
    return {"path": str(target)}


# -- action.move --------------------------------------------------------------------

def _move_args(ctx, inputs) -> Tuple[Path, Path]:
    src = as_path(ctx, inputs.get("source"), "source")
    dest = as_path(ctx, inputs.get("dest"), "destination")
    target = move_target(src, dest)
    if target.exists():
        raise NodeError(f"Refus : `{target}` existe deja (move n'ecrase jamais)", code="E_EXISTS")
    if src.exists() and _inside(target, src):
        raise NodeError(f"Refus : `{target}` est dans la source `{src}`")
    return src, target


def _simulate_move(ctx, inputs, params):
    src, target = _move_args(ctx, inputs)
    lines = [_line("move", f"deplacerait {src} vers {target}", src)]
    if not src.exists():
        lines.append(_line("warn", f"{src} n'existe pas encore", src))
    return {"lines": lines, "outputs": {"path": str(target)}}


@flow_node("action.move", "Move", icon="FolderInput",
           inputs=[_EXEC,
                   port("source", "path", "Fichier ou dossier a deplacer", "File or folder to move",
                        "render/out.exr", required=True),
                   port("dest", "path", "Destination (un dossier existant = dedans)",
                        "Destination (an existing folder = into it)", "render/old/", required=True)],
           outputs=[*_EXITS, port("path", "path", "Chemin final", "Final path")],
           effect=True, simulate=_simulate_move, shelf=52, aliases=["deplacer", "bouger"],
           doc_fr="Deplace un fichier ou un dossier. N'ecrase jamais : erreur si la destination existe.",
           doc_en="Moves a file or a folder. Never overwrites: error when the destination exists.")
def move(ctx, inputs, params):
    src, target = _move_args(ctx, inputs)
    _existing(src, "Source")
    with _fs_errors("Deplacement"):
        target = move_path(src, target)
    return {"path": str(target)}


# -- action.copy --------------------------------------------------------------------

def _copy_args(ctx, inputs, params) -> Tuple[Path, Path, bool, List[Path]]:
    values = _values(inputs, params)
    src = as_path(ctx, inputs.get("source"), "source")
    raw = inputs.get("dest")
    dest = as_path(ctx, raw, "destination")
    overwrite = as_bool(values.get("overwrite"), False)
    dest_is = _choice(values, "dest_is", COPY_DEST_IS, "auto")
    # Into a folder (keeping the source name): folder mode, or auto with an existing
    # folder or a text ending with / or \\. Else dest is the exact target path.
    into = dest_is == "folder" or (dest_is == "auto" and (dest.is_dir() or _ends_with_sep(raw)))
    if into and dest.exists() and not dest.is_dir():
        raise NodeError(f"Refus : `{dest}` est un fichier, pas un dossier")
    if dest_is == "file" and dest.is_dir() and not src.is_dir():
        raise NodeError(f"Refus : `{dest}` est un dossier (dest_is file attend le chemin du fichier)")
    target = dest / src.name if into else dest
    missing = _check_parents(target.parent, as_bool(values.get("make_dirs"), True))
    if target.exists():
        if not overwrite:
            raise NodeError(f"Refus : `{target}` existe deja (active overwrite pour ecraser)", code="E_EXISTS")
        if src.exists() and src.is_dir() != target.is_dir():
            raise NodeError(f"Refus : `{target}` existe et n'est pas du meme genre que la source")
        check_destructive_target(target)
    if src.is_dir() and _inside(target, src):
        raise NodeError(f"Refus : `{target}` est dans la source `{src}`")
    return src, target, overwrite, missing


def _simulate_copy(ctx, inputs, params):
    src, target, _overwrite, missing = _copy_args(ctx, inputs, params)
    files = _files_of(src)
    size = sum(f.stat().st_size for f in files if f.exists())
    if src.is_dir():
        clash = sum(1 for f in files if (target / f.relative_to(src)).exists())
    else:
        clash = 1 if target.is_file() else 0
    text = f"copierait {len(files)} fichiers ({_size_text(size)}) vers {target}"
    if clash:
        text += f" ; en ecraserait {clash}"
    lines = [*_dirs_line(missing), _line("copy", text, target)]
    if not src.exists():
        lines.append(_line("warn", f"{src} n'existe pas encore", src))
    return {"lines": lines, "outputs": {"path": str(target)}}


@flow_node("action.copy", "Copy", icon="Copy",
           inputs=[_EXEC,
                   port("source", "path", "Fichier ou dossier a copier", "File or folder to copy",
                        "assets/CHR/HERO/publish/LAST", required=True),
                   port("dest", "path", "Destination : un dossier (existant ou finissant par /) = dedans",
                        "Destination: a folder (existing or ending with /) = into it", "$FLUX/LIVRAISON/",
                        required=True)],
           outputs=[*_EXITS, port("path", "path", "Chemin de la copie", "Path of the copy")],
           params=[port("overwrite", "bool", "Ecraser si la destination existe", "Overwrite when the destination exists",
                        False, default=False),
                   port("dest_is", "str", "auto (dossier existant ou finissant par /), folder (copie dedans) "
                        "ou file (chemin exact de la copie)",
                        "auto (existing folder or ending with /), folder (copy into it) or file (exact path of the copy)",
                        "auto", default="auto", choices=COPY_DEST_IS),
                   port("make_dirs", "bool", "Creer les dossiers manquants", "Create the missing folders", True,
                        default=True)],
           destructive={"param": "overwrite", "equals": True}, simulate=_simulate_copy, shelf=51,
           aliases=["copier", "dupliquer"],
           doc_fr="Copie un fichier ou un dossier, dans un dossier ou vers un chemin exact. Cree les dossiers "
                  "manquants. N'ecrase rien sauf avec overwrite.",
           doc_en="Copies a file or a folder, into a folder or to an exact path. Creates the missing folders. "
                  "Overwrites nothing unless overwrite is on.")
def copy(ctx, inputs, params):
    src, target, overwrite, missing = _copy_args(ctx, inputs, params)
    _existing(src, "Source")
    with _fs_errors("Copie"):
        if missing:
            make_dir(target.parent)
        target = copy_path(src, target, overwrite)
    return {"path": str(target)}


# -- action.make_dir ----------------------------------------------------------------

def _make_dir_args(ctx, inputs) -> Path:
    path = as_path(ctx, inputs.get("path"), "dossier")
    if path.exists() and not path.is_dir():
        raise NodeError(f"Refus : `{path}` existe et c'est un fichier")
    return path


def _simulate_make_dir(ctx, inputs, params):
    path = _make_dir_args(ctx, inputs)
    text = f"existe deja : {path}" if path.is_dir() else f"creerait {path}"
    return {"lines": [_line("make_dir", text, path)], "outputs": {"dir": str(path)}}


@flow_node("action.make_dir", "MakeDir", icon="FolderPlus",
           inputs=[_EXEC, port("path", "path", "Dossier a creer (et ses parents)", "Folder to create (and its parents)",
                               "shot/SEQ010/SH010/review", required=True)],
           outputs=[*_EXITS, port("dir", "dir", "Le dossier", "The folder")],
           effect=True, simulate=_simulate_make_dir, shelf=54, aliases=["mkdir", "creer dossier", "nouveau dossier"],
           doc_fr="Cree un dossier et ses parents. S'il existe deja, rien ne change.",
           doc_en="Creates a folder and its parents. Nothing changes when it exists.")
def make_dir_node(ctx, inputs, params):
    path = _make_dir_args(ctx, inputs)
    with _fs_errors("Creation du dossier"):
        make_dir(path)
    return {"dir": str(path)}


# -- action.delete ------------------------------------------------------------------

def _delete_args(ctx, inputs, params) -> Tuple[Path, str]:
    return as_path(ctx, inputs.get("path"), "chemin a supprimer"), _mode(params, DELETE_MODES, "archive")


def _simulate_delete(ctx, inputs, params):
    path, mode = _delete_args(ctx, inputs, params)
    if mode == "erase":
        target = check_destructive_target(path)
        n = len(_files_of(target))
        lines = [_line("erase", f"supprimerait {n} fichiers ({target})", target)]
        if not target.exists():
            lines.append(_line("warn", f"{target} n'existe pas encore", target))
        return {"lines": lines, "outputs": {"archived_to": None}}
    dest = archive_preview(ctx, path)
    return {"lines": [_line("archive", f"deplacerait {path} vers {dest}", path)],
            "outputs": {"archived_to": str(dest)}}


@flow_node("action.delete", "Delete", icon="Trash2",
           inputs=[_EXEC, port("path", "path", "Fichier ou dossier a supprimer", "File or folder to delete",
                               "shot/SEQ010/SH010/tmp", required=True)],
           outputs=[*_EXITS, port("archived_to", "path", "Ou il a ete archive (mode archive)",
                                  "Where it was archived (archive mode)")],
           params=[port("mode", "str", "archive (deplace dans ARCHIVE du projet) ou erase (efface)",
                        "archive (moves into the project ARCHIVE) or erase (deletes)", "archive",
                        default="archive", choices=DELETE_MODES)],
           destructive={"param": "mode", "equals": "erase"}, simulate=_simulate_delete, shelf=55,
           aliases=["supprimer", "effacer", "archiver", "remove"],
           doc_fr="Archive un fichier ou un dossier du projet dans ARCHIVE/<date>_<ARTISTE>/, "
                  "ou l'efface definitivement en mode erase.",
           doc_en="Archives a project file or folder into ARCHIVE/<date>_<ARTIST>/, "
                  "or erases it for good in erase mode.")
def delete(ctx, inputs, params):
    path, mode = _delete_args(ctx, inputs, params)
    if mode == "erase":
        target = check_destructive_target(path)
        _existing(target, "Chemin")
        from core.paths import force_remove

        with _fs_errors("Suppression"):
            force_remove(target)
        ctx.log(f"efface : {target}")
        return {"archived_to": None}
    dest = archive_into_project(ctx, path)
    ctx.log(f"archive : {path} -> {dest}")
    return {"archived_to": str(dest)}


# -- action.write_json / write_text -------------------------------------------------

def _check_write(path: Path, mode: str, make_dirs: bool) -> List[Path]:
    """Refusals of a file write (folder, exists in create mode, containment of an
    overwrite, missing parents without make_dirs). Returns the folders to create."""
    if path.is_dir():
        raise NodeError(f"Refus : `{path}` est un dossier")
    if path.exists():
        if mode == "create":
            raise NodeError(f"Refus : `{path}` existe deja (mode overwrite pour ecraser)", code="E_EXISTS")
        if mode == "overwrite":
            check_destructive_target(path)
    return _check_parents(path.parent, make_dirs)


def _write_file(ctx, inputs, values) -> Path:
    """The file of write_json / write_text: ``dir`` + ``name``, else ``path`` (an
    existing folder as ``path`` = ``path``/``name``)."""
    name = _text(values.get("name"))
    if _text(inputs.get("dir")):
        if not name:
            raise NodeError("`dir` est relie : donne aussi `name`, le nom du fichier a ecrire dedans",
                            code="E_PARAM_INVALID")
        return as_path(ctx, inputs.get("dir"), "dossier") / _file_name(name)
    if inputs.get("path") is None or _text(inputs.get("path")) == "":
        raise NodeError("Donne `path` (le fichier) ou `dir` et `name` (un dossier et un nom de fichier)")
    path = as_path(ctx, inputs.get("path"), "fichier")
    if path.is_dir():
        if not name:
            raise NodeError(f"`{path}` est un dossier : donne `name` pour le fichier a ecrire dedans",
                            code="E_PARAM_INVALID")
        path = path / _file_name(name)
    return path


def _write_target(ctx, inputs, params, allowed: Tuple[str, ...]) -> Tuple[Path, str, List[Path]]:
    values = _values(inputs, params)
    path = _write_file(ctx, inputs, values)
    mode = _mode(values, allowed, "create")
    return path, mode, _check_write(path, mode, as_bool(values.get("make_dirs"), True))


def _write_ports(example: str) -> list:
    """path / dir inputs of write_json / write_text (one of them is needed)."""
    return [port("path", "path", "Fichier (ou un dossier existant + name)", "File (or an existing folder + name)",
                 example),
            port("dir", "dir", "Dossier ou ecrire (avec name), a la place de path",
                 "Folder to write into (with name), instead of path", "review/")]


def _write_params(modes: Tuple[str, ...], doc_fr: str, doc_en: str, example: str) -> list:
    return [port("mode", "str", doc_fr, doc_en, "create", default="create", choices=modes),
            port("name", "str", "Nom du fichier quand dir est donne (ou path est un dossier)",
                 "File name when dir is given (or path is a folder)", example),
            port("make_dirs", "bool", "Creer les dossiers manquants", "Create the missing folders", True,
                 default=True)]


def _json_text(data: Any) -> str:
    try:
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise NodeError(f"Donnees non ecrivables en JSON : {exc}") from None


def _simulate_write_json(ctx, inputs, params):
    path, mode, missing = _write_target(ctx, inputs, params, WRITE_MODES_JSON)
    _json_text(inputs.get("data"))
    text = f"ecrirait {path}" + (" (ecrase l'existant)" if path.exists() else "")
    return {"lines": [*_dirs_line(missing), _line("write", text, path)], "outputs": {"path": str(path)}}


@flow_node("action.write_json", "WriteJson", icon="FileJson",
           inputs=[_EXEC, *_write_ports("review/notes.json"),
                   port("data", "any", "Donnees a ecrire", "Data to write", {"status": "ok"}, required=True)],
           outputs=[*_EXITS, port("path", "path", "Fichier ecrit", "Written file")],
           params=_write_params(WRITE_MODES_JSON, "create (erreur si existe) ou overwrite",
                                "create (error when it exists) or overwrite", "notes.json"),
           destructive={"param": "mode", "equals": "overwrite"}, simulate=_simulate_write_json, shelf=62,
           aliases=["json", "ecrire json", "save json"],
           doc_fr="Ecrit des donnees dans un fichier JSON (ecrit a cote puis remplace). N'ecrase qu'en mode overwrite.",
           doc_en="Writes data to a JSON file (written next to it, then swapped in). Overwrites only in overwrite mode.")
def write_json(ctx, inputs, params):
    path, _mode_, _missing = _write_target(ctx, inputs, params, WRITE_MODES_JSON)
    data = inputs.get("data")
    _json_text(data)
    with _fs_errors("Ecriture JSON"):
        make_dir(path.parent)
        write_json_atomic(path, data)
    return {"path": str(path)}


def _simulate_write_text(ctx, inputs, params):
    path, mode, missing = _write_target(ctx, inputs, params, WRITE_MODES_TEXT)
    if mode == "append" and path.exists():
        text = f"ajouterait a la fin de {path}"
    else:
        text = f"ecrirait {path}" + (" (ecrase l'existant)" if path.exists() else "")
    return {"lines": [*_dirs_line(missing), _line("write", text, path)], "outputs": {"path": str(path)}}


@flow_node("action.write_text", "WriteText", icon="FileText",
           inputs=[_EXEC, *_write_ports("review/notes.txt"),
                   port("text", "str", "Texte a ecrire", "Text to write", "Retake : lumiere trop forte",
                        required=True)],
           outputs=[*_EXITS, port("path", "path", "Fichier ecrit", "Written file")],
           params=_write_params(WRITE_MODES_TEXT, "create (erreur si existe), overwrite ou append (ajoute a la fin)",
                                "create (error when it exists), overwrite or append (adds at the end)", "notes.txt"),
           destructive={"param": "mode", "equals": "overwrite"}, simulate=_simulate_write_text, shelf=57,
           aliases=["texte", "ecrire", "note", "rapport"],
           doc_fr="Ecrit un fichier texte (note, rapport) : un chemin, ou un dossier et un nom. N'ecrase qu'en "
                  "mode overwrite ; append ajoute a la fin.",
           doc_en="Writes a text file (note, report): a path, or a folder and a name. Overwrites only in overwrite "
                  "mode; append adds at the end.")
def write_text(ctx, inputs, params):
    path, mode, _missing = _write_target(ctx, inputs, params, WRITE_MODES_TEXT)
    text = inputs.get("text")
    with _fs_errors("Ecriture"):
        write_text_file(path, "" if text is None else text, append=(mode == "append"))
    return {"path": str(path)}


# -- action.create_file -------------------------------------------------------------

def _create_file_args(ctx, inputs, params) -> Tuple[Path, str, List[Path], str]:
    values = _values(inputs, params)
    folder = as_path(ctx, inputs.get("dir"), "dossier")
    name = _file_name(_text(values.get("name")))
    ext = _text(values.get("ext")).lstrip(".")
    if ext:
        _file_name(ext, "ext")
    path = folder / (f"{name}.{ext}" if ext else name)
    mode = _mode(values, WRITE_MODES_JSON, "create")
    missing = _check_write(path, mode, as_bool(values.get("make_dirs"), True))
    text = values.get("text")
    return path, mode, missing, "" if text is None else str(text)


def _simulate_create_file(ctx, inputs, params):
    path, _mode_, missing, _text_ = _create_file_args(ctx, inputs, params)
    text = f"creerait {path}" + (" (ecrase l'existant)" if path.exists() else "")
    return {"lines": [*_dirs_line(missing), _line("write", text, path)], "outputs": {"path": str(path)}}


@flow_node("action.create_file", "CreateFile", icon="FilePlus",
           inputs=[_EXEC, port("dir", "dir", "Dossier ou creer le fichier", "Folder to create the file in",
                               "review/", required=True)],
           outputs=[*_EXITS, port("path", "path", "Fichier cree", "Created file", "review/notes.txt")],
           params=[port("name", "str", "Nom du fichier (sans dossier)", "File name (no folder)", "notes",
                        required=True),
                   port("ext", "str", "Extension (txt, json... ; le point est optionnel, vide = aucune)",
                        "Extension (txt, json...; the dot is optional, empty = none)", "txt"),
                   port("text", "str", "Contenu initial (vide par defaut)", "Initial content (empty by default)",
                        "", default=""),
                   port("mode", "str", "create (erreur si existe) ou overwrite", "create (error when it exists) or overwrite",
                        "create", default="create", choices=WRITE_MODES_JSON),
                   port("make_dirs", "bool", "Creer les dossiers manquants", "Create the missing folders", True,
                        default=True)],
           destructive={"param": "mode", "equals": "overwrite"}, simulate=_simulate_create_file, shelf=56,
           aliases=["creer fichier", "nouveau fichier", "new file", "touch"],
           doc_fr="Cree un fichier (vide ou avec un texte) dans un dossier, a partir d'un nom et d'une extension. "
                  "N'ecrase qu'en mode overwrite.",
           doc_en="Creates a file (empty or with a text) in a folder, from a name and an extension. "
                  "Overwrites only in overwrite mode.")
def create_file(ctx, inputs, params):
    path, _mode_, _missing, text = _create_file_args(ctx, inputs, params)
    with _fs_errors("Creation du fichier"):
        write_text_file(path, text)
    return {"path": str(path)}


# -- action.list_files (exec? reader) -----------------------------------------------

@flow_node("action.list_files", "ListFiles", icon="ListTree",
           inputs=[port("exec", "exec", "Optionnel : relie, la liste se fait a cet endroit du flow",
                        "Optional: linked, the listing runs at this point of the flow"),
                   port("folder", "dir", "Dossier a lister", "Folder to list", "render/", required=True)],
           outputs=[port("then", "exec", "Suite (si exec est relie)", "Next step (when exec is linked)"),
                    port("files", "list[path]", "Chemins trouves, tries", "Paths found, sorted"),
                    port("count", "int", "Nombre de chemins", "Number of paths", 12),
                    port("first", "path", "Premier chemin (vide si aucun)", "First path (empty when none)")],
           params=[port("pattern", "pattern", "Motif facon Houdini sur le nom (^ exclut)",
                        "Houdini style pattern on the name (^ excludes)", "*.exr ^*_tmp*", default="*"),
                   port("recursive", "bool", "Sous-dossiers aussi", "Sub-folders too", False, default=False),
                   port("kind", "str", "file, dir ou both", "file, dir or both", "file", default="file",
                        choices=LIST_KINDS)],
           shelf=58, aliases=["lister", "fichiers", "glob", "ls"],
           doc_fr="Liste les fichiers (ou dossiers) d'un dossier qui passent un motif. Lecture : tourne aussi en essai a blanc.",
           doc_en="Lists the files (or folders) of a folder that pass a pattern. Read only: also runs in a dry run.")
def list_files(ctx, inputs, params):
    from flux_flows.patterns import PatternError, mask

    folder = as_path(ctx, inputs.get("folder"), "dossier")
    if not folder.is_dir():
        raise NodeError(f"Dossier introuvable : {folder}")
    kind = str(params.get("kind") or "file").strip().lower()
    if kind not in LIST_KINDS:
        raise NodeError(f"kind inconnu '{kind}' ({', '.join(LIST_KINDS)})", code="E_PARAM_INVALID")
    pattern = params.get("pattern")
    pattern = "*" if pattern is None or str(pattern).strip() == "" else str(pattern)
    with _fs_errors("Lecture du dossier"):
        found = list_paths(folder, as_bool(params.get("recursive"), False), kind)
    rels = [Path(p).relative_to(folder).as_posix() for p in found]
    try:
        keep = mask(pattern, rels)
    except PatternError as exc:
        raise NodeError(f"Motif invalide : {exc.message}", code="E_PARAM_INVALID") from None
    files = [p for p, k in zip(found, keep) if k]
    return {"files": files, "count": len(files), "first": files[0] if files else None}


# -- action.wait --------------------------------------------------------------------

def _seconds(inputs) -> float:
    try:
        seconds = float(inputs.get("seconds"))
    except (TypeError, ValueError):
        raise NodeError(f"seconds : nombre attendu, recu {inputs.get('seconds')!r}") from None
    if seconds < 0:
        raise NodeError("seconds doit etre positif ou nul", code="E_PARAM_INVALID")
    return seconds


def _simulate_wait(ctx, inputs, params):
    return {"lines": [_line("wait", f"attendrait {_seconds(inputs):g} s")], "outputs": {}}


@flow_node("action.wait", "Wait", icon="Hourglass",
           inputs=[_EXEC, port("seconds", "float", "Duree en secondes", "Duration in seconds", 5, required=True,
                               default=5)],
           outputs=list(_EXITS),
           effect=True, simulate=_simulate_wait, shelf=59, aliases=["attendre", "pause", "sleep", "delai"],
           doc_fr="Attend un certain temps avant la suite (s'arrete tout de suite si le run est annule).",
           doc_en="Waits for a while before the next step (stops at once when the run is cancelled).")
def wait(ctx, inputs, params):
    seconds = _seconds(inputs)
    # Event.wait sleeps and wakes up as soon as the run is cancelled.
    ctx.cancelled.wait(seconds)
    return {}


# -- action.zip_folder --------------------------------------------------------------

def _zip_args(ctx, inputs, params) -> Tuple[Path, Path, Path]:
    folder = as_path(ctx, inputs.get("folder"), "dossier a zipper")
    dest = as_path(ctx, inputs.get("dest"), "zip")
    if dest.is_dir():
        dest = dest / f"{folder.name}.zip"
    base = dest.with_suffix("") if dest.suffix.lower() == ".zip" else dest
    zip_path = base.with_name(base.name + ".zip")
    if folder.exists() and _inside(zip_path, folder):
        raise NodeError(f"Refus : le zip `{zip_path}` serait dans le dossier zippe")
    if zip_path.exists():
        if not as_bool(params.get("overwrite"), False):
            raise NodeError(f"Refus : `{zip_path}` existe deja (active overwrite pour ecraser)", code="E_EXISTS")
        check_destructive_target(zip_path)
    return folder, base, zip_path


def _simulate_zip(ctx, inputs, params):
    folder, _base, zip_path = _zip_args(ctx, inputs, params)
    text = f"zipperait {folder} ({len(_files_of(folder))} fichiers) vers {zip_path}"
    if zip_path.exists():
        text += " ; ecraserait le zip existant"
    return {"lines": [_line("zip", text, zip_path)], "outputs": {"zip": str(zip_path)}}


@flow_node("action.zip_folder", "ZipFolder", icon="FileArchive",
           inputs=[_EXEC,
                   port("folder", "dir", "Dossier a zipper", "Folder to zip", "assets/CHR/HERO/publish/LAST",
                        required=True),
                   port("dest", "path", "Zip a creer (.zip ajoute si absent ; un dossier = dedans)",
                        "Zip to create (.zip added when missing; a folder = into it)", "$FLUX/LIVRAISON/HERO.zip",
                        required=True)],
           outputs=[*_EXITS, port("zip", "path", "Zip cree", "Created zip")],
           params=[port("overwrite", "bool", "Ecraser un zip existant", "Overwrite an existing zip", False,
                        default=False)],
           destructive={"param": "overwrite", "equals": True}, simulate=_simulate_zip, shelf=60,
           aliases=["zip", "archive zip", "compresser", "livraison"],
           doc_fr="Zippe un dossier (livraison, sauvegarde avant une modif risquee).",
           doc_en="Zips a folder (delivery, backup before a risky change).")
def zip_folder(ctx, inputs, params):
    folder, base, zip_path = _zip_args(ctx, inputs, params)
    if not folder.is_dir():
        raise NodeError(f"Dossier introuvable : {folder}")
    with _fs_errors("Zip"):
        base.parent.mkdir(parents=True, exist_ok=True)
        out = zip_dir(folder, base)
    return {"zip": str(out)}


# -- action.convert_image -----------------------------------------------------------

def _convert_args(ctx, inputs, params) -> Tuple[Path, Path]:
    src = as_path(ctx, inputs.get("source"), "image source")
    dst = as_path(ctx, inputs.get("dest"), "image de sortie")
    if dst.is_dir() or not dst.suffix:
        raise NodeError(f"Destination `{dst}` : donne un fichier avec son extension (.png, .exr, .jpg...)",
                        code="E_PARAM_INVALID")
    if dst.exists():
        if not as_bool(params.get("overwrite"), False):
            raise NodeError(f"Refus : `{dst}` existe deja (active overwrite pour ecraser)", code="E_EXISTS")
        check_destructive_target(dst)
    return src, dst


def _simulate_convert(ctx, inputs, params):
    src, dst = _convert_args(ctx, inputs, params)
    text = f"convertirait {src} vers {dst}" + (" (ecrase l'existant)" if dst.exists() else "")
    return {"lines": [_line("convert", text, dst)], "outputs": {"path": str(dst)}}


@flow_node("action.convert_image", "ConvertImage", icon="ImageDown",
           inputs=[_EXEC,
                   port("source", "path", "Image source", "Source image", "render/beauty.0001.exr", required=True),
                   port("dest", "path", "Image de sortie (l'extension choisit le format)",
                        "Output image (the extension picks the format)", "review/beauty.0001.png", required=True)],
           outputs=[*_EXITS, port("path", "path", "Image ecrite", "Written image")],
           params=[port("overwrite", "bool", "Ecraser si l'image existe", "Overwrite when the image exists", False,
                        default=False)],
           destructive={"param": "overwrite", "equals": True}, simulate=_simulate_convert, shelf=61,
           aliases=["convertir", "image", "exr", "png", "oiio"],
           doc_fr="Convertit une image dans un autre format (exr, png, tif, jpg) avec OpenImageIO.",
           doc_en="Converts an image to another format (exr, png, tif, jpg) with OpenImageIO.")
def convert_image(ctx, inputs, params):
    src, dst = _convert_args(ctx, inputs, params)
    _existing(src, "Image source")
    try:
        import OpenImageIO  # noqa: F401
    except ImportError:
        raise NodeError("OpenImageIO n'est pas installe avec FLUX sur ce poste") from None
    with _fs_errors("Conversion"):
        convert_image_file(src, dst)
    return {"path": str(dst)}
