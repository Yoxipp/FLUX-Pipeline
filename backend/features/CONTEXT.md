# CONTEXT — Features

> Domain: backend
> Path: backend/features/
> Last updated: 2026-05-13
> Key internal dependencies: routers/*, socket_manager, config/

## 1. Module Role
All pipeline business logic, organized by feature. Each subdirectory implements one feature: activity logging, folder management, file import/export, DCC launcher, file publishing, and shelf management. Routers in `backend/routers/` are thin wrappers that expose these features as HTTP endpoints.

## 2. When to Read This Module
When implementing or fixing pipeline business logic, understanding how data flows from DCCs to the file system, or designing new features. Each feature subdir is self-contained; read the one(s) relevant to your task.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| activity/ | Submodule | Event log & team chat. Reads/writes activity.json and teamChat.json. | read_activity(), write_event(), read_chat(), write_chat(), list_events_filtered() |
| folder_manager/ | Submodule | Project/asset/sequence/shot hierarchy. CRUD on folder tree and tokens.json. | list_projects(), create_project(), list_assets(), create_asset(), list_sequences(), create_sequence(), list_shots(), create_shot(), read_tokens(), write_tokens() |
| importer/ | Submodule | Import commands & file browser. Sends socket messages to DCCs; browses file system. | import_files_batch(), browse_folders(), list_files_immediate() |
| launcher/ | Submodule | DCC detection & launch. Scans system for Maya, Houdini, etc.; spawns processes. | find_installed_dccs(), get_dcc_version(), launch_dcc() |
| publisher/ | Submodule | File versioning & publishing. Places files into pipeline structure with version numbers. | publish_file() |
| shelf_manager/ | Submodule | Shelf install/remove. Copies/removes Flux shelf from DCC user directories. | install_shelf(), uninstall_shelf(), list_installed_shelves() |

## 4. Useful Relations
- **activity/** ↔ routers/activity.py (HTTP endpoint wrapper).
- **folder_manager/** ↔ routers/folder_manager.py; depends on tokens.json (user session tracking).
- **importer/** ↔ routers/importer.py; depends on socket_manager (DCC communication) and launcher/ (DCC detection).
- **launcher/** ↔ routers/dcc.py; finds & launches DCCs; used by importer/ and publisher/ to route commands.
- **publisher/** ↔ routers/publish.py; depends on folder_manager/ (asset structure) and launcher/ (routing to correct DCC).
- **shelf_manager/** ↔ routers/shelf.py; depends on launcher/ (DCC paths).
- All features depend on config/ for pipeline root path, settings, and environment variables.

## 5. Module Entry Points
- **Startup**: `backend/main.py` imports routers; each router function calls its corresponding feature function.
- **HTTP requests**: Frontend sends requests to `/dcc`, `/import`, `/publish`, `/activity`, `/folder`, `/shelf`; routers dispatch to features.
- **DCC sockets**: socket_manager receives commands from DCCs; importer and publisher route responses back through features.
- **File system**: Features read/write JSON (activity.json, teamChat.json, tokens.json) and folder structures to disk.

## 6. Per-File Detail

### `activity/`
**Role:** Event log and team chat. Manages activity.json (timestamped pipeline events) and teamChat.json (team messages). All writes are append-only to prevent data loss.

#### Core functions:
- `read_activity(filter_type=None, filter_user=None, start_date=None, end_date=None)`: Load activity.json and apply filters. Returns list of events with timestamp, user, type, asset context.
- `write_event(event_type, user, asset_context, message)`: Append a new event to activity.json. Called by publisher, importer, launcher when milestones occur.
- `read_chat()`: Load teamChat.json. Returns all messages sorted by timestamp.
- `write_chat(user, message)`: Append a new team chat message. Called by activity router.
- `list_events_filtered()`: Combined read + filter; used by activity router for paginated queries.

→ used by: routers/activity.py (read/write) and publisher, importer when recording file versions, import completions, publish milestones.

### `folder_manager/`
**Role:** Project, asset, sequence, and shot hierarchy. Manages the on-disk folder tree (projects/PROJECTNAME/assets, sequences/SEQNAME/shots, etc.) and tokens.json (per-user session tracking).

#### Core functions:
- `list_projects()`: Scan pipeline root for project folders. Return names and metadata.
- `create_project(name, metadata)`: Create new project folder structure + tokens.json entry.
- `list_assets(project)`: List all assets within a project.
- `create_asset(project, name, asset_type)`: Create asset folder (geo, char, rig, etc.) with folder structure.
- `list_sequences(project)`: List all sequences in a project.
- `create_sequence(project, seq_name)`: Create sequence folder.
- `list_shots(project, sequence)`: List shots in a sequence.
- `create_shot(project, sequence, shot_name)`: Create shot folder with work, publish, reference subfolders.
- `read_tokens()`: Load tokens.json. Returns per-user session tokens.
- `write_tokens(user, token)`: Update tokens.json with new or refreshed token.

→ used by: routers/folder_manager.py (CRUD), importer (context for imports), publisher (asset path resolution).

### `importer/`
**Role:** Import command dispatcher and file browser. Sends import commands to DCCs via socket_manager; browses project files for import source selection.

#### Core functions:
- `import_files_batch(dcc_name, files, target_asset_context)`: Build import command, send via socket_manager to specified DCC. Returns job_id for tracking.
- `browse_folders(project, path=None)`: Navigate project folder tree. Return subfolders at current depth.
- `list_files_immediate(project, path)`: List files in a folder (non-recursive). Filters by file type (alembic, fbx, texture, etc.).

→ used by: routers/importer.py (HTTP endpoints), importer endpoint calls import_files_batch when user imports files, browse_folders/list_files_immediate when user navigates project browser.

### `launcher/`
**Role:** DCC detection and launch. Scans system registry/PATH to find installed DCCs (Maya, Houdini, etc.) and their versions; spawns DCC processes.

#### Core functions:
- `find_installed_dccs()`: Scan system (registry on Windows, ~/.config on Linux/Mac) for installed DCCs. Return dict of {dcc_name: [versions]}.
- `get_dcc_version(dcc_name, exe_path)`: Query DCC executable for version string.
- `launch_dcc(dcc_name, version, with_scripts=None)`: Spawn DCC process with optional pre-load scripts (Flux shelf, setup MEL, etc.). Return process PID.

→ used by: routers/dcc.py (endpoints for launch, find_installed), importer (route commands to correct DCC), publisher (same), shelf_manager (detect DCC paths).

### `publisher/`
**Role:** File versioning and publishing. Reads a working file, increments version number, places it in the pipeline structure (e.g., assets/ASSETNAME/publish/v001_filename.mb), and logs the publish to activity.json.

#### Core functions:
- `publish_file(source_path, asset_context, publish_type)`: Load source file, generate version number, write to publish folder, log event to activity.json. Return published file path and version.

→ used by: routers/publish.py (single endpoint), called when user clicks "Publish" button in DCC shelf or frontend UI.

### `shelf_manager/`
**Role:** Shelf installation and removal. Copies Flux shelf files (MEL scripts for Maya, .otl for Houdini, etc.) into DCC user directories. Manages shelf lifecycle (install, list, uninstall).

#### Core functions:
- `install_shelf(dcc_name, version)`: Copy Flux shelf to DCC user directory (e.g., ~/maya/scripts for Maya). Symlink or copy depending on OS.
- `uninstall_shelf(dcc_name, version)`: Remove Flux shelf from DCC user directory.
- `list_installed_shelves()`: Scan DCC user directories for installed Flux shelves. Return dict of {dcc_name: {version: install_path}}.

→ used by: routers/shelf.py (install/uninstall/list endpoints), depends on launcher/ to detect DCC user directory paths.

## 7. Maintenance Notes
- All JSON writes (activity.json, teamChat.json, tokens.json) use append-only or merge strategies to prevent data loss from concurrent writes.
- Publisher and importer features call activity/write_event() at key milestones; audit those calls if activity log appears incomplete.
- DCC detection (launcher/) is OS-specific; test on Windows (registry), macOS (~/.config), and Linux (same) before release.
- Shelf manager uses symlinks where possible (fast, updates reflected instantly) and falls back to copy on restricted filesystems.
- If pipeline root path changes, all features reload config on next request; no restart needed.
