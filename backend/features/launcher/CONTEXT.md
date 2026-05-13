# CONTEXT — Launcher

> Domain: backend
> Path: backend/features/launcher/
> Last updated: 2026-05-13
> Key internal dependencies: core.config, core.constants, core.socket_manager

## 1. Module Role

Detects installed DCCs on the system (Maya, Houdini, Nuke, Substance, ZBrush, etc.), launches them as detached processes, and monitors their connection status. Maintains custom executable paths for user-specified DCC locations. Provides real-time DCC status via async polling.

## 2. When to Read This Module

When implementing DCC launch buttons, detecting available DCCs for the user's setup, managing custom DCC paths, or providing real-time connection status in the UI.

## 3. Files Present

| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `launcher_core.py` | module | Detect and launch DCC applications | `get_installed_dccs()`, `launch_dcc(dcc_name)`, `get_custom_exe_path(dcc_name)`, `set_custom_exe_path(dcc_name, path)`, `find_dcc_exe(dcc_key)` |
| `connection_monitor.py` | module | Async polling of DCC port status | `poll_dcc_status()`, `dcc_status_stream(interval_ms?)` |

## 4. Useful Relations

- **Consumed by**: DCC launcher UI endpoints, connection status dashboard, WebSocket status streams
- **Reads**: User config (custom DCC paths), system filesystem (DCC default install dirs via glob), Windows registry (for env var fallbacks)
- **Writes**: User config (custom DCC exe paths)
- **Depends on**: core.config (get/set_dcc_exe), core.constants (DCC_EXE_PATTERNS, DCC_PORTS), socket_manager (probe_port for connection checks)

## 5. Module Entry Points

1. **Detect DCCs**: `get_installed_dccs()` → {dcc_name: exe_path} for all found DCCs.
2. **Launch DCC**: `launch_dcc("Maya")` → launches as detached process, returns bool.
3. **Custom path**: `set_custom_exe_path("Maya", "C:\\custom\\maya.exe")` → persist user preference.
4. **Find DCC**: `find_dcc_exe("maya")` → glob-scan, save to config, return path or None.
5. **Status stream**: `dcc_status_stream(interval_ms=1000)` → async generator yielding {dcc_name: bool} every interval.

## 6. Per-File Detail

### `launcher_core.py`

**Role:** DCC detection and launching. Checks user config, then auto-detects via glob patterns.

#### `get_installed_dccs()`
Return {dcc_name: exe_path} for all detected DCCs. Checks custom paths first, then glob-scans default dirs.
→ used by: DCC launcher dropdown, status indicators, installation checks

#### `launch_dcc(dcc_name)`
Launch DCC as detached process (Windows DETACHED_PROCESS flag). Returns True on success, logs warnings on failure.
→ used by: "Launch Maya/Houdini" button, DCC startup flow

#### `get_custom_exe_path(dcc_name)`
Return user-configured exe path for DCC, or None if not set.
→ used by: settings panel, custom path display

#### `set_custom_exe_path(dcc_name, path)`
Persist custom exe path in user config. No return value, logs to activity.
→ used by: "Browse for DCC executable" form, custom path settings

#### `find_dcc_exe(dcc_key)`
Glob-scan default install directories for DCC. *dcc_key* is frontend lowercase (maya, substance_painter). Saves path to config if found, returns path or None.
→ used by: "Auto-find DCC" button, first-time setup wizard

### `connection_monitor.py`

**Role:** Async DCC port polling for real-time connection status. Feeds WebSocket status endpoints.

#### `poll_dcc_status()`
Return async-awaitable dict {dcc_name: bool} of current connection status. Runs port probes in executor.
→ used by: WebSocket /api/dcc-status endpoint, status refresh endpoints

#### `dcc_status_stream(interval_ms?)`
Async generator yielding {dcc_name: bool} status every *interval_ms* milliseconds. Runs indefinitely.
→ used by: WebSocket streaming, real-time connection indicators

## 7. Maintenance Notes

- **DCC detection**: Uses _FRONTEND_KEY_MAP to map frontend keys (maya, substance_painter) to internal DCC_EXE_PATTERNS keys (Maya, SubstanceP).
- **Windows processes**: DETACHED_PROCESS (0x00000008) flag ensures launched DCC continues running if hub window closes.
- **Glob patterns**: DCC_EXE_PATTERNS defined in core.constants; matches version-specific install paths (e.g., Program Files/Autodesk/Maya*/bin/).
- **Custom path priority**: Always checked before auto-detection; allows users to override default installations.
- **Version selection**: When multiple versions found, glob results sorted and highest version chosen.
- **Port probing**: DCC_PORTS from core.constants; connection_monitor uses socket_manager.probe_port() which is blocking (run in executor in async context).
- **Monitor interval**: MONITOR_INTERVAL_MS constant in core.constants; typical 1000ms (1 second) refresh rate.
