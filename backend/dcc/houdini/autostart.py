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
from core.paths import get_flux_root

log = get_logger(__name__)

# Startup scripts that carry the FLUX block. 123.py runs only when Houdini starts WITHOUT a
# scene; 456.py runs on every scene load (a .hip double-clicked outside FLUX). B5 2026-09-28.
_STARTUP_FILES = ("123.py", "456.py")
# 2026-09-30 (B5, tested live on Houdini 22): a Houdini opened on a .hip runs
# neither 123.py nor 456.py (nor uiready.py), only pythonX.Ylibs/pythonrc.py. The block
# also goes there, for every Python the installed Houdini ships (python313 -> 3.13).
_PYTHONRC = "pythonrc.py"
_DEFAULT_PY_VERSIONS = ("3.13",)

# Markers used to locate the FLUX block in 123.py — never change these.
_BLOCK_BEGIN = "# >>> FLUX autostart — do not edit manually"
_BLOCK_END   = "# <<< FLUX autostart"

# Markers for the FLUX block in houdini.env — never change these.
# ASCII-only on purpose: houdini.env is parsed by Houdini (not Python), avoid cp1252 risk.
_ENV_BEGIN = "# >>> FLUX env - do not edit manually"
_ENV_END   = "# <<< FLUX env"
# FLUX no longer writes a houdini.env block (it used to set PYTHONNOUSERSITE=1);
# the markers stay so _remove_env_block can clean up blocks left by older versions.

# Houdini package file that injects $FLUX (priority n3, F1).
# A Houdini package (JSON under <prefs>/packages/) is the SideFX-native way to set
# environment variables per install. We use it instead of houdini.env on purpose:
# houdini.env is the file whose PYTHONNOUSERSITE line hard-crashed Houdini 22.0, so
# it stays untouched (see _install_to). $FLUX = the local pipeline root, so a .hip
# saved as "$FLUX/DOSSIER_PROJETS/..." stays portable across machines with different
# roots. A plain FLUX variable is inert and cannot cause the user-site USD clash.
_PACKAGE_FILENAME = "flux.json"


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


def _flux_package_text(root: Path) -> str:
    """Return the flux.json package content that sets $FLUX to *root*.

    Forward slashes on purpose: valid JSON on every OS and Houdini's preferred
    path form (no backslash escaping). Two-space indent for readability.
    """
    import json
    payload = {"env": [{"FLUX": root.as_posix()}]}
    return json.dumps(payload, indent=2) + "\n"


def _write_flux_package(prefs_dir: Path, root: Path | None) -> bool:
    """Upsert <prefs_dir>/packages/flux.json so Houdini resolves $FLUX. Best-effort.

    Idempotent: rewrites only when the content changed (root moved). Returns True
    if the package is present and current after the call. When *root* is unknown
    (workspace not set yet) nothing is written and False is returned — we never
    inject an empty or guessed root.
    """
    if root is None:
        return False
    pkg_file = prefs_dir / "packages" / _PACKAGE_FILENAME
    desired = _flux_package_text(root)
    try:
        if pkg_file.exists() and pkg_file.read_text(encoding="utf-8") == desired:
            return True  # already current
    except OSError:
        pass
    try:
        pkg_file.parent.mkdir(parents=True, exist_ok=True)
        pkg_file.write_text(desired, encoding="utf-8")
        return True
    except OSError:
        return False


# File chooser favourites (Locations). jump.pref = plain text, one path per line, env
# vars kept as-is by Houdini, each entry ends with '/', no empty line.
_JUMP_PREF_FILENAME = "jump.pref"
_JUMP_ENTRIES = ("$FLUX/", "$FLUX/DOSSIER_PROJETS/")


