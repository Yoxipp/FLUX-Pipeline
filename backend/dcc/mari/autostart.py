# autostart.py — install the FLUX bridge into Mari's scripts dirs (V6 B7).
#
# Same shape as the other DCC autostart modules. Mari runs every .py of its user
# scripts dir at startup (Foundry: Documents\Mari\Scripts on Windows, ~/Mari/Scripts
# elsewhere, plus every folder of MARI_SCRIPT_PATH); the bridge starts its socket
# server when Mari runs it.
#
# 2026-09-25: bridge installed, Mari open, dot still orange. FLUX wrote ONE copy,
# into the first MARI_SCRIPT_PATH entry or the shell (OneDrive) Documents folder, which
# is not always the one this Mari reads. The bridge now goes into every folder Mari may
# read (it starts once even when Mari runs two copies), and diagnose() says where it is
# and what its log says when Mari does not answer.
#
# 2026-09-30: Mari open, dot orange again. MariLog.txt: when a scripts folder holds an
# init.py (here the artist's MariExtensionTablet loader), Mari 7 runs ONLY that init.py,
# never the other .py files. The bridge is then also started from a marked FLUX block
# appended to that init.py (same pattern as the Nuke / Houdini startup blocks).

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from core.logger import get_logger
from dcc.user_dirs import documents_dir

log = get_logger(__name__)

_PLUGIN_SRC = Path(__file__).resolve().parent / "mari_bridge.py"
_PLUGIN_NAME = "flux_mari_bridge.py"
_BRIDGE_LOG = Path(tempfile.gettempdir()) / "flux_mari_bridge.log"
_INIT_NAME = "init.py"
_BLOCK_BEGIN = "# >>> FLUX autostart - do not edit manually"
_BLOCK_END = "# <<< FLUX autostart"


def _init_block(scripts_dir: Path) -> str:
    """FLUX block for an init.py: runs the bridge copy of the same folder (Mari may
    exec init.py without __file__, so the folder is written in at install time)."""
    bridge = str(scripts_dir / _PLUGIN_NAME)
    lines = (
        "",
        _BLOCK_BEGIN,
        "try:",
        "    import runpy as _flux_runpy",
        f"    _flux_runpy.run_path({bridge!r}, run_name='flux_mari_bridge')",
        "except Exception as _flux_exc:",
        "    print('[FLUX] Mari bridge autostart error: %s' % _flux_exc)",
        _BLOCK_END,
        "",
    )
    return "\n".join(lines)


def _strip_block(text: str) -> str:
    start = text.find(_BLOCK_BEGIN)
    if start < 0:
        return text
    end = text.find(_BLOCK_END, start)
    end = len(text) if end < 0 else end + len(_BLOCK_END)
    if text[end:end + 1] == "\n":
        end += 1
    if start > 0 and text[start - 1] == "\n":
        start -= 1
    return text[:start] + text[end:]


def _init_ok(scripts_dir: Path) -> bool:
    """True when the folder has no init.py (Mari runs every .py) or its init.py
    carries the current FLUX block."""
    init = scripts_dir / _INIT_NAME
    if not init.is_file():
        return True
    try:
        return _init_block(scripts_dir).strip() in init.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _write_init_block(scripts_dir: Path) -> None:
    """Append (or refresh) the FLUX block in an existing init.py; never creates one."""
    init = scripts_dir / _INIT_NAME
    if not init.is_file():
        return
    text = _strip_block(init.read_text(encoding="utf-8", errors="replace")).rstrip("\n") + "\n"
    init.write_text(text + _init_block(scripts_dir), encoding="utf-8")


def _documents_dir() -> Path:
    return documents_dir()


