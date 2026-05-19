# CONTEXT — DCC Bridge

> Domain: backend
> Path: backend/dcc/
> Last updated: 2026-05-13
> Key internal dependencies: core.publish, config

## 1. Module Role
Bridge layer between DCCs (Digital Content Creation tools) and the FLUX Hub backend. Provides DCC-specific connection management, command execution, and publish workflows. Isolates DCC-agnostic pipeline logic from tool-specific APIs.

## 2. When to Read This Module
When implementing a new DCC integration, debugging connection issues between a DCC and the Hub, or modifying publish/export/import workflows for DCCs.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `maya/` | submodule | Full Maya integration (connection, export, import, publish, shelf). | — |
| `houdini/` | submodule | Houdini startup stub (connection only, ready for expansion). | — |

## 4. Useful Relations
**Depends on:** core.publish (for publish orchestration), config (for settings), paths (for file paths).
**Consumed by:** Hub backend routers, DCC startup scripts, Maya shelf shelf button.
**Parallel modules:** backend/core (publish/export orchestration).

## 5. Module Entry Points
- **From Hub:** Import `maya.maya_connection.execute_command()` to send commands to a running Maya instance.
- **From DCC (Maya):** `maya.startup.flux_bridge` auto-runs on Maya startup; calls `maya_connection.start_server()`.
- **From Maya UI:** Shelf button calls `maya_connection.open_hub()` to launch the Hub in Maya's workspace.

## 6. Per-File Detail
No top-level Python files in backend/dcc/; all logic is in submodules (maya/, houdini/).

## 7. Maintenance Notes
Each DCC submodule follows a consistent pattern: connection management, command builders (export/import), publish entry point, and startup/shelf UI. When adding a new DCC, replicate this structure. The dual-context design (inside DCC + from Hub) is central; ensure both code paths are tested.
