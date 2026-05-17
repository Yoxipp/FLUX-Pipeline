# CONTEXT — Shared Components

> Domain: frontend  
> Path: app/src/components/shared/  
> Last updated: 2026-05-14  
> Key internal dependencies: react, lucide-react, api.client, types

## 1. Module Role
Persistent chrome and UI primitives for the FLUX app. TitleBar, Sidebar, and StatusBar form the application shell visible on every page. SoftwareSelector provides DCC filtering. ui.tsx exports reusable atoms (Avatar, Button, Field, Pill, etc.).

## 2. When to Read This Module
- Adding or refactoring app navigation and chrome
- Building new pages that use shared components
- Extending the DCC launcher, window controls, or status display
- Creating custom UI elements that reuse Pill, Button, Field patterns

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| TitleBar.tsx | component | Frameless window title bar, 42px height. Logo, app title, notification bell, settings gear with popover, user pill, traffic-light window controls. | `TitleBar` component (props: `username`, `unreadCount`, `onSettings`, `onUserChange`) |
| Sidebar.tsx | component | Left navigation, 200px wide. NavGroups: ASSETS (Publisher, Importer, USD), PIPELINE (Shelf Manager, Folder Manager, Activity), LAUNCHER (8 DCCs with connection dots, auto-find, path picker, launch buttons). | `Sidebar` component (props: `dccStatus`, `unreadCount`) |
| StatusBar.tsx | component | Bottom status bar, 24px height. Shows connected DCC names with color-coded dots. Filters to display only DCCs with status entries. | `StatusBar` component (props: `dccStatus`) |
| SoftwareSelector.tsx | component | DCC software dropdown selector (7 software options). Used by Publisher and Importer pages to pick the target DCC. | `SoftwareSelector` component (props: `active`, `onChange`) |
| ui.tsx | module | Primitive UI atoms: Avatar, Cap, SecTitle, Pill, Btn, Field, Tag, Toggle, Check, FolderIcon, Tooltip/TooltipTrigger/TooltipContent. All inline styled, no CSS dependencies. | `Avatar`, `Cap`, `SecTitle`, `Pill`, `Btn`, `Field`, `Tag`, `Toggle`, `Check`, `FolderIcon`, `Tooltip`, `TooltipTrigger`, `TooltipContent` |

## 4. Useful Relations
TitleBar uses Avatar from ui.tsx. Sidebar and StatusBar both consume `DccStatusMap` type from types module. All components use api.client for settings and DCC control (launch, find exe, update paths). SoftwareSelector uses Pill atom.

## 5. Module Entry Points
- **Sidebar**: Imported by app layout; handles navigation and DCC launcher state.
- **TitleBar**: Imported by app layout; handles window controls and settings popover.
- **StatusBar**: Imported by app layout; displays live DCC connection status.
- **SoftwareSelector**: Imported by Publisher and Importer pages.
- **ui.tsx**: Imported directly by consumers for Avatar, Pill, Button, etc.

## 6. Per-File Detail

### `TitleBar.tsx`
**Role:** Frameless window chrome. Exports TitleBar component with window minimize/maximize/close controls (via window.electronAPI), app logo, notification badge, settings gear with inline popover, and user pill trigger. SettingsPopover (internal sub-component) includes a "Changer de répertoire…" button in the WORKSPACE section that triggers handleChangeWorkspace to open a native directory picker, update app settings, and reload.

### `Sidebar.tsx`
**Role:** Primary navigation and DCC launcher. Manages local state for launching DCCs, auto-finding paths, and picking paths via file dialog. Calls api.launchDcc, api.findDccExe, api.updateSettings, and api.getSettings on mount.

### `StatusBar.tsx`
**Role:** Live DCC connection display. Shows only connected or in-warning DCCs from dccStatus. Uses dot color class (ok/warn) to indicate status.

### `SoftwareSelector.tsx`
**Role:** Horizontal pill selector for DCC choice. Maps over SW array (7 items). Calls onChange callback when user selects a software.

### `ui.tsx`
**Role:** Reusable UI atoms. Avatar renders a circular badge with a letter and accent color. All atoms use inline CSS. No external CSS or className-based styling needed. Tooltip/TooltipTrigger/TooltipContent wrap `@radix-ui/react-tooltip` with the project's dark design system (animated, bordered arrow) — use these instead of native `title=` attributes.

## 7. Maintenance Notes
- **Window Controls**: TitleBar traffic-light buttons call window.electronAPI methods; ensure Electron preload exposes windowMinimize, windowMaximize, windowClose.
- **DCC Status**: Both Sidebar and StatusBar consume the same DccStatusMap; keep key names consistent (e.g., 'maya', 'houdini', 'nuke', etc.).
- **Settings Popover**: Located inline in TitleBar, positioned absolutely; ensure it doesn't overflow on small windows. Includes workspace change feature with RefreshCw animation during directory picker and settings update.
- **Sidebar DCC Launcher**: Software list (SOFTWARE const) must match backend DCC_PORTS keys exactly; mismatch breaks launch/find/status.
- **Avatar Usage**: Two instances in TitleBar (in settings popover and user pill); both use first character of username, uppercased.
- **StatusBar Filtering**: Only displays items with a dot (entry in dccStatus); remove entry keys to hide DCC from status bar.
