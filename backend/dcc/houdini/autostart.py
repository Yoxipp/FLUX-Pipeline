"""
FLUX — Houdini 123.py autostart manager.
Installs / removes the FLUX server block in Houdini's startup script.
Works without Houdini being open.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

# Markers used to locate the FLUX block in 123.py — never change these.
_BLOCK_BEGIN = "# >>> FLUX autostart — do not edit manually"
_BLOCK_END   = "# <<< FLUX autostart"

# Markers for the FLUX block in houdini.env — never change these.
# ASCII-only on purpose: houdini.env is parsed by Houdini (not Python), avoid cp1252 risk.
_ENV_BEGIN = "# >>> FLUX env - do not edit manually"
_ENV_END   = "# <<< FLUX env"

# houdini.env block. PYTHONNOUSERSITE=1 stops Houdini's embedded Python from adding
# the per-user site-packages to sys.path. Without it, a pip-installed usd-core in the
# user site (the FLUX backend runs on the same Python minor as Houdini) gets loaded on
# top of Houdini's bundled USD → two USD builds → fatal Tf class-wrapper clash that
# breaks every LOP/USD viewer state. houdini.env is read before Python starts, so the
# user site is never added. This is the reliable, launch-path-independent fix.
_ENV_BLOCK = (
    f"{_ENV_BEGIN}\n"
    f"PYTHONNOUSERSITE = 1\n"
    f"{_ENV_END}"
)


# ---------------------------------------------------------------------------
# Prefs / startup file location
# ---------------------------------------------------------------------------

def _try_hconfig(houdini_exe_path: str | None = None) -> Path | None:
    """Run hconfig -ap to resolve HOUDINI_USER_PREF_DIR via Houdini's own env resolution."""
    hconfig_candidates: list[str | Path] = []
    if houdini_exe_path:
        hconfig_candidates.append(Path(houdini_exe_path).parent / "hconfig.exe")
    hconfig_candidates.append("hconfig")  # Houdini Shell PATH fallback

    # CREATE_NO_WINDOW — évite une console visible sur Windows (meilleure pratique)
    extra: dict = {}
    if platform.system() == "Windows":
        extra["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    for hconfig in hconfig_candidates:
        try:
            result = subprocess.run(
                [str(hconfig), "-ap"],
                capture_output=True, text=True, timeout=10,
                **extra,
            )
            for line in result.stdout.splitlines():
                if "HOUDINI_USER_PREF_DIR" in line:
                    parts = line.split(":=", 1)
                    if len(parts) == 2:
                        p = Path(parts[1].strip())
                        if p.exists():
                            return p
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None


def _get_documents_dir() -> Path:
    """
    Return the real Windows Documents folder, following GPO/OneDrive redirects.
    Falls back to ~/Documents if winreg is unavailable or the key is missing.
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
    except Exception:
        return Path.home() / "Documents"


def _default_prefs_path(houdini_exe_path: str | None = None) -> Path | None:
    """OS-specific default prefs path. Version extracted from exe path via regex."""
    version: str | None = None
    if houdini_exe_path:
        m = re.search(r"[Hh]oudini(?:\s+(?:FX|Core|Indie|Apprentice))?\s+(\d+\.\d+)", str(houdini_exe_path))
        if m:
            version = m.group(1)

    system = platform.system()

    if system == "Windows":
        home = Path.home()
        docs = _get_documents_dir()
        # Priority: real Documents (registry, handles GPO/OneDrive) then home directly
        bases = [docs] if docs != home / "Documents" else []
        bases += [home / "Documents", home]
        if version:
            for base in bases:
                p = base / f"houdini{version}"
                if p.exists():
                    return p
        candidates: list[Path] = []
        for base in bases:
            try:
                candidates.extend(
                    d for d in base.glob("houdini*")
                    if d.is_dir() and re.match(r"houdini\d+\.\d+$", d.name)
                )
            except OSError:
                pass
        candidates.sort(key=lambda d: d.name, reverse=True)
        return candidates[0] if candidates else None

    elif system == "Darwin":
        prefs = Path.home() / "Library" / "Preferences" / "houdini"
        if version:
            p = prefs / version
            if p.exists():
                return p
        if prefs.exists():
            mac_candidates = sorted(
                [d for d in prefs.iterdir() if d.is_dir() and re.match(r"\d+\.\d+$", d.name)],
                key=lambda d: d.name, reverse=True,
            )
            return mac_candidates[0] if mac_candidates else None
        return None

    else:  # Linux
        home = Path.home()
        if version:
            p = home / f"houdini{version}"
            if p.exists():
                return p
        linux_candidates = sorted(
            [d for d in home.glob("houdini*") if d.is_dir() and re.match(r"houdini\d+\.\d+$", d.name)],
            key=lambda d: d.name, reverse=True,
        )
        return linux_candidates[0] if linux_candidates else None


def get_prefs_dir(houdini_exe_path: str | None = None) -> Path | None:
    """
    Locate Houdini's user prefs directory without running Houdini.

    Search order:
      1. HOUDINI_USER_PREF_DIR env var
      2. hconfig -ap  (official SideFX utility — handles GPO-redirected paths and custom installs)
      3. OS-default paths (Windows ~/Documents/houdiniX.Y or ~/houdiniX.Y,
                           macOS ~/Library/Preferences/houdini/X.Y, Linux ~/houdiniX.Y)
    """
    env = os.environ.get("HOUDINI_USER_PREF_DIR")
    if env:
        p = Path(env)
        if p.exists():
            return p

    # Chemins par défaut OS — couvre les installations standard, aucun subprocess
    default = _default_prefs_path(houdini_exe_path)
    if default:
        return default

    # Dernier recours : hconfig (installations non-standard, redirections GPO…)
    # Déclenche une création de processus — peut alerter certains antivirus.
    return _try_hconfig(houdini_exe_path)


def get_startup_file(houdini_exe_path: str | None = None) -> Path | None:
    """Return the 123.py path (may not exist yet). None if prefs dir not found."""
    prefs = get_prefs_dir(houdini_exe_path)
    return (prefs / "scripts" / "123.py") if prefs else None


# ---------------------------------------------------------------------------
# Server script deployment
# ---------------------------------------------------------------------------

def _deploy_server(scripts_dir: Path) -> None:
    """
    Copy flux_houdini_server.py into Houdini's scripts/ directory (next to 123.py).
    Any user sharing that prefs directory gets the server automatically — no
    per-user path hardcoding needed.
    """
    src = Path(__file__).parent / "flux_houdini_server.py"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, scripts_dir / "flux_houdini_server.py")


def _write_env_block(prefs_dir: Path) -> bool:
    """Upsert the FLUX block in prefs_dir/houdini.env. Idempotent. Best-effort.

    Returns True if the block is present after the call, False on write failure.
    """
    env_file = prefs_dir / "houdini.env"
    try:
        existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    except OSError:
        existing = ""

    if _ENV_BEGIN in existing:
        b_start = existing.find(_ENV_BEGIN)
        b_end   = existing.find(_ENV_END, b_start)
        if b_end > b_start:
            old_fragment = existing[b_start : b_end + len(_ENV_END)]
            if old_fragment == _ENV_BLOCK:
                return True  # already current
            new_content = existing.replace(old_fragment, _ENV_BLOCK)
        else:
            new_content = existing  # malformed; fall through to append below
            if _ENV_END not in existing:
                new_content = existing + f"\n{_ENV_BLOCK}\n"
    else:
        sep = "" if existing.endswith("\n") or not existing else "\n"
        new_content = f"{existing}{sep}\n{_ENV_BLOCK}\n"

    try:
        prefs_dir.mkdir(parents=True, exist_ok=True)
        env_file.write_text(new_content, encoding="utf-8")
        return True
    except OSError:
        return False


def _remove_env_block(prefs_dir: Path) -> None:
    """Remove the FLUX block from prefs_dir/houdini.env, if present."""
    env_file = prefs_dir / "houdini.env"
    if not env_file.exists():
        return
    try:
        content = env_file.read_text(encoding="utf-8")
    except OSError:
        return
    if _ENV_BEGIN not in content:
        return
    cleaned = re.sub(
        rf"\n?{re.escape(_ENV_BEGIN)}.*?{re.escape(_ENV_END)}\n?",
        "",
        content,
        flags=re.DOTALL,
    )
    try:
        env_file.write_text(cleaned, encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# The autostart block. homeHoudiniDirectory() resolves the scripts dir AT RUNTIME
# inside Houdini, so the same block works regardless of which prefs dir Houdini uses.
_NEW_BLOCK = (
    f"{_BLOCK_BEGIN}\n"
    f"try:\n"
    f"    import sys as _flux_sys, os as _flux_os, hou as _flux_hou\n"
    f"    _flux_sys.path.insert(0, _flux_os.path.join(_flux_hou.homeHoudiniDirectory(), 'scripts'))\n"
    f"    import flux_houdini_server\n"
    f"except Exception as _flux_exc:\n"
    f"    print(f'[FLUX] Autostart error (Houdini continues normally): {{_flux_exc}}')\n"
    f"{_BLOCK_END}"
)


def _extract_version(houdini_exe_path: str | None) -> str | None:
    if not houdini_exe_path:
        return None
    m = re.search(r"[Hh]oudini(?:\s+(?:FX|Core|Indie|Apprentice))?\s+(\d+\.\d+)", str(houdini_exe_path))
    return m.group(1) if m else None


def _resolve_version(houdini_exe_path: str | None) -> str | None:
    """Best-effort Houdini X.Y version, from the exe path or the prefs dir names."""
    v = _extract_version(houdini_exe_path)
    if v:
        return v
    for d in _all_prefs_dirs(houdini_exe_path):
        m = re.search(r"houdini(\d+\.\d+)", d.name)
        if m:
            return m.group(1)
    return None


def _install_importer_hda(houdini_exe_path: str | None) -> dict:
    """Install the Houdini importer/exporter HDAs (a pipeline dependency).

    Called from install() so connecting Houdini via the Launcher's Autostart also
    installs the HDA the FLUX importer needs. Idempotent: install_hdas copies to a
    fixed filename in otls/, so reconnecting refreshes rather than duplicating.
    Non-fatal — a failure here never blocks the autostart install itself.
    """
    version = _resolve_version(houdini_exe_path)
    if not version:
        log.info("HDA install skipped: could not resolve Houdini version")
        return {"success": False, "message": "version_unresolved"}
    try:
        from features.shelf_manager.shelf_core import install_hdas
        ok, msg = install_hdas(version)
        if not ok:
            log.warning("HDA install (autostart) failed (non-fatal): %s", msg)
        return {"success": ok, "message": msg}
    except Exception as exc:  # never break autostart on HDA issues
        log.warning("HDA install (autostart) errored (non-fatal): %s", exc)
        return {"success": False, "message": str(exc)}


def _all_prefs_dirs(houdini_exe_path: str | None = None) -> list[Path]:
    """Every prefs dir Houdini might load 123.py from.

    On some machines Documents is GPO/OneDrive-redirected (get_prefs_dir finds that),
    but Houdini still uses the plain ~/houdiniX.Y home dir. We install into BOTH so the
    block lands wherever Houdini actually reads it.
    """
    dirs: list[Path] = []
    primary = get_prefs_dir(houdini_exe_path)
    if primary:
        dirs.append(primary)
    version = _extract_version(houdini_exe_path)
    if version:
        home = Path.home() / f"houdini{version}"
        if home not in dirs:
            dirs.append(home)
    return dirs


def _install_to(prefs_dir: Path) -> dict:
    """Deploy the server + write/upgrade the FLUX block in prefs_dir/scripts/123.py."""
    scripts = prefs_dir / "scripts"
    try:
        _deploy_server(scripts)
    except Exception as exc:
        return {"success": False, "message": f"Failed to deploy server: {exc}", "path": None}

    # NOTE: PYTHONNOUSERSITE=1 was written here to neutralise the user-site USD
    # clash, but on Houdini 22.0 (py3.13) it makes Houdini hard-crash at startup
    # (loading panel then the process dies). It is disabled until a safer USD
    # isolation is in place (see _remove_env_block, which also cleans up any block
    # a previous version wrote). The user-site usd-core only breaks LOP viewer
    # states, not the SOP usdimport the FLUX importer uses.
    _remove_env_block(prefs_dir)

    startup = scripts / "123.py"
    existing = startup.read_text(encoding="utf-8") if startup.exists() else ""
    if _BLOCK_BEGIN in existing:
        b_start = existing.find(_BLOCK_BEGIN)
        b_end   = existing.find(_BLOCK_END, b_start)
        old_fragment = existing[b_start : b_end + len(_BLOCK_END)] if b_end > b_start else ""
        # Upgrade a legacy block (no try/except, hardcoded path, or __file__ which is
        # undefined in Houdini's exec context).
        needs_upgrade = (
            "try:" not in old_fragment
            or "homeHoudiniDirectory" not in old_fragment
            or "__file__" in old_fragment
        )
        if needs_upgrade:
            try:
                startup.write_text(existing.replace(old_fragment, _NEW_BLOCK), encoding="utf-8")
            except OSError as exc:
                return {"success": False, "message": f"Cannot upgrade 123.py: {exc}", "path": str(startup)}
            return {"success": True, "message": f"upgraded: {startup}", "path": str(startup)}
        return {"success": True, "message": "already_installed", "path": str(startup)}

    try:
        with open(startup, "a", encoding="utf-8") as fh:
            fh.write(f"\n{_NEW_BLOCK}\n")
    except OSError as exc:
        return {"success": False, "message": f"Cannot write 123.py: {exc}", "path": str(startup)}
    return {"success": True, "message": f"installed: {startup}", "path": str(startup)}


def is_installed(houdini_exe_path: str | None = None) -> bool:
    for prefs_dir in _all_prefs_dirs(houdini_exe_path):
        startup = prefs_dir / "scripts" / "123.py"
        try:
            if startup.exists() and _BLOCK_BEGIN in startup.read_text(encoding="utf-8"):
                return True
        except OSError:
            continue
    return False


def install(houdini_exe_path: str | None = None) -> dict:
    """
    Deploy flux_houdini_server.py next to 123.py and append/upgrade the autostart
    block, in EVERY prefs dir Houdini might use. Idempotent.

    Returns {"success": bool, "message": str, "path": str | None, "also": [...]}.
    """
    dirs = _all_prefs_dirs(houdini_exe_path)
    if not dirs:
        return {"success": False, "message": "Houdini prefs directory not found", "path": None}

    results = [_install_to(d) for d in dirs]
    primary = dict(results[0])
    primary["success"] = any(r["success"] for r in results)
    extras = [r["path"] for r in results[1:] if r.get("path")]
    if extras:
        primary["also"] = extras

    # Install the importer HDA dependency as part of connecting Houdini (non-fatal).
    primary["hda"] = _install_importer_hda(houdini_exe_path)
    return primary


def uninstall(houdini_exe_path: str | None = None) -> dict:
    """Remove the FLUX autostart block from 123.py in every prefs dir."""
    removed_any = False
    for prefs_dir in _all_prefs_dirs(houdini_exe_path):
        _remove_env_block(prefs_dir)
        startup = prefs_dir / "scripts" / "123.py"
        if not startup.exists():
            continue
        try:
            content = startup.read_text(encoding="utf-8")
        except OSError:
            continue
        if _BLOCK_BEGIN not in content:
            continue
        cleaned = re.sub(
            rf"\n?{re.escape(_BLOCK_BEGIN)}.*?{re.escape(_BLOCK_END)}\n?",
            "",
            content,
            flags=re.DOTALL,
        )
        try:
            startup.write_text(cleaned, encoding="utf-8")
            removed_any = True
        except OSError:
            continue

    # Remove the importer HDA dependency too (symmetry with install; non-fatal).
    version = _resolve_version(houdini_exe_path)
    if version:
        try:
            from features.shelf_manager.shelf_core import remove_hdas
            ok_hda, msg_hda = remove_hdas(version)
            if not ok_hda:
                log.warning("HDA removal (autostart) failed (non-fatal): %s", msg_hda)
        except Exception as exc:
            log.warning("HDA removal (autostart) errored (non-fatal): %s", exc)

    return {"success": True, "message": "uninstalled" if removed_any else "not_installed"}
