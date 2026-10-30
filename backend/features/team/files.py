# files.py — files attached to a team chat message (ADR 0077). Bytes never go through the
# API (ADR 0005): the backend COPIES a local file the artist picked or dropped into
#   DOSSIER_PROJETS/<project>/_flux_setup/team_files/<hash>.<ext>
# named by its content, so the same file attached twice is stored once. Programs and
# scripts are refused: a click on an attachment opens it with the system.

from __future__ import annotations

import hashlib
import re
import secrets
import shutil
from pathlib import Path
from typing import Dict

MAX_BYTES = 200 * 1024 * 1024
BLOCKED = {".exe", ".bat", ".cmd", ".com", ".msi", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".scr", ".lnk",
           ".reg", ".hta", ".cpl", ".jar", ".dll", ".sh"}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
NAME_RE = re.compile(r"^[0-9a-f]{20}\.[a-z0-9]{1,8}$")


class AttachError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def files_dir(project: str) -> Path:
    from core.paths import get_project_path
    from core.project_setup import setup_path

    return setup_path(get_project_path(project), "team_files")


def attach(folder: Path, source: str) -> Dict[str, object]:
    """Copy *source* into *folder*: {name, file, size, image}."""
    src = Path(source)
    ext = src.suffix.lower()
    if not ext or ext in BLOCKED or not re.match(r"^\.[a-z0-9]{1,8}$", ext):
        raise AttachError(f"type de fichier refuse : {ext or 'sans extension'}")
    try:
        size = src.stat().st_size
    except OSError:
        raise AttachError(f"fichier introuvable : {source}", 404) from None
    if not src.is_file() or size > MAX_BYTES:
        raise AttachError(f"fichier trop gros (max {MAX_BYTES // (1024 * 1024)} Mo)")
    digest = hashlib.sha1()
    with open(src, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    name = f"{digest.hexdigest()[:20]}{ext}"
    target = folder / name
    if not target.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".flux_tmp_{secrets.token_hex(4)}{ext}")
        shutil.copyfile(src, tmp)
        tmp.replace(target)
    return {"name": src.name[:200], "file": name, "size": size, "image": ext in IMAGES}


def file_path(folder: Path, name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise AttachError("nom de fichier invalide", 400)
    path = folder / name
    if not path.is_file():
        raise AttachError("fichier introuvable", 404)
    return path
