# client.py — connection check + library bootstrap for Photoshop over COM (V6 B6).
#
# Photoshop is driven from outside via COM, so there is no socket/plugin: "connected"
# means Photoshop is running and COM answers. The photoshop-python-api library is
# lazy-imported so the backend runs without it (status = lib_missing). Because COM
# can auto-launch Photoshop, the status check attaches to an already-running
# instance (GetActiveObject) instead of Dispatch, so polling never starts Photoshop.

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager

from core.logger import get_logger

log = get_logger(__name__)

# The pip requirement, kept in one place so the install path and the user hint match.
_PIP_PACKAGE = "photoshop-python-api"


def library_available() -> bool:
    """True when photoshop-python-api can be imported in the backend env."""
    try:
        import photoshop.api  # noqa: F401 - import probe only
        return True
    except Exception:  # noqa: BLE001
        return False


@contextmanager
def com_apartment():
    """Initialise COM for the current thread.

    FastAPI runs these calls in executor threads, where COM is not initialised:
    every COM call then fails and Photoshop reads as "not running".
    """
    try:
        import comtypes
    except Exception:  # noqa: BLE001 - no comtypes: nothing to initialise
        yield
        return
    comtypes.CoInitialize()
    try:
        yield
    finally:
        comtypes.CoUninitialize()


def _active_photoshop():
    """Attach to a running Photoshop (never launches it). Raises when not running.

    photoshop-python-api is built on comtypes; pywin32 is only a fallback.
    """
    try:
        import comtypes.client
    except Exception:  # noqa: BLE001
        import win32com.client
        return win32com.client.GetActiveObject("Photoshop.Application")
    return comtypes.client.GetActiveObject("Photoshop.Application", dynamic=True)


def status() -> dict:
    """Report Photoshop connectivity as an actionable state.

    Returns a dict with:
      reason: "ok" | "lib_missing" | "not_running"
      lib_installed: bool
      connected: bool
      version: str | None
      error: str | None
    """
    if not library_available():
        return {
            "reason": "lib_missing",
            "lib_installed": False,
            "connected": False,
            "version": None,
            "error": f"{_PIP_PACKAGE} indisponible dans l'env backend",
        }
    # Attach to a running Photoshop only (never launch it from a poll).
    try:
        with com_apartment():
            app = _active_photoshop()
            version = str(getattr(app, "version", ""))
            del app
        return {
            "reason": "ok",
            "lib_installed": True,
            "connected": True,
            "version": version,
            "error": None,
        }
    except ImportError as exc:
        return {
            "reason": "lib_missing",
            "lib_installed": True,
            "connected": False,
            "version": None,
            "error": f"comtypes indisponible: {exc}",
        }
    except Exception as exc:  # noqa: BLE001 - Photoshop not running / COM not answering
        log.debug("Photoshop COM attach failed: %s", exc)
        return {
            "reason": "not_running",
            "lib_installed": True,
            "connected": False,
            "version": None,
            "error": "Photoshop n'est pas lancé (ou COM ne répond pas)",
        }


def ping() -> dict:
    """Return {ok, version} when Photoshop is reachable over COM, else {ok: False}.

    Kept for the generic /{dcc}/ping route. Delegates to status()."""
    st = status()
    return {"ok": st["connected"], "version": st["version"], "error": st["error"]}


def open_document(abs_path: str) -> dict:
    """Open a file in Photoshop over COM (launches Photoshop if needed).

    Unlike status(), this uses Dispatch so it starts Photoshop when closed, which
    is what the artist wants from a "Ouvrir dans Photoshop" action.
    Returns {ok, error}.
    """
    if not library_available():
        return {"ok": False, "error": f"{_PIP_PACKAGE} indisponible dans l'env backend"}
    try:
        import photoshop.api as ps
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    try:
        with com_apartment():
            app = ps.Application()
            app.open(abs_path)
            del app
        return {"ok": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def ensure_library() -> dict:
    """Install photoshop-python-api into the backend env when missing.

    the maintainer's choice: auto-install. In a frozen exe pip has no target, so fall back to
    a clear hint instead of failing silently.
    Returns {ok, already, installed, frozen, message}.
    """
    if library_available():
        return {"ok": True, "already": True, "installed": False, "frozen": False,
                "message": f"{_PIP_PACKAGE} déjà installé"}

    # A PyInstaller-frozen backend has no pip to install into: guide instead.
    if getattr(sys, "frozen", False):
        return {
            "ok": False, "already": False, "installed": False, "frozen": True,
            "message": (f"Installe {_PIP_PACKAGE} dans l'env Python de FLUX : "
                        f"pip install {_PIP_PACKAGE}"),
        }

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", _PIP_PACKAGE],
            capture_output=True, text=True, timeout=300,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "already": False, "installed": False, "frozen": False,
                "message": f"pip a échoué: {exc}"}

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        log.warning("photoshop lib install failed: %s", " | ".join(tail))
        return {"ok": False, "already": False, "installed": False, "frozen": False,
                "message": f"pip install {_PIP_PACKAGE} a échoué (voir logs)"}

    ok = library_available()
    return {
        "ok": ok, "already": False, "installed": ok, "frozen": False,
        "message": f"{_PIP_PACKAGE} installé" if ok else "Installé mais import toujours KO",
    }
