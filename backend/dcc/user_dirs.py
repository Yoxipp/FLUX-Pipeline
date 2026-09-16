# user_dirs.py - user folders shared by the DCC autostart installers.

from __future__ import annotations

import platform
from pathlib import Path


def documents_dir() -> Path:
    """The real Windows Documents folder, following GPO / OneDrive / custom redirects.

    Path.home() / "Documents" is wrong when Documents is redirected, and that is where
    Mari (Mari/Scripts) and Painter (Adobe/Adobe Substance 3D Painter) keep user files.
    Same lookup as maya/houdini/zbrush autostart (_get_documents_dir).
    """
    if platform.system() != "Windows":
        return Path.home() / "Documents"
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        val, _ = winreg.QueryValueEx(key, "Personal")
        winreg.CloseKey(key)
        return Path(val)
    except Exception:  # noqa: BLE001 - registry unavailable: plain default
        return Path.home() / "Documents"
