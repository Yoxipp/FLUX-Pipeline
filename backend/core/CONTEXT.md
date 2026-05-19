# CONTEXT — Core

> Domain: backend
> Path: backend/core/
> Last updated: 2026-05-13
> Key internal dependencies: none (zero cross-module imports)

## 1. Module Role
Shared infrastructure layer. Contains only configuration, constants, logging, paths, JSON utilities, and DCC socket management. No business logic. Used by all other backend modules.

## 2. When to Read This Module
When adding new config keys, hardcoding constants, setting up logging, managing file paths, reading/writing JSON, or communicating with DCCs via TCP.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `config.py` | Python | User settings store; in-memory + file-based | `is_first_launch()`, `create_user()`, `set_current_user()`, `get_current_user()`, settings getters/setters |
| `constants.py` | Python | Flux-wide constants; no imports from other flux modules | `DCC_PORTS`, `DCC_COLORS`, `TOKEN_TYPES`, `USD_PRESETS`, `THEME_*` presets |
| `json_manager.py` | Python | Atomic JSON read/write helpers | `read_json()`, `write_json()`, `update_json()`, `append_to_list()` |
| `logger.py` | Python | Centralized logging setup | `get_logger(name)` returns configured logger |
| `paths.py` | Python | Single source of truth for path construction | `get_flux_root()`, `get_projects_dir()`, `get_user_dir()`, `ensure_dir()`, etc. |
| `socket_manager.py` | Python | TCP connection manager for DCCs | Singleton `socket_manager`, class `SocketManager` with `connect()`, `send_command()`, etc. |

## 4. Useful Relations
- **Config loading chain:** `config.py` → `paths.py` (for file paths) → `json_manager.py` (for I/O)
- **Logging everywhere:** All modules call `get_logger(__name__)` from `logger.py`
- **Path consistency:** All code uses `paths.py` exports; never hardcode paths
- **DCC comms:** All DCC TCP communication routed through `socket_manager` singleton (avoids multiple connections)
- **Constants are global:** All magic values live in `constants.py`; never hardcode in business logic

## 5. Module Entry Points
- `config.get_current_user()` — called by `main.py` lifespan at startup
- `paths.get_flux_root()` — called first to establish app root
- `logger.get_logger(__name__)` — called by all modules
- `socket_manager.connect(dcc_name)` — called by routers to communicate with DCCs

## 6. Per-File Detail

### `config.py`
**Role:** Read/write user preferences and settings. Maintains active user in memory; stores in config.json and prefs.json.
- `is_first_launch()` → bool: true if config.json missing
- `create_user(name, workspace)` → None: create new user + workspace dir
- `set_current_user(name)` → None: update active user in memory
- `get_current_user()` → str: active username
- `get(key, default)` → any: read setting value
- `set(key, value)` → None: write setting value
- `get_last_project()`, `set_last_project(name)` → track last opened project
- `get_theme()`, `set_theme(bg, surface, fg, accent)` → color scheme
- `get_dcc_exe(dcc_name)`, `set_dcc_exe(dcc_name, path)` → DCC executable paths

### `constants.py`
**Role:** All Flux-wide constants. No imports from other Flux modules; safe for any module to import.
- `DCC_PORTS` dict: DCC name → TCP port
- `DCC_COLORS` dict: DCC name → color hex
- `DCC_EXE_PATTERNS` dict: DCC name → exe regex patterns
- `TOKEN_TYPES` list: token type names
- `DEFAULT_CLASS_TOKENS` dict: class → default token assignments
- `USD_PRESETS` dict: USD preset configs
- `JSON_ACTIVITY`, `JSON_CHAT`, `JSON_TOKENS`, `JSON_MODIF_LOG`: JSON file constants
- `FLUX_ROOT_DIRS`, `FLUX_MARKER_FILENAME`: directory structure constants
- `THEME_DEFAULT_*`, `THEME_*_PRESETS`: theme color constants
- `SOCKET_TIMEOUT_S` int: DCC socket timeout in seconds

### `json_manager.py`
**Role:** Atomic JSON I/O helpers. All read/write operations safe against corruption on failure.
- `read_json(path)` → dict: returns {} if file missing or invalid
- `write_json(path, data, indent=2)` → bool: atomic via temp file + rename; returns true on success
- `update_json(path, key, value)` → bool: read, modify key, write atomically
- `append_to_list(path, list_key, item)` → bool: read, append to list at key, write atomically

### `logger.py`
**Role:** Centralized logging setup. All modules use this instead of bare `logging` module.
- `get_logger(name)` → Logger: returns Python logger configured for Flux (handlers, format, level)

### `paths.py`
**Role:** Single source of truth for path construction. No hardcoded paths elsewhere in codebase.
- `get_flux_root()` → str: Flux project root directory
- `set_flux_root(path)` → None: override root (for testing)
- `get_config_username()`, `set_config_username(name)` → manage config file username
- `get_users_dir()`, `get_projects_dir()`, `get_config_dir()` → base directories
- `get_user_dir(username)`, `get_project_path(project_name)` → user/project paths
- `get_project_tokens_path(project_name)`, `get_activity_path()`, `get_chat_path()` → file paths
- `get_flux_marker_path(root?)` → marker file location
- `is_flux_root(directory)` → bool: validate directory structure
- `ensure_dir(path)`, `path_exists_safe(path)`, `normalize_path(path)` → I/O helpers
- `is_subpath(child, parent)` → bool: path containment check

### `socket_manager.py`
**Role:** Singleton TCP connection manager for all DCC communications. Handles reconnect logic, timeouts, multi-DCC coordination.
- `socket_manager` module-level instance: use this, not creating new SocketManager()
- `connect(dcc_name)` → bool: open TCP connection to DCC on its port
- `disconnect(dcc_name)` → None: close connection for DCC
- `is_connected(dcc_name)` → bool: connection status
- `probe(dcc_name)` → bool: test if DCC is running (non-blocking)
- `probe_port(port, timeout)` → bool: low-level TCP port probe
- `known_dccs()` → list: all DCC names in constants
- `send_command(dcc_name, command)` → response: send command, raise on failure
- `send_command_safe(dcc_name, command)` → response: send command, auto-reconnect once on failure

## 7. Maintenance Notes
- **No cross-module imports:** `core/` imports only stdlib. This keeps it lightweight and cyclic-import free.
- **Config file paths:** Hardcoded in `paths.py`; update there if Flux directory structure changes.
- **JSON atomicity:** Always use `json_manager` for reads/writes; never raw open/json.load. Prevents corruption on crash.
- **Logging levels:** Set via `logger.py` config function; no per-file overrides.
- **DCC socket timeout:** Set in `constants.SOCKET_TIMEOUT_S`; shared across all DCC connections.
