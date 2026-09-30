# zbrush_ui.py - the FLUX ZBrush "shelf": the maintainer's UI (flux_ui_zbrush.cfg) + the FLUX bridge.
#
# 2026-09-30: his current ZBrush interface (made from Rongeart's template) becomes
# the FLUX ZBrush UI, installed from the Shelf Manager like the Maya / Houdini shelves.
# ZBrush loads ZStartup/CustomUserInterface<YEAR>.cfg at launch, so installing =
# writing that file (the artist's own one is kept aside once as .before_flux and
# restored by Remove). The FLUX buttons (Export FLUX, Save +1) are not in the .cfg:
# the bridge plugin, installed at the same time, adds them as a FLUX menu.

from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

UI_SOURCE: Path = Path(__file__).resolve().parents[2] / "resources" / "shelves" / "zbrush" / "flux_ui_zbrush.cfg"
_BACKUP_SUFFIX = ".before_flux"
_YEAR_RE = re.compile(r"(20\d\d)")


def _roots() -> list[Path]:
    from dcc.zbrush.autostart import _find_zbrush_data_dirs
    return _find_zbrush_data_dirs()


def _version_of(root: Path) -> str:
    """'Maxon ZBrush 2026_F3C8B4C4' -> '2026'; a hash-only dir keeps its name."""
    m = _YEAR_RE.search(root.name)
    return m.group(1) if m else root.name


def _root_for(version: str) -> Path | None:
    return next((r for r in _roots() if _version_of(r) == version), None)


def cfg_path(root: Path, version: str) -> Path:
    """The CustomUserInterface cfg ZBrush reads in this data dir (existing name first)."""
    zstartup = root / "ZStartup"
    found = sorted(zstartup.glob("CustomUserInterface*.cfg"))
    if found:
        return found[-1]
    year = version if version.isdigit() else "2026"
    return zstartup / f"CustomUserInterface{year}.cfg"


def get_versions() -> list[str]:
    seen: list[str] = []
    for r in _roots():
        v = _version_of(r)
        if v not in seen:
            seen.append(v)
    return sorted(seen)


def is_installed(version: str) -> bool:
    root = _root_for(version)
    if root is None or not UI_SOURCE.is_file():
        return False
    target = cfg_path(root, version)
    try:
        return target.is_file() and target.read_bytes() == UI_SOURCE.read_bytes()
    except OSError:
        return False


def install(version: str) -> tuple[bool, str]:
    root = _root_for(version)
    if root is None:
        return False, f"Dossier de donnees ZBrush {version} introuvable"
    if not UI_SOURCE.is_file():
        return False, f"UI FLUX introuvable : {UI_SOURCE}"
    target = cfg_path(root, version)
    backup = target.with_name(target.name + _BACKUP_SUFFIX)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Keep the artist's own UI once (never overwritten by a later reinstall).
        if target.is_file() and not backup.exists() and target.read_bytes() != UI_SOURCE.read_bytes():
            shutil.copy2(target, backup)
        shutil.copyfile(UI_SOURCE, target)
    except OSError as exc:
        return False, f"Erreur : {exc}"
    msg = f"UI FLUX installee -> {target}"
    try:
        from dcc.zbrush.autostart import install as install_bridge
        res = install_bridge(None)
        ok = bool(res.get("success")) if isinstance(res, dict) else bool(res)
        msg += " | bridge FLUX (menu FLUX : Export FLUX, Save +1) installe" if ok else f" | bridge non installe : {res}"
    except Exception as exc:  # noqa: BLE001 - the UI is installed, the bridge is secondary
        msg += f" | bridge non installe : {exc}"
    log.info(msg)
    return True, msg + " | relance ZBrush"


def remove(version: str) -> tuple[bool, str]:
    root = _root_for(version)
    if root is None:
        return False, f"Dossier de donnees ZBrush {version} introuvable"
    target = cfg_path(root, version)
    backup = target.with_name(target.name + _BACKUP_SUFFIX)
    try:
        if backup.is_file():
            shutil.move(str(backup), str(target))
            return True, f"UI d'origine restauree -> {target} | relance ZBrush"
        if is_installed(version):
            target.unlink()
            return True, f"UI FLUX retiree (ZBrush reprend son UI par defaut) -> {target}"
    except OSError as exc:
        return False, f"Erreur : {exc}"
    return False, "L'UI FLUX n'est pas installee"
