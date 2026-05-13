# CONTEXT — Backend

> Domain: backend
> Path: backend/
> Last updated: 2026-05-13
> Key internal dependencies: core

## 1. Module Role
FastAPI sidecar server launched by Electron at startup. Exposes 8 routers (dcc, publish, import, activity, files, settings, folder, shelf) over HTTP on port 8765.

## 2. When to Read This Module
When integrating Electron frontend with backend services, adding new API routes, or debugging server startup and CORS behavior.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `main.py` | Python | FastAPI entry point; registers routers, CORS, lifespan | `app` (FastAPI instance), uvicorn runner |
| `requirements.txt` | Text | Python dependencies | fastapi, uvicorn, pydantic, websockets, aiofiles |

## 4. Useful Relations
- **Startup chain:** Electron → uvicorn → FastAPI app → 8 routers (all in `/routers/`)
- **Config loading:** `main.py` lifespan calls `core.config.get_current_user()` at startup
- **CORS origins:** localhost:5173 (dev frontend) + null (Electron renderer process)
- **Port source:** `FLUX_PORT` env var (default 8765)

## 5. Module Entry Points
- `main.py` — Run via `uvicorn backend.main:app --port 8765`
- Reads config username in lifespan before accepting requests

## 6. Per-File Detail

### `main.py`
**Role:** Entry point. Initializes FastAPI app, registers all routers, configures CORS and lifespan hooks.
- Creates FastAPI instance
- Registers 8 routers from `/routers/` (dcc, publish, import, activity, files, settings, folder, shelf)
- CORS: allows origin `localhost:5173` + `null`
- Lifespan: reads config username at startup
- Runs via uvicorn on `FLUX_PORT` env var (default 8765)

### `requirements.txt`
**Role:** Declares Python dependencies for FastAPI server and async utilities.
- Core: fastapi, uvicorn, pydantic, websockets
- I/O: aiofiles

## 7. Maintenance Notes
- CORS origins are hardcoded for dev (localhost:5173) and Electron (null). Update if frontend URL changes.
- Port is configurable via `FLUX_PORT`. Ensure no conflicts on startup.
- All 8 routers must be registered before app runs; missing router will cause import error.
- Lifespan config read is synchronous; blocking I/O here delays startup.
