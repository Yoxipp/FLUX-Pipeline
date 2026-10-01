# main.py — FLUX FastAPI sidecar entry point.
# Launched by Electron at startup; listens on 127.0.0.1:8765.

from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Ensure backend/ is on sys.path when run directly
sys.path.insert(0, os.path.dirname(__file__))

from core import api_auth, config
from core.api_auth import ApiAuthMiddleware
from core.constants import APP_VERSION
from core.logger import get_logger
from routers import actions, activity, dcc, files, folder_manager, logs, production, project, publish, settings, shelf, system, team_calendar, usd_assembler

log = get_logger("main")

PORT = int(os.environ.get("FLUX_PORT", 8765))

# Persist port so Houdini HDAs can discover it without importing backend modules
try:
    import pathlib as _pl
    _port_file = _pl.Path(os.environ.get("APPDATA", ""), "FLUX", "backend_port")
    _port_file.parent.mkdir(parents=True, exist_ok=True)
    _port_file.write_text(str(PORT))
except Exception:
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("[FLUX] Backend starting on port %d", PORT)
    saved_user = config.get("username")
    if saved_user:
        config.set_current_user(saved_user)
        log.info("[FLUX] Active user: %s", saved_user)
    # Self-heal frozen installs whose config.json drifted from prefs.json (older
    # wizard wrote username only to prefs.json, leaving is_first_launch stuck at
    # True and the front-end looping through the first-launch wizard forever).
    try:
        from core import paths
        if saved_user and not paths.get_config_username():
            paths.set_config_username(saved_user)
            log.info("[FLUX] Mirrored username to config.json (self-heal)")
        saved_workspace = config.get("workspace")
        if saved_workspace and not paths.get_flux_root():
            paths.set_flux_root(saved_workspace)
            log.info("[FLUX] Mirrored workspace to config.json (self-heal)")
    except Exception as exc:  # never block startup on a bootstrap hiccup
        log.warning("[FLUX] Bootstrap self-heal skipped: %s", exc)
    # Publish switches saved in "Parametres avances" (N8, decision D1) -> env of this process.
    try:
        from features.settings.advanced import apply_saved_switches
        applied = apply_saved_switches()
        if applied:
            log.info("[FLUX] Advanced switches applied: %s", applied)
    except Exception as exc:  # never block startup on a prefs hiccup
        log.warning("[FLUX] Advanced switches skipped: %s", exc)
    # The manual ships with each FLUX version into FLUX_UPDATE (next to the installers).
    try:
        from features.system.manual import ensure_manual_in_flux_root
        ensure_manual_in_flux_root()
    except Exception as exc:  # never block startup on a manual copy hiccup
        log.warning("[FLUX] Manual copy skipped: %s", exc)
    # Keep the Maya shelf / autostart in sync with this FLUX. Houdini HDAs are only
    # ever (re)built live from source (Shelf Manager or Houdini autostart): FLUX no
    # longer ships .hda files, whose old copies used to overwrite fresh builds.
    try:
        from features.shelf_manager.shelf_core import reconcile_installed_dccs
        updated = reconcile_installed_dccs()
        if updated.get("maya") or updated.get("houdini"):
            log.info("[FLUX] DCC auto-update: %s", updated)
    except Exception as exc:  # never block startup on a reconcile hiccup
        log.warning("[FLUX] DCC auto-update skipped: %s", exc)
    yield
    # Best-effort: release ZBrush if a freeze is active, so a graceful shutdown never
    # leaves it frozen. Electron hard-kills the sidecar on quit (this may not run),
    # so the app-close release also fires from the Electron side before the kill.
    try:
        from dcc.zbrush.client import zbrush_client
        zbrush_client.release(timeout=1.0)
    except Exception as exc:  # never block shutdown on a ZBrush hiccup
        log.debug("[FLUX] ZBrush release on shutdown skipped: %s", exc)
    log.info("[FLUX] Backend shutting down")


app = FastAPI(title="FLUX Backend", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "null",                   # Electron file:// — Chromium envoie Origin: null
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    # ETag is not a CORS-safelisted response header, so the renderer (different
    # origin than 127.0.0.1:8765) cannot read it for conditional GETs unless it
    # is explicitly exposed. Required by the Phase 2 304 short-circuit.
    expose_headers=["ETag"],
)
# Added after CORS so it runs first: browser requests without the per-launch token
# are refused before reaching any route (security S1, see core/api_auth.py).
app.add_middleware(ApiAuthMiddleware)


# B3 (2026-09-28): measure before optimizing. Every request slower than
# FLUX_SLOW_REQUEST_MS (default 300) is logged with its duration.
_SLOW_MS = float(os.environ.get("FLUX_SLOW_REQUEST_MS", "300"))


@app.middleware("http")
async def log_slow_requests(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    if ms >= _SLOW_MS:
        log.warning("[slow] %s %s %.0f ms", request.method, request.url.path, ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Log any uncaught route error to the FLUX log and hand its message to the front.

    Without this a crash is a bare "HTTP 500" in the UI and the traceback only goes
    to uvicorn's stderr, which the packaged app (console=False) never shows.
    """
    log.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Erreur interne ({type(exc).__name__}) : {exc}"},
    )


@app.get(api_auth.TOKEN_PATH, tags=["Health"])
async def api_token() -> dict:
    """Hand the per-launch API token to the Electron main process (non-browser only,
    enforced by ApiAuthMiddleware)."""
    return {"token": api_auth.API_TOKEN}

@app.get("/health", tags=["Health"])
async def health() -> dict:
    """Liveness probe. Dependency-free and instant, so the Electron shell (and the
    renderer's reconnect banner) can tell a truly-ready backend from a port that is
    merely bound but not serving yet. Returns as soon as the app can route."""
    return {"ok": True}


app.include_router(dcc.router,            prefix="/dcc",            tags=["DCC"])
app.include_router(publish.router,        prefix="/publish",        tags=["Publisher"])
app.include_router(actions.router,        prefix="/actions",        tags=["Actions"])
app.include_router(activity.router,       prefix="/activity",       tags=["Activity"])
app.include_router(files.router,          prefix="/files",          tags=["Files"])
app.include_router(settings.router,       prefix="/settings",       tags=["Settings"])
app.include_router(folder_manager.router, prefix="/folder",         tags=["FolderManager"])
app.include_router(shelf.router,          prefix="/shelf",          tags=["Shelf"])
app.include_router(usd_assembler.router,  prefix="/usd",            tags=["UsdAssembler"])
app.include_router(logs.router,           prefix="/logs",           tags=["Logs"])
app.include_router(project.router,        prefix="/project",        tags=["Project"])
app.include_router(production.router,     prefix="/production",     tags=["Production"])
app.include_router(team_calendar.router,  prefix="/calendar",       tags=["Calendar"])
app.include_router(system.router,         prefix="/system",         tags=["System"])


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
