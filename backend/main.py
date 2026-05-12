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
from routers import activity, dcc, files, folder_manager, importer, publish, settings, shelf

log = get_logger("main")

PORT = int(os.environ.get("FLUX_PORT", 8765))


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("[FLUX] Backend starting on port %d", PORT)
    saved_user = config.get("username")
    if saved_user:
        config.set_current_user(saved_user)
        log.info("[FLUX] Active user: %s", saved_user)
    yield
    log.info("[FLUX] Backend shutting down")


app = FastAPI(title="FLUX Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "file://"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dcc.router,            prefix="/dcc",            tags=["DCC"])
app.include_router(publish.router,        prefix="/publish",        tags=["Publisher"])
app.include_router(importer.router,       prefix="/import",         tags=["Importer"])
app.include_router(activity.router,       prefix="/activity",       tags=["Activity"])
app.include_router(files.router,          prefix="/files",          tags=["Files"])
app.include_router(settings.router,       prefix="/settings",       tags=["Settings"])
app.include_router(folder_manager.router, prefix="/folder",         tags=["FolderManager"])
app.include_router(shelf.router,          prefix="/shelf",          tags=["Shelf"])


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
