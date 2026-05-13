# CONTEXT — Maya DCC Bridge

> Domain: backend
> Path: backend/dcc/maya/
> Last updated: 2026-05-13
> Key internal dependencies: core.publish, config

## 1. Module Role
Complete Maya-to-Hub integration. Manages TCP command server for bidirectional communication, builds Maya commands for import/export/publish, and provides a startup hook and shelf UI for launching the Hub from within Maya.

## 2. When to Read This Module
When fixing Maya connection issues, adding new export/import file formats to Maya, debugging publish workflows triggered from Maya, or modifying the Maya shelf button.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `maya_connection.py` | module | TCP server lifecycle + command dispatch (dual-context: inside Maya and from Hub). | `start_server()`, `stop_server()`, `is_server_running()`, `open_hub()`, `execute_command()` |
| `maya_export.py` | module | Builders for Maya export commands (FBX, USD, Alembic, mayaBinary). | `build_fbx_export()`, `build_usd_export()`, `build_abc_export()`, `build_mb_export()` |
| `maya_import.py` | module | Builders for Maya import commands (FBX, USD, Alembic, mayaBinary). | `build_fbx_import()`, `build_usd_import()`, `build_abc_import()`, `build_mb_import()` |
| `maya_publish.py` | module | High-level publish entry point: triggers export, then calls core.publish. | `publish_from_maya()` |
| `maya_shelf.py` | module | Shelf MEL/Python code as Python strings (deployed to Maya). | `get_shelf_button_code()` |
| `startup/flux_bridge.py` | script | Maya userSetup.py hook. Auto-starts commandPort on Maya launch. | — |

## 4. Useful Relations
**Depends on:** core.publish (for publish orchestration), config (for Maya port config), paths (for workspace paths).
**Consumed by:** Hub routers (for execute_command), Maya startup (for flux_bridge), Maya shelf (for open_hub).
**Parallel modules:** backend/dcc/houdini (similar structure), backend/core/publish.

## 5. Module Entry Points
- **From Hub (main path):** Import `maya_connection.execute_command(cmd)` to send MEL/Python to Maya.
- **From Maya startup:** `flux_bridge.py` runs on Maya launch; calls `maya_connection.start_server(port)`.
- **From Maya shelf:** User clicks shelf button → calls `maya_connection.open_hub()` to open Hub in Maya workspace.
- **From Maya UI (publish):** Calls `maya_publish.publish_from_maya()` to export and publish scene.

## 6. Per-File Detail

### `maya_connection.py`
**Role:** Manage Maya's commandPort server and dispatch commands from Hub to Maya.
#### `start_server(port=2023)`
Start TCP server on specified port inside Maya. Only callable from within Maya.
→ used by: `startup/flux_bridge`, Maya shelf

#### `stop_server(port=2023)`
Shutdown TCP server on specified port. Only callable from within Maya.
→ used by: cleanup routines, restart operations

#### `is_server_running(port=2023)`
Check if commandPort is active on specified port. Callable from Hub or Maya.
→ used by: Hub health checks, Hub connection validation

#### `open_hub()`
Launch FLUX Hub application in Maya's workspace. Only callable from within Maya.
→ used by: Maya shelf button

#### `execute_command(cmd, port=2023)`
Send MEL or Python command to a running Maya instance. Only callable from Hub.
→ used by: Hub routers (export, import, publish commands)

### `maya_export.py`
**Role:** Build Maya-native export commands for common file formats.
#### `build_fbx_export(scene_path, output_path, options)`
Generate MEL command to export FBX. Returns command string.
→ used by: core.publish workflows

#### `build_usd_export(scene_path, output_path, options)`
Generate MEL command to export USD. Returns command string.
→ used by: core.publish workflows

#### `build_abc_export(scene_path, output_path, options)`
Generate MEL command to export Alembic. Returns command string.
→ used by: core.publish workflows

#### `build_mb_export(scene_path, output_path, options)`
Generate MEL command to export as Maya Binary. Returns command string.
→ used by: core.publish workflows

### `maya_import.py`
**Role:** Build Maya-native import commands for common file formats.
#### `build_fbx_import(file_path, namespace, options)`
Generate MEL command to import FBX. Returns command string.
→ used by: core.publish workflows

#### `build_usd_import(file_path, namespace, options)`
Generate MEL command to import USD. Returns command string.
→ used by: core.publish workflows

#### `build_abc_import(file_path, namespace, options)`
Generate MEL command to import Alembic. Returns command string.
→ used by: core.publish workflows

#### `build_mb_import(file_path, namespace, options)`
Generate MEL command to import as Maya Binary. Returns command string.
→ used by: core.publish workflows

### `maya_publish.py`
**Role:** High-level entry point for publishing a Maya scene via FLUX.
#### `publish_from_maya(scene_file, format, publish_config)`
Export scene in specified format, then trigger core.publish pipeline. Orchestrates end-to-end publish.
→ used by: Maya shelf (publish button), Hub publish routers

### `maya_shelf.py`
**Role:** Generate Maya shelf MEL/Python code as strings for deployment.
#### `get_shelf_button_code()`
Return MEL/Python code defining the FLUX shelf button. Code calls `open_hub()` and `publish_from_maya()`.
→ used by: deployment/installation scripts

### `startup/flux_bridge.py`
**Role:** Maya userSetup.py hook to auto-start commandPort on launch.
**Execution:** Auto-sourced by Maya on startup. Calls `maya_connection.start_server()` silently.

## 7. Maintenance Notes
All export/import builders return MEL command strings (not executed); execution happens via `execute_command()` from Hub or Maya shelf. Ensure command strings are valid MEL/Python syntax and handle option dicts carefully. The dual-context design means connection functions must detect their caller context (inside Maya vs. from Hub) — test both paths when modifying. Port configuration is stored in config.json; maintain consistency across Hub and Maya startup.
