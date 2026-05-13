# CONTEXT — Houdini DCC Bridge

> Domain: backend  
> Path: backend/dcc/houdini/  
> Last updated: 2026-05-13  
> Key internal dependencies: (none yet; planned integration with hou module)

## 1. Module Role
Houdini DCC bridge stub. Provides a placeholder directory structure for Houdini commandPort integration, export commands, and startup hooks. The actual Houdini integration is not yet implemented; framework planned in TODO/09_dcc_houdini.md.

## 2. When to Read This Module
- Planning Houdini commandPort listener implementation
- Adding Houdini export command handlers (geometry, cache, USD export)
- Integrating Houdini startup hooks for shelf install or auto-connect
- Understanding the stub structure reserved for future Houdini work

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| __init__.py | module | Empty stub. No exports yet. Integration planned. | (none) |
| startup/__init__.py | module | Empty startup hook placeholder for Houdini initialization. | (none) |

## 4. Useful Relations
Houdini shelf file (Flux.shelf) stored in backend/resources/shelves/houdini/. Once implemented, this module will coordinate with backend/main.py's DCC registry and socket listeners. Maya and Nuke bridges (backend/dcc/maya/, backend/dcc/nuke/) are reference implementations for the planned Houdini structure.

## 5. Module Entry Points
Currently none. Once implemented, expected entry point: a Houdini startup script or command that imports this module's initialization code.

## 6. Per-File Detail

### `__init__.py`
**Role:** Empty stub. No current implementation. Will eventually house Houdini commandPort listener setup and export command routing.

### `startup/__init__.py`
**Role:** Empty startup hook placeholder. Will be invoked by Houdini's startup scripts to initialize FLUX integration (shelf register, socket connect, listener setup).

## 7. Maintenance Notes
- **Status**: Stub only. No functional Houdini integration yet.
- **Shelf File**: Flux.shelf is pre-created in backend/resources/shelves/houdini/ but not yet integrated.
- **Implementation Plan**: See TODO/09_dcc_houdini.md for design and priority.
- **Reference**: Use Maya (backend/dcc/maya/) and Nuke (backend/dcc/nuke/) as templates for commandPort and export handlers.
- **Next Steps**: Implement commandPort listener, export command handlers (geometry, USD), and startup hook registration.
