# publish_note.py — the note of a published file (N7): who, when, what, from modif_logs.json.
#
# A publish writes one entry per version in modif_logs.json of its folder (append_log):
# {"name": base, "date", "time", "version", "modification", "user"}. A regenerated USD
# asset writes "asset USD regenere : rig v001, look v002, ..." (its departments). Clicking
# a published file (LAST, a vNNN folder or a file inside it) shows the note of that
# version, and the history of the base (newest first).

from __future__ import annotations

import re
from pathlib import Path

from features.folder_manager.naming_validator import get_base_name
from features.publisher.modif_log import read_logs

_VERSION_DIR = re.compile(r"^(?P<base>.+)_(?P<ver>v\d{3,})$")
_VERSION_IN_NAME = re.compile(r"_(v\d{3,})(?=\.|$)")


def _base_and_version(target: Path) -> tuple[str, str | None]:
    """(base, "vNNN" | None) of a published file or version folder. None = LAST."""
    m = _VERSION_DIR.match(target.name) if target.is_dir() else None
    if m:
        return m.group("base"), m.group("ver")
    parent = _VERSION_DIR.match(target.parent.name)
    if parent and target.name.startswith(parent.group("base")):
        return parent.group("base"), parent.group("ver")      # a file of a version folder
    name = target.name
    for suffix in (".flux.json", ".link"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    ver = _VERSION_IN_NAME.search(name)
    return get_base_name(name.split(".", 1)[0] if "." in name else name), (ver.group(1) if ver else None)


def publish_notes(project_path: str | Path, rel_path: str) -> dict:
    """{"base", "version", "latest": entry | None, "history": [entries newest first]}.

    Looks for modif_logs.json in the file's folder and up to two parents (the log lives
    in the publish folder, a file can sit in a version folder below it)."""
    project = Path(project_path)
    target = project / str(rel_path).replace("\\", "/")
    base, version = _base_and_version(target)
    start = target if target.is_dir() else target.parent
    history: list[dict] = []
    for folder in (start, start.parent, start.parent.parent):
        if project not in (folder, *folder.parents):
            break
        history = [e for e in read_logs(folder)
                   if str(e.get("name", "")) == base or str(e.get("name", "")).startswith(base + "_")]
        if history:
            break
    latest = None
    if history:
        latest = next((e for e in history if e.get("version") == version), None) if version else history[0]
    return {"base": base, "version": version, "latest": latest, "history": history}
