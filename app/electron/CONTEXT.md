# CONTEXT — electron

> Domain: electron-main
> Path: app/electron/
> Last updated: 2026-05-13
> Key internal dependencies: main.ts, preload.ts, python_bridge.ts

## 1. Module Role
Electron runtime integration layer for FLUX. Manages desktop window lifecycle, inter-process communication (IPC) bridges to React, and Python backend sidecar process startup and health monitoring.

## 2. When to Read This Module
- Read this module if adding IPC handlers, debugging window behavior, or managing Python backend integration.
- Do not read this module if working only in React components or backend Python services.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| main.ts | TypeScript | Electron main process, BrowserWindow creation, IPC handler registry | `createWindow()`, app lifecycle handlers |
| preload.ts | TypeScript | Secure context bridge exposing IPC to renderer | `window.electronAPI` object |
| python_bridge.ts | TypeScript | Python sidecar lifecycle and port polling | `startPythonSidecar()`, `stopPythonSidecar()`, `waitForPort()` |

## 4. Useful Relations
- `main.ts` calls `python_bridge.startPythonSidecar()` at app startup before opening BrowserWindow.
- `main.ts` registers IPC handlers that are exposed by `preload.ts` as `window.electronAPI` methods.
- `python_bridge.ts` is isolated and consumed only by `main.ts` for sidecar management.

## 5. Module Entry Points
- `main.ts` — Primary entry point (spawned by Electron runtime at app launch).

## 6. Per-File Detail

### `main.ts`
**Role:** Electron main process. Creates frameless dark BrowserWindow (1400×900), manages app lifecycle, registers IPC message handlers.

#### `createWindow()`
Initializes and displays BrowserWindow with dark theme, frameless design, dev tools in development mode.
→ calls: `python_bridge.startPythonSidecar()`
→ used by: app.whenReady event

#### `dialog:openFolder` handler
IPC handler. Opens native folder selection dialog, returns chosen path to renderer.
→ used by: React component via `window.electronAPI.openFolder()`

#### `dialog:openFile` handler
IPC handler. Opens native file selection dialog with optional filters, returns chosen path.
→ used by: React component via `window.electronAPI.openFile(filters?)`

#### `app:getVersion` handler
IPC handler. Returns application version string from package.json.
→ used by: React component via `window.electronAPI.getAppVersion()`

#### `notification:show` handler
IPC handler. Displays system notification with title and body text.
→ used by: React component via `window.electronAPI.showNotification(title, body)`

#### `shell:openPath` handler
IPC handler. Opens file or folder in system file explorer.
→ used by: React component via `window.electronAPI.openPath(filePath)`

#### `window:minimize`, `window:maximize`, `window:close` handlers
IPC handlers. Control window state (minimize, maximize, close).
→ used by: React component via `window.electronAPI.windowMinimize()`, `.windowMaximize()`, `.windowClose()`

#### App lifecycle handlers
Responds to `app.whenReady`, `window-all-closed`, `activate` events to manage window and process lifecycle.

### `preload.ts`
**Role:** Secure context bridge using Electron's contextBridge API. Exposes only safe IPC methods to React renderer process.

#### `window.electronAPI`
Object exposing methods: `openFolder()`, `openFile(filters?)`, `getAppVersion()`, `showNotification(title, body)`, `openPath(filePath)`, `windowMinimize()`, `windowMaximize()`, `windowClose()`.
→ calls: Electron ipcRenderer.invoke() to main.ts handlers

### `python_bridge.ts`
**Role:** Manages Python FastAPI backend sidecar (flux_backend.exe in production, python backend/main.py in development). Handles startup, shutdown, and port readiness polling.

#### `startPythonSidecar()`
Spawns Python backend process. Uses flux_backend.exe in production or `python backend/main.py` in development. Polls port 8765 with configurable timeout. Skips launch if port already bound (allows manual dev mode).
→ calls: `waitForPort(8765, timeout)`
→ used by: `main.ts` at app startup

#### `stopPythonSidecar()`
Terminates Python background process cleanly (SIGTERM or equivalent).
→ used by: app shutdown or cleanup handlers

#### `waitForPort(port, timeout)`
Polls TCP port at 500ms intervals until bound or timeout expires. Returns promise that resolves when port is ready.
→ used by: `startPythonSidecar()`

## 7. Maintenance Notes
- Update this file whenever IPC handler signatures or names change.
- Keep exported methods in `preload.ts` synchronized with handler names in `main.ts`.
- Update Python sidecar spawn logic if backend launch command, entry point, or port 8765 changes.
- Document any new IPC handlers added to `main.ts` in Section 6.
- Coordinate updates with `app/CONTEXT.md` to maintain consistency across app and electron modules.
