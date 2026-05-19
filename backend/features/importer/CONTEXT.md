# CONTEXT — Importer

> Domain: backend
> Path: backend/features/importer/
> Last updated: 2026-05-13
> Key internal dependencies: core.socket_manager, core.config, features.activity, features.folder_manager

## 1. Module Role

Imports files into connected DCCs via socket commands. Provides read-only file browsing for project content discovery and metadata lookup. Coordinates with socket_manager to send Python/MEL code to Maya, Houdini, etc.

## 2. When to Read This Module

When implementing file import UI, browsing project files in the frontend, retrieving file metadata and version history, or sending DCC commands from the backend.

## 3. Files Present

| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `import_core.py` | module | Send import commands to DCCs via socket | `import_file_to_dcc(dcc_name, file_path, project_name?)`, `import_files_batch(dcc_name, file_paths, project_name?)` |
| `file_browser.py` | module | Read-only file and folder enumeration with filtering | `list_files(project_path, class_filter?, type_filter?, name_filter?, last_only?)`, `list_folders(project_path, parent_rel?)`, `get_file_metadata(file_path)`, `list_files_immediate(folder_path)`, `get_file_info(file_path, project_path)` |

## 4. Useful Relations

- **Consumed by**: import UI endpoints, file picker components, DCC import handlers
- **Reads**: Project folder structure, tokens.json (via folder_manager), modif_logs.json (version history)
- **Writes**: None (read-only file browsing)
- **Depends on**: socket_manager (send_command, is_connected), activity_writer (log_import), folder_manager (parse_filename, get_logs_for_file)

## 5. Module Entry Points

1. **Import to DCC**: `import_file_to_dcc("Maya", Path("/path/file.mb"))` → sends command, logs activity.
2. **Batch import**: `import_files_batch("Maya", [Path(...), Path(...)])` → returns list of bools.
3. **Browse files**: `list_files(project_path, class_filter="CHAR")` → all CHAR files, newest-first if version history exists.
4. **Browse folders**: `list_folders(project_path, "assets")` → immediate subdirs under assets/.
5. **File metadata**: `get_file_info(Path("file.mb"), project_path)` → version, modification date, user, from modif_logs.json.

## 6. Per-File Detail

### `import_core.py`

**Role:** Build and send DCC-specific import commands via socket. Logs successful imports to activity.json.

#### `import_file_to_dcc(dcc_name, file_path, project_name?)`
Send import command to DCC. Returns True on success (and logs to activite.json). Logs warning if DCC not connected.
→ used by: /api/import endpoint, DCC file import button

#### `import_files_batch(dcc_name, file_paths, project_name?)`
Import each file sequentially. Returns list of per-file success bools.
→ used by: multi-select import UI, batch operations

### `file_browser.py`

**Role:** Safe, read-only file enumeration with path validation and filtering.

#### `list_files(project_path, class_filter?, type_filter?, name_filter?, last_only?)`
Return all publishable files under project, sorted alphabetically. Filters by parsed tokens (CLASS/TYPE/NAME). If last_only=True, only _LAST.* files. Excludes .json and modif_logs.json.
→ used by: file picker, project file list API, publish source selector

#### `list_folders(project_path, parent_rel?)`
Return immediate subdirectory names under parent_rel (relative path). Excludes hidden dirs (starting with .).
→ used by: folder tree navigation, breadcrumb paths

#### `get_file_metadata(file_path)`
Return dict with name, path, size, modified datetime, is_dir.
→ used by: file browser cells, tooltip display

#### `list_files_immediate(folder_path)`
Return immediate (non-recursive) files in folder, excluding .json files. Sorted by name.
→ used by: single-level file picker, flat file lists

#### `get_file_info(file_path, project_path)`
Return dict with file name, base_name, version, date, time, modification, user. Queries modif_logs.json for latest entry.
→ used by: file details panel, version browser, metadata display

## 7. Maintenance Notes

- **Socket commands**: _build_command() generates Python code for Maya (cmds.file import) and returns path string for Houdini (TODO: implement HIP import).
- **Path validation**: is_subpath() check ensures file is inside project_path (prevents traversal attacks).
- **JSON exclusion**: .json files excluded from file lists; modif_logs.json explicitly in _EXCLUDED_NAMES.
- **Version history**: get_file_info queries modif_logs.json in the file's folder; returns empty dict if no history exists.
- **DCC connectivity**: is_connected() check required before send_command(); returns False if DCC port unreachable.
- **User tracking**: log_import reads current user from core.config.get_current_user(); defaults to "null" if unset.
