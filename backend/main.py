# main.py — FLUX FastAPI sidecar entry point.
# Launched by Electron at startup; listens on 127.0.0.1:8765.

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure backend/ is on sys.path when run directly
sys.path.insert(0, os.path.dirname(__file__))

from core import config
from core.logger import get_logger
from routers import actions, activity, dcc, files, folder_manager, logs, production, project, publish, settings, shelf, usd_assembler

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
    # Re-stage bundled Houdini HDAs (copy-if-newer). Keeps a dev who pulled updated
    # .hda in sync so the offline shelf install works without a live rebuild.
    try:
        from installer.install_ops import deploy_houdini_hdas
        deploy_houdini_hdas()
    except Exception as exc:  # never block startup on a staging hiccup
        log.warning("[FLUX] HDA re-stage skipped: %s", exc)
    # Auto-update already-installed DCC shelves/HDAs when FLUX now ships a newer
    # copy (runs AFTER the re-stage above so it compares against fresh staging).
    # This is what carries the importer format_switch fix onto machines with a
    # stale flux_importer.hda, and keeps the Maya shelf in sync (ANIM + RIG only).
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


app = FastAPI(title="FLUX Backend", version="0.1.0", lifespan=lifespan)

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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
