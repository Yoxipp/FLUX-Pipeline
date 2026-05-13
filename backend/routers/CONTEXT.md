# CONTEXT — Routers

> Domain: backend
> Path: backend/routers/
> Last updated: 2026-05-13
> Key internal dependencies: features/*, main.py

## 1. Module Role
HTTP API layer providing thin REST/WebSocket wrappers around business logic in `features/`. All routers are FastAPI APIRouter instances registered in `backend/main.py` under their respective prefixes.

## 2. When to Read This Module
When adding new endpoints, modifying request/response contracts, or tracing how frontend requests map to backend features. Entry point for all HTTP traffic.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| dcc.py | Router | DCC connection & command execution. Exposes socket_manager and launcher logic. | GET /status, POST /execute, POST /connect/{dcc_name}, POST /disconnect/{dcc_name}, GET /find/{dcc_key}, GET /installed, POST /launch, WS /ws/status |
| publish.py | Router | Single publish endpoint. Thin wrapper to publish_core. | POST /publish |
| importer.py | Router | Import commands & file browser. Calls import_core and file_browser. | POST /import, GET /browse |
| activity.py | Router | Event log & team chat. Read/write activity.json and teamChat.json. | GET /activity, POST /activity/read, POST /activity/read-all, GET /activity/chat, POST /activity/chat |
| files.py | Router | File system navigation & activity logs. Exposes browse and modif_logs.json. | GET /files/projects/{project}/browse, GET /files/projects/{project}/logs |
| settings.py | Router | App configuration. Full settings CRUD + first-launch detection. | GET /settings, POST /settings/init, PUT /settings, GET /settings/users |
| folder_manager.py | Router | Project/asset/sequence/shot CRUD. Manages folder structure & tokens.json. | GET /folder/projects, POST /folder/projects, GET /folder/projects/{project}/assets, POST /folder/assets, GET /folder/projects/{project}/sequences, POST /folder/sequences, GET /folder/projects/{project}/sequences/{seq}/shots, POST /folder/shots |
| shelf.py | Router | Shelf install/remove. Manages Flux shelf in DCC user directories. | GET /shelf, POST /shelf/install, DELETE /shelf |

## 4. Useful Relations
- All routers depend on `features/` submodules for core business logic.
- `dcc.py` ↔ `features/launcher/` (DCC detection/launch) and `socket_manager` (command execution).
- `importer.py` ↔ `features/importer/` (import logic) and `file_browser` (fs navigation).
- `activity.py`, `files.py`, `settings.py`, `folder_manager.py` each wrap their respective `features/` counterpart.
- `shelf.py` ↔ `features/shelf_manager/` (install/remove logic).
- All routers are imported and registered in `backend/main.py`.

## 5. Module Entry Points
- **Application startup**: `backend/main.py` creates FastAPI app and includes all routers via `.include_router()`.
- **HTTP requests**: Frontend sends requests to `/dcc`, `/publish`, `/import`, `/activity`, `/files`, `/settings`, `/folder`, `/shelf` prefixes; routers handle them.
- **WebSocket**: `/dcc/ws/status` is the only WebSocket endpoint; pushes DCC status every 2 seconds.

## 6. Per-File Detail

### `dcc.py`
**Role:** DCC connection and command execution. Probes installed DCCs, executes commands via socket_manager, manages DCC lifecycle (launch/connect/disconnect).

#### `GET /status`
Probe all DCCs in parallel; returns availability and version info.
→ used by: Frontend to display "Which DCCs are available right now?"

#### `POST /execute`
Send a command to a DCC via socket_manager. Routes to the running DCC instance.
→ used by: Frontend shelves and tools when user executes an action in Maya/Houdini/etc.

#### `POST /connect/{dcc_name}` & `POST /disconnect/{dcc_name}`
Manage DCC socket connections. Connect sets up a listening socket; disconnect closes it.
→ used by: Frontend when user clicks "Connect to Maya" or switches DCCs.

#### `GET /find/{dcc_key}` & `GET /installed`
Auto-detect installed DCCs (scan system paths) or list all installed versions.
→ used by: Settings page, launcher dropdown.

#### `POST /launch`
Launch a DCC executable with optional scripts/plugins pre-loaded.
→ used by: Frontend "Launch" button.

#### `WS /ws/status`
WebSocket that pushes DCC status every 2 seconds (availability, version, connected/disconnected state).
→ used by: Frontend real-time status indicator.

### `publish.py`
**Role:** Single REST endpoint wrapping `features/publisher/publish_core.publish_file`. Handles versioning and file placement into pipeline structure.

#### `POST /publish`
Publish a file into the pipeline. Calls `publish_core.publish_file` with source path, asset/sequence context, and version info.
→ used by: Frontend publish dialog; DCC shelves.

### `importer.py`
**Role:** Import command dispatcher and file browser. `POST /import` sends import commands to DCCs; `GET /browse` navigates project file structure.

#### `POST /import`
Import files into a DCC. Calls `import_core.import_files_batch` which sends socket commands to the target DCC.
→ used by: Frontend import dialog.

#### `GET /browse`
Browse project folders and files. Calls `file_browser.list_folders` + `list_files_immediate` for non-recursive listing.
→ used by: Frontend file picker / project browser.

### `activity.py`
**Role:** Event log and team chat. Read-only and write access to activity.json (pipeline events) and teamChat.json (team messages).

#### `GET /activity`
Get filtered events from activity.json. Filter by type, date range, user, asset.
→ used by: Frontend activity panel.

#### `POST /activity/read` & `POST /activity/read-all`
Mark events as read in activity.json (tracks which user read which event).
→ used by: Frontend when user clicks an event or "Mark All As Read".

#### `GET /activity/chat` & `POST /activity/chat`
Read teamChat.json or append a new team chat message.
→ used by: Frontend team chat panel.

### `files.py`
**Role:** File system navigation and activity log retrieval. Wraps file browser and modif_logs.json access.

#### `GET /files/projects/{project}/browse`
Navigate file system within a project. Returns folder structure.
→ used by: Frontend file browser.

#### `GET /files/projects/{project}/logs`
Retrieve modif_logs.json for a project. Shows file modification history.
→ used by: Frontend activity / history panel.

### `settings.py`
**Role:** Application-wide configuration. Full CRUD on settings.json + first-launch scaffold. Also exposes user list.

#### `GET /settings`
Return full settings object + `first_launch` flag (indicates if app needs onboarding).
→ used by: Frontend on app startup.

#### `POST /settings/init`
First-launch scaffold. Creates default settings, project folders, tokens.json, etc.
→ used by: Frontend onboarding flow.

#### `PUT /settings`
Patch any settings field. Accepts partial updates (e.g., only update theme, leave other fields untouched).
→ used by: Frontend settings page, theme toggle, etc.

#### `GET /settings/users`
Return list of users from settings (pipeline team members).
→ used by: Frontend user dropdown, activity filter.

### `folder_manager.py`
**Role:** Project, asset, sequence, and shot CRUD. Manages folder tree structure and tokens.json.

#### `GET /folder/projects`
List all projects in the pipeline root.
→ used by: Frontend project selector.

#### `POST /folder/projects`
Create a new project. Scaffolds folder structure.
→ used by: Frontend "New Project" dialog.

#### `GET /folder/projects/{project}/assets`
List all assets in a project.
→ used by: Frontend asset browser.

#### `POST /folder/assets`
Create a new asset. Generates folder structure and tokens.json entry.
→ used by: Frontend "New Asset" dialog.

#### `GET /folder/projects/{project}/sequences` & `POST /folder/sequences`
List/create sequences. Sequences group shots for a project.
→ used by: Frontend sequence manager.

#### `GET /folder/projects/{project}/sequences/{seq}/shots` & `POST /folder/shots`
List/create shots within a sequence.
→ used by: Frontend shot manager.

### `shelf.py`
**Role:** Shelf installation and removal. Manages Flux shelf deployment to DCC user directories (Maya scripts, Houdini otl, etc.).

#### `GET /shelf`
Return list of installed shelves per DCC and version.
→ used by: Frontend shelf manager UI.

#### `POST /shelf/install`
Install Flux shelf into a DCC user directory. Calls `shelf_manager.install_shelf`.
→ used by: Frontend "Install Shelf" button.

#### `DELETE /shelf`
Remove Flux shelf from a DCC user directory.
→ used by: Frontend "Uninstall Shelf" button.

## 7. Maintenance Notes
- Each router file is deliberately thin; business logic lives in `features/`.
- Register new routers in `backend/main.py` via `app.include_router(your_router)`.
- WebSocket `/dcc/ws/status` is the only persistent connection; all other endpoints are stateless HTTP.
- Activity and settings routers are read-heavy; optimize JSON parsing if pipelines scale to thousands of events.
