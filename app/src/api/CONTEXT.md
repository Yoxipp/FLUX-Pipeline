# CONTEXT — app/src/api

> Domain: frontend
> Path: app/src/api/
> Last updated: 2026-05-14
> Key internal dependencies: types.ts (from parent), backend at http://127.0.0.1:8765

## 1. Module Role
HTTP API client layer. Single typed HTTP client to FastAPI backend. Exposes all backend endpoints as a unified `api` object with typed request/response contracts. Handles route construction, error handling, and marshaling between React and backend.

## 2. When to Read This Module
When calling backend endpoints from hooks or pages. When adding new backend routes (update client.ts). When debugging network requests or API response shapes. When understanding the contract between frontend and backend.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| client.ts | api | HTTP client singleton. Exports `api` object with all typed endpoint methods. | `api` (namespace with ~30 methods across 8 domains) |

## 4. Useful Relations
- Every hook and page imports from `api/client.ts` to call backend endpoints.
- Request/response types use definitions from `types.ts` (parent directory).
- Backend runs at fixed address `http://127.0.0.1:8765` (hardcoded in client).
- Error responses are assumed to be JSON with `{detail}` or `{error}` shape.

## 5. Module Entry Points
- `api/client.ts` — Single entry point. Import `api` object and call methods by domain.
- Method naming: `api.<domain>.<action>()` (e.g., `api.settings.getSettings()`, `api.dcc.connectDcc(dcc)`).

## 6. Per-File Detail

**client.ts**
Singleton HTTP client wrapping fetch API. Base URL fixed to `http://127.0.0.1:8765`. Exports single `api` object grouped by domain:

Settings: `getSettings()`, `initFirstLaunch(workspace, username)`, `updateSettings(patch)`, `listUsers()`. Manages app config and user identity setup. `updateSettings(patch)` accepts configuration changes including theme fields, last_project, dcc_path, username, and workspace (triggers workspace/pipeline root directory change on the backend).

DCC: `getDccStatus()`, `connectDcc(dcc)`, `disconnectDcc(dcc)`, `executeCommand(dcc, command)`, `findDccExe(dcc)`, `getInstalledDccs()`, `launchDcc(dcc, exe_path?)`. Controls 3D software (Maya, Houdini, Blender) connections and command execution.

Publisher: `publish(payload: PublishPayload)`. Triggers asset publishing workflow.

Importer: `importFiles(dcc, file_paths, project_name?)`, `browseImport(project_name, subpath?)`. File ingest and project directory browsing.

Activity: `getActivity(params?)`, `markEventRead(event_id)`, `markAllRead()`, `getChat(limit?)`, `sendChat(message, user?)`. Logs, notifications, and chat UI.

Files: `browseProject(project_name, subpath?)`, `getModifLogs(project_name, subpath?)`. File browsing and version history.

FolderManager: `getProjects()`, `createProject(name)`, `getAssets(project, class_token?)`, `createAsset(...)`, `getSequences(project)`, `createSequence(...)`, `getShots(...)`, `createShot(...)`. Folder hierarchy and metadata management.

Shelf: `getShelves()`, `installShelf(dcc, version)`, `removeShelf(dcc, version)`. Tool shelf lifecycle for DCCs.

## 7. Maintenance Notes
- Base URL `http://127.0.0.1:8765` is environment-specific. Consider extracting to env var or settings if multi-environment support is needed.
- All responses assume JSON. If backend returns non-JSON (e.g., file download), add a separate method or wrapper.
- Type definitions for payloads/responses live in parent `types.ts`. Keep in sync when backend schema changes.
- Error handling assumes backend returns `{detail: string}` or `{error: string}`. Update if backend error format changes.
- Method signatures are TypeScript-first. Check implementation for actual JSON payload shape sent to backend.
