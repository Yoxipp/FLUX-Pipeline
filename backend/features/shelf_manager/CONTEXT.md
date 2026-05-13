# CONTEXT — Shelf Manager

> Domain: backend
> Path: backend/features/shelf_manager/
> Last updated: 2026-05-13
> Key internal dependencies: core.logger, winreg (Windows registry)

## 1. Module Role

Installs, removes, and updates Flux shelves (Maya .mel files, Houdini .shelf files) in DCC user preference directories. Handles Windows Documents folder redirect detection via registry (OneDrive, school network paths). Lists installed DCC versions and verifies shelf installation status.

## 2. When to Read This Module

When implementing shelf installation UI, detecting installed DCC versions, managing shelf lifecycle, or resolving DCC user directory paths that may be redirected.

## 3. Files Present

| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `shelf_core.py` | module | Install/remove/update shelves; resolve DCC paths and Documents folder | `get_shelf_source_path(dcc_name)`, `get_dcc_shelf_dir(dcc_name, version)`, `get_installed_versions(dcc_name)`, `is_shelf_installed(dcc_name, version)`, `install_shelf(dcc_name, version)`, `remove_shelf(dcc_name, version)`, `update_shelf(dcc_name, version)` |

## 4. Useful Relations

- **Consumed by**: shelf installation UI endpoints, DCC setup wizard, settings management
- **Reads**: Bundled shelf source files (backend/resources/shelves/), Windows registry (Documents folder), filesystem (DCC user dirs)
- **Writes**: DCC user preference directories (copy/remove .mel and .shelf files)
- **Depends on**: core.logger, winreg (Windows registry), pathlib (Path), shutil (copy2, unlink)

## 5. Module Entry Points

1. **Install shelf**: `install_shelf("Maya", "2024")` → copies shelf to Maya user dir, returns (bool, message).
2. **Remove shelf**: `remove_shelf("Maya", "2024")` → deletes shelf file, returns (bool, message).
3. **Check installed**: `is_shelf_installed("Maya", "2024")` → bool.
4. **List versions**: `get_installed_versions("Maya")` → [str] of version numbers found on disk.
5. **Get shelf path**: `get_shelf_source_path("Maya")` → Path to bundled shelf file or None.
6. **Get DCC dir**: `get_dcc_shelf_dir("Maya", "2024")` → Path to DCC user shelf directory or None.

## 6. Per-File Detail

### `shelf_core.py`

**Role:** Central shelf management with special handling for Windows Documents folder redirect.

#### `get_shelf_source_path(dcc_name)`
Return bundled shelf source file path (resources/shelves/maya/shelf_Flux.mel, etc.), or None if DCC unsupported.
→ used by: install_shelf, update_shelf validation

#### `get_dcc_shelf_dir(dcc_name, version)`
Return user shelf directory for DCC version. Respects MAYA_APP_DIR / HOUDINI_USER_PREF_DIR env vars. Falls back to registry-resolved Documents folder. Returns None if unsupported.
→ used by: install/remove/check operations, DCC preferences UI

#### `get_installed_versions(dcc_name)`
Return sorted list of DCC version strings found on disk. Scans Documents/maya or Documents/houdini* for numeric version folders. Returns [] if none found.
→ used by: version selector dropdown, batch install UI

#### `is_shelf_installed(dcc_name, version)`
Return True if shelf file exists in the DCC user directory.
→ used by: install button enable/disable, status indicator

#### `install_shelf(dcc_name, version)`
Copy bundled shelf file to DCC user directory. Creates directory structure if needed. Returns (success: bool, message: str).
→ used by: "Install Shelf" button, setup wizard, batch installation

#### `remove_shelf(dcc_name, version)`
Delete shelf file from DCC user directory. Returns (success: bool, message: str).
→ used by: "Uninstall Shelf" button, cleanup operations

#### `update_shelf(dcc_name, version)`
Remove existing shelf (if installed) then reinstall. Returns (success: bool, message: str).
→ used by: "Update Shelf" button, version upgrade flow

## 7. Maintenance Notes

- **Documents folder detection**: Windows registry query (HKEY_CURRENT_USER/Software/Microsoft/Windows/CurrentVersion/Explorer/Shell Folders/"Personal") handles OneDrive, school network, and custom redirects. Falls back to ~/Documents on non-Windows.
- **Bundled shelves**: Located at backend/resources/shelves/{maya,houdini}/. Must exist before install; error returned if source file missing.
- **Env var priority**: MAYA_APP_DIR and HOUDINI_USER_PREF_DIR override registry Documents folder if set.
- **Version detection**: Only directories whose names start with a digit are considered versions (2022, 2023, 2024 for Maya; houdini19, houdini20 suffix version for Houdini).
- **File operations**: Uses shutil.copy2 to preserve metadata (timestamp, permissions) and pathlib for cross-platform path handling.
- **Shelf filenames**: Maya uses .mel extension (shelf_Flux.mel), Houdini uses .shelf extension (Flux.shelf). Defined in _SHELF_FILENAME dict.
- **Error messages**: All operations return human-readable (success, message) tuples for UI display.
- **Maya shelf subdirs**: Shelf stored in maya/{version}/prefs/shelves/; Houdini in houdini{version}/toolbar/.
