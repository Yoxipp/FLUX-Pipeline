"""Paths as the farm service account sees them: UNC, never a drive letter.

A FLUX root opened through a mapped drive (X:\\...) is converted to its UNC
form (\\\\server\\share\\...) with WNetGetConnection. A local disk has no UNC
form: the job cannot be spooled (the blades do not see it).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def _unc_of_drive(drive: str) -> Optional[str]:
    """\\\\server\\share mapped on *drive* ("X:"), None for a local disk."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(len(buf))
    try:
        rc = ctypes.windll.mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size))
    except (AttributeError, OSError):
        return None
    return buf.value if rc == 0 and buf.value else None


def to_farm_path(path: str | Path) -> Optional[str]:
    """UNC path with forward slashes, or None when the path is on a local disk."""
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        return text.replace("\\", "/")
    if len(text) >= 2 and text[1] == ":":
        unc = _unc_of_drive(text[:2].upper())
        if not unc:
            return None
        return (unc.rstrip("\\/") + text[2:]).replace("\\", "/")
    return text.replace("\\", "/")
