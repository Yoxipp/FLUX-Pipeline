# CONTEXT — app

> Domain: frontend
> Path: app/
> Last updated: 2026-05-13
> Key internal dependencies: electron/main.ts, electron/preload.ts, src/

## 1. Module Role
Complete Electron + React 18 + TypeScript frontend application for FLUX VFX pipeline. Combines desktop runtime (Electron) with modern React UI, bridged via IPC to Python backend services.

## 2. When to Read This Module
- Read this module if building, modifying, or debugging the FLUX desktop application UI and Electron integration.
- Do not read this module if working exclusively on backend services or Python pipeline logic.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| electron/main.ts | TypeScript | Electron main process, window lifecycle, IPC handlers | `createWindow()`, IPC registry |
| electron/preload.ts | TypeScript | Context bridge for React ↔ Electron IPC | `window.electronAPI` |
| electron/python_bridge.ts | TypeScript | Python sidecar lifecycle management | `startPythonSidecar()`, `stopPythonSidecar()`, `waitForPort()` |
| src/ | React + TypeScript | UI components, hooks, pages, styles | React components tree |

## 4. Useful Relations
- `electron/main.ts` initializes Python sidecar via `python_bridge.ts:startPythonSidecar()` before opening BrowserWindow.
- `electron/preload.ts` exposes IPC handlers registered in `main.ts` to React components as `window.electronAPI`.
- `src/` components invoke `window.electronAPI` methods to communicate with Electron main and Python backend.

## 5. Module Entry Points
- `electron/main.ts` — Electron application entry (spawned by Electron runtime).
- `src/index.tsx` or equivalent — React application entry (loaded into BrowserWindow).

## 6. Per-File Detail

### `electron/main.ts`
**Role:** Electron main process. Creates frameless dark BrowserWindow (1400×900), manages app lifecycle, registers IPC handlers.

#### `createWindow()`
Creates and configures the main BrowserWindow with dark theme and frameless design.
→ calls: `python_bridge.startPythonSidecar()`

#### IPC Handlers
Registered handlers: `dialog:openFolder`, `dialog:openFile`, `app:getVersion`, `notification:show`, `shell:openPath`, `window:minimize`, `window:maximize`, `window:close`.
→ used by: `electron/preload.ts`

### `electron/preload.ts`
**Role:** Context bridge exposing safe IPC interface to React via `window.electronAPI`.

#### `window.electronAPI`
Object with methods: `openFolder()`, `openFile(filters?)`, `getAppVersion()`, `showNotification(title, body)`, `openPath(filePath)`, `windowMinimize()`, `windowMaximize()`, `windowClose()`.
→ calls: Electron IPC to `main.ts` handlers

### `electron/python_bridge.ts`
**Role:** Manages Python FastAPI sidecar process lifecycle (start, stop, port polling).

#### `startPythonSidecar()`
Spawns flux_backend.exe (production) or python backend/main.py (development), waits for port 8765 readiness. Skips if port already bound.
→ calls: `waitForPort(8765, timeout)`
→ used by: `main.ts`

#### `stopPythonSidecar()`
Terminates Python process cleanly.
→ used by: app shutdown handlers

#### `waitForPort(port, timeout)`
Polls TCP port until bound or timeout. Returns promise resolving when port is ready.

## 7. Maintenance Notes
- Update this file whenever IPC handler names, method signatures, or module structure changes.
- Keep `electron/preload.ts` exports synchronized with `main.ts` handler registry.
- Update Python sidecar spawn logic here if backend launch command or port changes.
- Sync `app.CONTEXT.md` and `app/electron/CONTEXT.md` for consistency.
