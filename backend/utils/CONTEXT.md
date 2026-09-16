# CONTEXT — Backend Utilities

> Domain: backend
> Path: backend/utils/
> Last updated: 2026-05-13
> Key internal dependencies: config, paths, core.publish

## 1. Module Role
Thin utility wrapper layer over core backend services. Simplifies user/project management and token handling for use by routers, features, and DCC bridges. Abstracts common patterns (config access, file system operations) to reduce duplication.

## 2. When to Read This Module
When adding new user or project endpoints, implementing features that need user/project context, or building utilities for token manipulation and validation.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `user_utils.py` | module | User management wrappers over config and paths. | `get_current_user()`, `set_current_user()`, `list_users()`, `user_exists()`, `create_user_dir()` |
| `project_utils.py` | module | Project path and listing helpers wrapping paths module. | Project-level utility functions |
| `token_utils.py` | module | Token formatting, parsing, and manipulation. | Token manipulation helpers |

## 4. Useful Relations
**Depends on:** config (user/project config state), paths (directory resolution), core.publish (for publish context).
**Consumed by:** Hub routers, DCC bridges, features.
**Parallel modules:** backend/core (lower-level services).

## 5. Module Entry Points
- **From routers:** Import `user_utils.get_current_user()` to fetch active user context.
- **From DCC bridges:** Import `project_utils` to resolve project paths for export/import operations.
- **From features:** Import `token_utils` to format/parse publish tokens.

## 6. Per-File Detail

### `user_utils.py`
**Role:** Manage current user context and user-related filesystem operations.
#### `get_current_user()`
Return name of currently active user (from memory or config). Fallback to default if not set.
→ used by: routers, DCC bridges, features

#### `set_current_user(name)`
Set active user in memory, config file, and create user directory (FLUX_ROOT/USER/name/) if needed.
→ used by: routers (user selection/login endpoints)

#### `list_users()`
Scan FLUX_ROOT/USER/ directory and return list of existing user directories.
→ used by: routers (user listing endpoints)

#### `user_exists(name)`
Check if user directory exists in FLUX_ROOT/USER/.
→ used by: routers (user validation)

#### `create_user_dir(name)`
Create user directory (FLUX_ROOT/USER/name/) and initialize default structure.
→ used by: set_current_user, routers (user creation endpoints)

### `project_utils.py`
**Role:** Simplify project path operations and listing.
**Functions:** Project-level wrappers over paths module (exact exports depend on project structure). Common patterns: `get_project_path(project_name)`, `list_projects()`, `project_exists()`, `get_project_assets()`.
→ used by: routers, DCC bridges, features

### `token_utils.py`
**Role:** Token formatting, parsing, and manipulation for publish workflows.
**Functions:** Token helpers (exact exports depend on token format). Common patterns: `format_token()`, `parse_token()`, `validate_token()`, `generate_token()`.
→ used by: folder_manager, publish features, DCC bridges

## 7. Maintenance Notes
These utilities are thin wrappers; keep logic minimal and defer to config/paths modules. If a function grows beyond 5-10 lines, consider moving core logic to the underlying module. user_utils and project_utils must maintain consistency with FLUX_ROOT directory structure (defined in paths). token_utils should be stateless (pure functions) to support concurrent usage from multiple routers.