def _write_flux_jump_pref(prefs_dir: Path) -> bool:
    """Add the $FLUX favourites to <prefs_dir>/jump.pref, keeping the user's own entries.

    Idempotent and best-effort: returns True when both entries are present after the call.
    """
    jump = prefs_dir / _JUMP_PREF_FILENAME
    try:
        lines = jump.read_text(encoding="utf-8").splitlines() if jump.exists() else []
    except OSError:
        return False
    lines = [ln for ln in lines if ln.strip()]
    missing = [e for e in _JUMP_ENTRIES if e not in lines]
    if not missing:
        return True
    try:
        prefs_dir.mkdir(parents=True, exist_ok=True)
        jump.write_text("\n".join(lines + missing) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def _remove_flux_jump_pref(prefs_dir: Path) -> None:
    """Remove only the FLUX entries from jump.pref (file deleted if left empty)."""
    jump = prefs_dir / _JUMP_PREF_FILENAME
    try:
        lines = jump.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return
    kept = [ln for ln in lines if ln.strip() and ln not in _JUMP_ENTRIES]
    try:
        if kept:
            jump.write_text("\n".join(kept) + "\n", encoding="utf-8")
        else:
            jump.unlink()
    except OSError:
        pass


def _remove_flux_package(prefs_dir: Path) -> None:
    """Remove <prefs_dir>/packages/flux.json, if present. Best-effort."""
    pkg_file = prefs_dir / "packages" / _PACKAGE_FILENAME
    try:
        pkg_file.unlink()
    except (FileNotFoundError, OSError):
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# The autostart block. homeHoudiniDirectory() resolves the scripts dir AT RUNTIME
# inside Houdini, so the same block works regardless of which prefs dir Houdini uses.
# It also sets $FLUX from the *currently running* FLUX backend (agnostic of the pipe
# folder that installed the autostart): each Houdini launch asks the live backend for
# its root and overrides the value the flux.json package set at install time. When no
# FLUX is up, the package value is kept as a fallback.
_NEW_BLOCK = (
    f"{_BLOCK_BEGIN}\n"
    f"try:\n"
    f"    import sys as _flux_sys, os as _flux_os, hou as _flux_hou\n"
    f"    # B5: also in 456.py and pythonrc.py (a .hip opened outside FLUX skips 123.py):\n"
    f"    # once per session, and only with a UI (never in hython / hbatch).\n"
    f"    if 'flux_houdini_server' not in _flux_sys.modules and _flux_hou.isUIAvailable():\n"
    f"        # Dynamic $FLUX: whichever FLUX is currently running wins over the installed value.\n"
    f"        try:\n"
    f"            import urllib.request as _flux_ureq, json as _flux_json, pathlib as _flux_pl\n"
    f"            _flux_port_file = _flux_pl.Path(_flux_os.environ.get('APPDATA', '')) / 'FLUX' / 'backend_port'\n"
    f"            _flux_port = int(_flux_port_file.read_text().strip()) if _flux_port_file.exists() else 8765\n"
    f"            with _flux_ureq.urlopen('http://127.0.0.1:' + str(_flux_port) + '/system/flux-root', timeout=1.0) as _r:\n"
    f"                _flux_root = _flux_json.loads(_r.read().decode()).get('root') or ''\n"
    f"            if _flux_root:\n"
    f"                _flux_hou.putenv('FLUX', _flux_root.replace('\\\\', '/'))\n"
    f"                print('[FLUX] $FLUX -> ' + _flux_root)\n"
    f"        except Exception as _flux_env_exc:\n"
    f"            print('[FLUX] $FLUX left to flux.json package (no live backend): ' + str(_flux_env_exc))\n"
    f"        _flux_sys.path.insert(0, _flux_os.path.join(_flux_hou.homeHoudiniDirectory(), 'scripts'))\n"
    f"        import flux_houdini_server\n"
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


def _py_versions(houdini_exe_path: str | None) -> list[str]:
    """Python versions shipped with this Houdini ($HFS/python313 -> '3.13')."""
    found: list[str] = []
    if houdini_exe_path:
        hfs = Path(houdini_exe_path).resolve().parent.parent
        try:
            for d in sorted(hfs.glob("python3*")):
                m = re.fullmatch(r"python3(\d+)", d.name)
                if d.is_dir() and m:
                    found.append(f"3.{m.group(1)}")
        except OSError:
            pass
    return found or list(_DEFAULT_PY_VERSIONS)


def _startup_targets(prefs_dir: Path, houdini_exe_path: str | None = None) -> list[Path]:
    """Every startup script that carries the FLUX block in *prefs_dir*."""
    targets = [prefs_dir / "scripts" / name for name in _STARTUP_FILES]
    targets += [prefs_dir / f"python{v}libs" / _PYTHONRC for v in _py_versions(houdini_exe_path)]
    return targets


def _install_to(prefs_dir: Path, houdini_exe_path: str | None = None) -> dict:
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

    # Inject $FLUX via a Houdini package (separate file, never houdini.env). Best-effort:
    # a package write failure must not block the autostart install itself.
    _write_flux_package(prefs_dir, get_flux_root())
    _write_flux_jump_pref(prefs_dir)

    results = [_write_block(t) for t in _startup_targets(prefs_dir, houdini_exe_path)]
    failed = [r for r in results if not r["success"]]
    return failed[0] if failed else results[0]


def _write_block(startup: Path) -> dict:
    """Write or upgrade the FLUX block in one startup script (123.py / 456.py / pythonrc.py)."""
    try:
        startup.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"success": False, "message": f"Cannot create {startup.parent}: {exc}", "path": str(startup)}
    existing = startup.read_text(encoding="utf-8") if startup.exists() else ""
    if _BLOCK_BEGIN in existing:
        b_start = existing.find(_BLOCK_BEGIN)
        b_end   = existing.find(_BLOCK_END, b_start)
        old_fragment = existing[b_start : b_end + len(_BLOCK_END)] if b_end > b_start else ""
        # Upgrade any block that is not exactly the current one (legacy path, no guard...).
        if old_fragment != _NEW_BLOCK:
            try:
                startup.write_text(existing.replace(old_fragment, _NEW_BLOCK), encoding="utf-8")
            except OSError as exc:
                return {"success": False, "message": f"Cannot upgrade {startup.name}: {exc}", "path": str(startup)}
            return {"success": True, "message": f"upgraded: {startup}", "path": str(startup)}
        return {"success": True, "message": "already_installed", "path": str(startup)}

    try:
        with open(startup, "a", encoding="utf-8") as fh:
            fh.write(f"\n{_NEW_BLOCK}\n")
    except OSError as exc:
        return {"success": False, "message": f"Cannot write {startup.name}: {exc}", "path": str(startup)}
    return {"success": True, "message": f"installed: {startup}", "path": str(startup)}


def is_installed(houdini_exe_path: str | None = None) -> bool:
    for prefs_dir in _all_prefs_dirs(houdini_exe_path):
        try:
            if all(t.exists() and _NEW_BLOCK in t.read_text(encoding="utf-8")
                   for t in _startup_targets(prefs_dir, houdini_exe_path)):
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

    results = [_install_to(d, houdini_exe_path) for d in dirs]
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
        _remove_flux_package(prefs_dir)
        _remove_flux_jump_pref(prefs_dir)
        for startup in _startup_targets(prefs_dir, houdini_exe_path):
            try:
                content = startup.read_text(encoding="utf-8") if startup.exists() else ""
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
