# CONTEXT — Publisher

> Domain: backend
> Path: backend/features/publisher/
> Last updated: 2026-05-13
> Key internal dependencies: features.folder_manager, features.activity, core.paths, core.json_manager

## 1. Module Role

Core publish pipeline: resolves destination paths from filename tokens, archives previous versions, copies files, logs modifications. Computes version numbers by scanning folders for existing vXXX patterns. Maintains per-folder modification logs (modif_logs.json) with user/date/description metadata.

## 2. When to Read This Module

When publishing files from disk to project folders, implementing version control UI, querying file modification history, or resolving token-based publish destinations.

## 3. Files Present

| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `publish_core.py` | module | Main publish pipeline: resolve, version, copy, log | `publish_file(source_path, project_path, description, user, project_name?)`, `resolve_publish_path(project_path, filename)`, `rename_last_to_versioned(dest_folder, base_name, next_version, padding?)`, `publish_from_dcc(dcc_name, ...)` |
| `version_resolver.py` | module | Compute next version number by scanning published files | `get_next_version(folder_path, base_name, padding?)`, `get_last_file(folder_path, base_name)` |
| `modif_log.py` | module | Read/write modif_logs.json per publish folder | `append_log(folder_path, name, version, modification, user)`, `read_logs(folder_path)`, `get_logs_for_file(folder_path, base_name)` |

## 4. Useful Relations

- **Consumed by**: publish API endpoints, DCC export handlers (future), activity dashboard
- **Reads**: Project structure, tokens.json (CLASS/NAME paths), modif_logs.json per folder
- **Writes**: Published files (as _LAST.ext), versioned files (_v001.ext, _v002.ext), modif_logs.json, activite.json
- **Depends on**: folder_manager (parse_filename, get_base_name, load_tokens), activity_writer (log_publish), core.paths (ensure_dir)

## 5. Module Entry Points

1. **Publish file**: `publish_file(Path("file.mb"), project_path, "description", "user")` → returns dest Path or None.
2. **Resolve destination**: `resolve_publish_path(project_path, "CHAR_RIG_HERO_A_LAST.mb")` → returns dest folder Path or None.
3. **Version history**: `get_logs_for_file(Path("folder"), "CHAR_RIG_HERO_A")` → list of modif log entries newest-first.
4. **Next version**: `get_next_version(Path("folder"), "CHAR_RIG_HERO_A")` → integer (1, 2, 3, ...).
5. **Last file**: `get_last_file(Path("folder"), "CHAR_RIG_HERO_A")` → Path to _LAST.ext or None.

## 6. Per-File Detail

### `publish_core.py`

**Role:** End-to-end publish: filename parsing, path resolution, version archiving, file copy, metadata logging.

#### `publish_file(source_path, project_path, description, user, project_name?)`
Main entry point. Steps: parse filename, resolve dest folder, compute next version, rename old LAST → vXXX, copy source → dest as _LAST.ext, log to modif_logs.json and activite.json. Returns dest LAST Path or None on failure.
→ used by: publish API endpoint, file upload handler

#### `resolve_publish_path(project_path, filename)`
Return destination folder Path for filename. Asset: project/<CLASS_path>/<NAME>/<type_subfolder>/. Shot: project/<CLASS_template{seq=SEQ, shot=SHOT}>/. Returns None if unparseable or missing tokens.
→ used by: publish destination preview, path resolution verification

#### `rename_last_to_versioned(dest_folder, base_name, next_version, padding?)`
If _LAST.ext exists, rename to _v{next_version}.ext. Returns versioned Path or None if no LAST existed.
→ used by: publish pipeline (archive old LAST before copying new)

### `version_resolver.py`

**Role:** Scan published folders for version patterns, compute next available version number.

#### `get_next_version(folder_path, base_name, padding?)`
Scan folder for <base_name>_v###[.ext] files, return max+1. Returns 1 if no versioned files exist.
→ used by: publish_core to determine new version number, version dropdown UI

#### `get_last_file(folder_path, base_name)`
Return Path to <base_name>_LAST[.ext] file, or None if not found.
→ used by: publish_core to archive old file, file browser (last_only filter)

### `modif_log.py`

**Role:** Per-folder JSON log of file modifications. Tracks user, version, description, date/time.

#### `append_log(folder_path, name, version, modification, user)`
Append entry to modif_logs.json. Creates file if absent. Returns True on success.
→ used by: publish_core after successful file copy, any modification event

#### `read_logs(folder_path)`
Load modif_logs.json, return all entries sorted by date/time descending (newest first).
→ used by: file history UI, version browser, metadata queries

#### `get_logs_for_file(folder_path, base_name)`
Return log entries for files with name starting with *base_name*, newest first.
→ used by: file_browser.get_file_info, file history widget

## 7. Maintenance Notes

- **Version naming**: Versions use padding=3 by default (v001, v002, ..., v999). Configured per publish folder scan.
- **LAST file semantics**: _LAST.ext is always the "active" version. On publish, old LAST → vXXX, new source → LAST. Files without LAST status are treated as immutable archives.
- **Path templates**: Asset destinations can use token templates (not yet used for shots). Shots may use {seq=SEQ, shot=SHOT} in CLASS token path.
- **Modification log schema**: Each entry has name (base filename), version, date (YYYY-MM-DD), time (HH:MM), modification (user description), user (who published).
- **Orphaned versions**: Old versioned files (_v001.ext) remain on disk; pruning is manual or via separate cleanup script.
- **Publish from DCC**: publish_from_dcc() is a stub (TODO in 08_dcc_maya, 09_dcc_houdini phases). Will use socket_manager to trigger DCC export, then publish the temp file.
