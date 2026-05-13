# CONTEXT — Build Configuration

> Domain: (build configuration, not imported by code)  
> Path: scripts/  
> Last updated: 2026-05-13  
> Key internal dependencies: (none; external tools only)

## 1. Module Role
Build configuration and packaging assets. Contains PyInstaller spec file for backend bundling, Electron builder config for Windows .msi packaging, and the FLUX application icon. Not imported by Python or TypeScript code; used by external build tools.

## 2. When to Read This Module
- Setting up or modifying the PyInstaller backend build (hidden imports, entry point, output dir)
- Configuring electron-builder for Windows .msi generation (code signing, installer options)
- Adding or changing the app icon
- Debugging build failures in CI/CD or local builds
- Understanding the final packaging layout

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| backend.spec | PyInstaller spec | Bundles backend/main.py into flux_backend.exe. Configured as --onedir with uvicorn and FastAPI hidden imports. Output: dist/flux_backend/. | (build artifact) |
| electron-builder.yml | YAML config | Electron builder configuration for Windows x64 .msi. Includes PyInstaller output as extraResources, requestedExecutionLevel asInvoker (no admin). | (build artifact) |
| icon.ico | image | FLUX application icon (ICO format). Used by electron-builder for .exe and .msi branding. | (build artifact) |

## 4. Useful Relations
backend.spec references backend/main.py as the entry point. electron-builder.yml includes dist/flux_backend/ (PyInstaller output) as extraResources, ensuring the backend executable is bundled with the Electron app. icon.ico is embedded in the final .msi by electron-builder.

## 5. Module Entry Points
None. External build tools (PyInstaller, electron-builder) read these configs directly; no code imports.

## 6. Per-File Detail

### `backend.spec`
**Role:** PyInstaller specification file. Defines backend bundling: entry point (backend/main.py), mode (--onedir), hidden imports (uvicorn, fastapi, pydantic, etc.), and output directory (dist/flux_backend/). Run via: `pyinstaller scripts/backend.spec`.

### `electron-builder.yml`
**Role:** Electron builder configuration. Targets Windows x64 platform, generates .msi installer. Includes PyInstaller output (dist/flux_backend/) as extraResources so the backend exe is packaged with the app. requestedExecutionLevel: asInvoker (no admin rights required).

### `icon.ico`
**Role:** FLUX application icon in ICO format. Referenced by electron-builder.yml for .exe and .msi icon branding.

## 7. Maintenance Notes
- **backend.spec**: Update hidden imports if backend/main.py adds new dependencies (numpy, scipy, custom packages). Keep entry point aligned with actual main module.
- **electron-builder.yml**: Ensure extraResources path (dist/flux_backend/) matches PyInstaller output location. Update if output dir changes.
- **icon.ico**: Replace if app icon design changes. Ensure file is in ICO format and at least 256x256 px for clarity at all scales.
- **Build Order**: PyInstaller must run before electron-builder so that dist/flux_backend/ is populated.
- **Platform**: Currently configured for Windows x64 only. Add entries for macOS/Linux if needed.
- **Signing**: No code signing configured; add certificateFile if required for distribution.
