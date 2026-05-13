# CONTEXT — app/src

> Domain: frontend
> Path: app/src/
> Last updated: 2026-05-13
> Key internal dependencies: hooks/, components/shared/, pages/, api/client.ts, styles/

## 1. Module Role
Root frontend module. Contains the React entry point and shell orchestration. Manages app initialization, theme setup, routing, and global component layout. Bridges Electron contextBridge to the React runtime.

## 2. When to Read This Module
When starting work on page routing, app-wide styling, initialization flow, or understanding how Electron IPC is exposed to React. Also when modifying the shell layout (header, sidebar, status bar).

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| main.tsx | entry | React root mount. Initializes ReactDOM render into `#root`. | None (side effects only) |
| App.tsx | shell | Main app component. Manages routing, settings init, first-launch flow, theme vars. | `<App />` |
| types.ts | types | Shared TypeScript definitions for DCC status, activity, chat, file metadata, settings. | `DccStatusEntry`, `DccStatusMap`, `ActivityEvent`, `ChatMessage`, `FileEntry`, `ModifLog`, `Settings`, `PublishPayload`, `PublishResult` |
| electron.d.ts | types | TypeScript ambient module for `window.electronAPI` surface. Declares preload API methods. | `window.electronAPI` interface |

## 4. Useful Relations
- `App.tsx` uses `useSettings()` hook (from hooks/) to load and apply settings on startup.
- `App.tsx` conditionally renders `<FirstLaunch />` page or `<AppShell />` based on `settings.first_launch`.
- `AppShell` wraps `<TitleBar />`, `<Sidebar />`, `<StatusBar />`, and page routes via `HashRouter`.
- CSS theme variables (color, spacing) are applied from settings via inline style or class binding.

## 5. Module Entry Points
- `main.tsx` — Application bootstrap. Mounts React tree.
- `App.tsx` — Main shell. Drives routing and layout orchestration.
- `types.ts` — Type contract. Import when defining data shapes across hooks/pages/api.

## 6. Per-File Detail

**main.tsx**
Bootstrap file. Creates React root and renders `<App />` into DOM element with id `root`. No business logic.

**App.tsx**
Shell orchestration. On mount, calls `useSettings()` to fetch app config. If first launch (`settings.first_launch === true`), shows `<FirstLaunch />` page for workspace/username setup. Otherwise renders `<AppShell />` containing `TitleBar`, `Sidebar`, `StatusBar`, and `HashRouter` with page routes. Applies CSS custom properties (colors, fonts, spacing) from settings object to root element.

**types.ts**
Shared type definitions used across frontend. Includes DCC status tracking (online/offline), activity event log, chat messages, file metadata (path, mtime, size), modification logs, app settings, publisher payloads, and importer results. Single source of truth for data contracts.

**electron.d.ts**
TypeScript declaration file. Augments `window` with `electronAPI` property. Describes shape of preload-exposed IPC methods (e.g., `openDirectory()`, `sendMessage()`). Used for compile-time type checking when calling Electron APIs from React code.

## 7. Maintenance Notes
- When adding new pages, update routes in `App.tsx` (within `<HashRouter>`).
- If Electron preload API changes, update `electron.d.ts` to maintain type safety.
- Settings object shape is defined in `types.ts`. Changes require updates to API contract and storage schema.
- Theme CSS variables should be listed in styles/ documentation for consistency.
