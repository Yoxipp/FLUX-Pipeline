# autostart.py — FLUX Nuke autostart manager (~/.nuke/init.py).
#
# Same shape as the Maya/Houdini autostart modules so the DCC router can dispatch
# to it generically: is_installed / get_startup_file / install / uninstall.
#
# Nuke runs ~/.nuke/init.py at startup. The FLUX block adds the backend to
# sys.path and starts the socket bridge (dcc/nuke/flux_nuke_server.py).

from __future__ import annotations

import re
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

_BLOCK_BEGIN = "# >>> FLUX autostart — do not edit manually"
_BLOCK_END   = "# <<< FLUX autostart"


def _nuke_home() -> Path:
    """Return the user's ~/.nuke directory (created on install if missing)."""
    return Path.home() / ".nuke"


def get_startup_file(nuke_exe_path: str | None = None) -> Path | None:
    return _nuke_home() / "init.py"


def is_installed(nuke_exe_path: str | None = None) -> bool:
    f = get_startup_file()
    if f is None or not f.exists():
        return False
    try:
        return _BLOCK_BEGIN in f.read_text(encoding="utf-8")
    except OSError:
        return False


def _block() -> str:
    flux_backend = str(Path(__file__).resolve().parent.parent.parent)
    try:
        from core.constants import DCC_PORTS
        port = DCC_PORTS.get("Nuke", 7003)
    except ImportError:
        port = 7003
    return (
        f"{_BLOCK_BEGIN}\n"
        f"try:\n"
        f"    import sys as _s\n"
        f"    if r'{flux_backend}' not in _s.path:\n"
        f"        _s.path.insert(0, r'{flux_backend}')\n"
        f"    from dcc.nuke import flux_nuke_server as _fns\n"
        f"    _fns.start({port})\n"
        f"except Exception as _e:\n"
        f"    print('[FLUX] Nuke autostart error: %s' % _e)\n"
        f"{_BLOCK_END}"
    )


def install(nuke_exe_path: str | None = None) -> dict:
    """Write (or refresh) the FLUX block into ~/.nuke/init.py. Idempotent."""
    home = _nuke_home()
    f = home / "init.py"
    block = _block()
    try:
        home.mkdir(parents=True, exist_ok=True)
        existing = f.read_text(encoding="utf-8") if f.exists() else ""
        if _BLOCK_BEGIN in existing:
            existing = re.sub(
                rf"\n?{re.escape(_BLOCK_BEGIN)}.*?{re.escape(_BLOCK_END)}\n?",
                "", existing, flags=re.DOTALL,
            )
        new = (existing.rstrip() + "\n\n" + block + "\n") if existing.strip() else (block + "\n")
        f.write_text(new, encoding="utf-8")
    except OSError as exc:
        return {"success": False, "message": str(exc), "path": None}
    log.info("Nuke autostart installed → %s", f)
    return {"success": True, "message": f"installed → {f}", "path": str(f)}


def uninstall(nuke_exe_path: str | None = None) -> dict:
    """Remove the FLUX block from ~/.nuke/init.py."""
    f = get_startup_file()
    if f is None or not f.exists():
        return {"success": True, "message": "not_installed"}
    try:
        content = f.read_text(encoding="utf-8")
        if _BLOCK_BEGIN not in content:
            return {"success": True, "message": "not_installed"}
        cleaned = re.sub(
            rf"\n?{re.escape(_BLOCK_BEGIN)}.*?{re.escape(_BLOCK_END)}\n?",
            "", content, flags=re.DOTALL,
        )
        f.write_text(cleaned, encoding="utf-8")
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    return {"success": True, "message": "uninstalled"}