def _scripts_dirs() -> list[Path]:
    """Every folder Mari may run startup scripts from, most specific first.

    FLUX_MARI_SCRIPTS_DIR alone when set (tests, studio override). Otherwise every
    MARI_SCRIPT_PATH entry, the shell Documents folder (follows OneDrive / GPO
    redirects), the plain profile Documents folder, and ~/Mari/Scripts.
    """
    override = os.environ.get("FLUX_MARI_SCRIPTS_DIR")
    if override:
        return [Path(override)]
    dirs: list[Path] = []
    for entry in os.environ.get("MARI_SCRIPT_PATH", "").split(os.pathsep):
        if entry.strip():
            dirs.append(Path(entry.strip()))
    dirs.append(_documents_dir() / "Mari" / "Scripts")
    dirs.append(Path.home() / "Documents" / "Mari" / "Scripts")
    dirs.append(Path.home() / "Mari" / "Scripts")
    unique: list[Path] = []
    for d in dirs:
        if not any(os.path.normcase(str(d)) == os.path.normcase(str(u)) for u in unique):
            unique.append(d)
    return unique


def _scripts_dir() -> Path:
    """Main scripts dir (the first of _scripts_dirs)."""
    return _scripts_dirs()[0]


def get_startup_file(exe_path: str | None = None) -> Path | None:
    for d in _scripts_dirs():
        f = d / _PLUGIN_NAME
        if f.exists():
            return f
    return _scripts_dir() / _PLUGIN_NAME


def is_installed(exe_path: str | None = None) -> bool:
    dirs = [d for d in _scripts_dirs() if (d / _PLUGIN_NAME).exists()]
    # A copy Mari never runs (init.py without the FLUX block) does not count: the
    # reinstall offered by FLUX then adds the block.
    return bool(dirs) and all(_init_ok(d) for d in dirs)


def install(exe_path: str | None = None) -> dict:
    written: list[str] = []
    errors: list[str] = []
    for d in _scripts_dirs():
        dest = d / _PLUGIN_NAME
        try:
            d.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_PLUGIN_SRC, dest)
            from dcc.bridge_secret import write_sidecar   # secret of the `run` action
            write_sidecar(dest)
            _write_init_block(d)
            written.append(str(dest))
        except OSError as exc:              # e.g. a read-only studio MARI_SCRIPT_PATH
            errors.append(f"{dest}: {exc}")
    if not written:
        return {"success": False, "message": "; ".join(errors), "path": None}
    log.info("Mari bridge installed -> %s", ", ".join(written))
    msg = "installed -> " + ", ".join(written)
    if errors:
        msg += " | not written: " + "; ".join(errors)
    return {"success": True, "message": msg, "path": written[0]}


def uninstall(exe_path: str | None = None) -> dict:
    errors: list[str] = []
    for d in _scripts_dirs():
        f = d / _PLUGIN_NAME
        init = d / _INIT_NAME
        try:
            if f.exists():
                f.unlink()
            from dcc.bridge_secret import remove_sidecar
            remove_sidecar(f)
            if init.is_file():
                text = init.read_text(encoding="utf-8", errors="replace")
                if _BLOCK_BEGIN in text:
                    init.write_text(_strip_block(text), encoding="utf-8")
        except OSError as exc:
            errors.append(str(exc))
    if errors:
        return {"success": False, "message": "; ".join(errors)}
    return {"success": True, "message": "uninstalled"}


def diagnose(max_lines: int = 4) -> str:
    """Why Mari may not answer, in words: where the bridge is and its last log lines."""
    installed = [str(d / _PLUGIN_NAME) for d in _scripts_dirs() if (d / _PLUGIN_NAME).exists()]
    parts = []
    if installed:
        parts.append("Bridge installe dans : " + ", ".join(installed))
    else:
        parts.append("Bridge non installe (bouton Plug de Mari dans la barre de gauche)")
    try:
        lines = _BRIDGE_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        lines = []
    if lines:
        parts.append("Log du bridge : " + " / ".join(lines[-max_lines:]))
    elif installed:
        parts.append("Mari n'a jamais lance le bridge (aucun log " + str(_BRIDGE_LOG)
                     + ") : relance Mari apres l'installation")
    return ". ".join(parts)
