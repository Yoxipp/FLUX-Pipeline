# CONTEXT — Components

> Domain: frontend
> Path: app/src/components/
> Last updated: 2026-05-13
> Key internal dependencies: types.ts, api/client.ts, hooks/

## 1. Module Role
Reusable UI components for FLUX app shell: window frame (TitleBar, StatusBar), navigation (Sidebar), DCC launcher controls, software selector, and primitive UI atoms (Avatar, Pill, Button, etc.).

## 2. When to Read This Module
When building new pages or modifying the app layout. Shared components ensure consistent styling and behavior across Publisher, Importer, and Activity pages. Reference here to reuse instead of duplicating UI patterns.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| shared/TitleBar.tsx | Component | Frameless window title bar (42px height). Displays FLUX logo, app title, notification bell, settings gear, user pill, and macOS-style traffic light controls (minimize/maximize/close). | `TitleBar(props)` with `username`, `unreadCount`, `onSettings`, `onUserChange` |
| shared/Sidebar.tsx | Component | Left navigation sidebar showing Home/Publisher/Importer/Activity items with notification badges, DCC launcher section per software, connection status dots, and path picker. | `Sidebar(props)` with `dccStatus`, `unreadCount` |
| shared/StatusBar.tsx | Component | Bottom status bar (24px height) showing connected DCC names with colored indicator dots and version number. | `StatusBar(props)` with `dccStatus` |
| shared/SoftwareSelector.tsx | Component | DCC selection dropdown pills (Maya, Houdini, Nuke, etc.). Used in Publisher and Importer pages to switch active software context. | `SoftwareSelector(props)` with `active`, `onChange` callback |
| shared/ui.tsx | Library | Primitive UI atoms: Avatar, Cap, SecTitle, Pill, Btn, Field, Tag, Toggle, Check, FolderIcon. All use CSS variable tokens (--accent, --ink-*, --rule, etc.). | 9 named exports (Avatar, Cap, SecTitle, Pill, Btn, Field, Tag, Toggle, Check, FolderIcon) |
| DccStatus/DccPill.tsx | Component | Individual DCC connection status indicator. Shows colored dot and DCC name. Used inside StatusBar or as a reusable status widget. | `DccPill(props)` with `name`, `status: DccStatusEntry` |

## 4. Useful Relations
- **TitleBar** imports `Avatar` and `SettingsPopover` from ui.tsx; uses `window.electronAPI` for window controls and app version.
- **Sidebar** uses `NavItem` and `NavGroup` subcomponents; imports hook icons from lucide-react; calls `api.launchDcc()` for software launch.
- **StatusBar** mirrors DCC list in Sidebar; filters to show only connected DCCs; hardcoded version "v1.1".
- **SoftwareSelector** wraps `Pill` primitive from ui.tsx; used by Publisher and Importer pages as a shared control.
- **ui.tsx** library provides consistent styling foundation; all components use className + inline styles; no external CSS imports.
- **DccPill** receives `DccStatusEntry` type from types.ts; maps `connected` flag to color rendering.

## 5. Module Entry Points
Import into `App.tsx`:
```
import { TitleBar, Sidebar, StatusBar } from './shared'
import { DccPill } from './DccStatus'
```

Import primitives for new components:
```
import { Avatar, Pill, Btn, Field } from './shared/ui'
```

## 6. Per-File Detail
**TitleBar.tsx**
42px frameless header with flex layout. Manages `SettingsPopover` visibility state. Shows unread notification badge on bell icon. Settings popover fetches workspace path and app version on mount. Workspace folder icon clickable via `window.electronAPI.openFolder()`. Traffic light buttons (minimize/maximize/close) call `window.electronAPI.windowAction()`.

**Sidebar.tsx**
Vertical navigation with collapsible NavGroup sections. First section: Home/Publisher/Importer/Activity/Docs with route links and activity badge. DCC launcher section lists 8 supported software (Maya, Houdini, Nuke, Substance, ZBrush, Marvelous, Photoshop) with CONNECTION_DELAY and `api.launchDcc()`. Each DCC shows live connection dot from `dccStatus[key]`. Settings icon opens workspace picker; user icon triggers login modal.

**StatusBar.tsx**
24px bottom bar showing only connected DCCs (filtered from `dccStatus`). Uses hardcoded `STATUS_ITEMS` list (not synced with Sidebar list). Dot color driven by `entry.connected` boolean. Dividers between items. Right-aligned version badge "v1.1".

**SoftwareSelector.tsx**
Horizontal pill selector for 7 DCCs. Props control active selection and `onChange` callback for parent page. Uses `Pill` primitive with `active` class for styling. No state management (controlled component pattern).

**ui.tsx**
9 pure presentational primitives with TypeScript interfaces. Avatar renders single letter in colored circle. Pill/Btn/Field have `active`/`disabled` variants. Toggle and Check are stateless UI representations (controlled by parent). All use CSS variables for theming (--accent, --ink-*, --rule, --paper, --bg-deep). FolderIcon is custom SVG.

**DccPill.tsx**
Small inline DccPill component (not a full bar). Maps `status.connected` to color; shows gray (#9a9a9a) if offline. Renders as flex row with indicator dot and name. Could be refactored to use `Pill` primitive from ui.tsx for consistency.

## 7. Maintenance Notes
- StatusBar has hardcoded DCC list (STATUS_ITEMS) that differs from Sidebar SOFTWARE list; keep in sync manually or unify source.
- TitleBar and Sidebar both call `api.getSettings()` independently; consider lifting to App.tsx to fetch once.
- DccPill uses inline color instead of CSS class; consider updating to match ui.tsx pattern for consistency.
- Sidebar CONNECTION_DELAY is hardcoded; extract to config if DCC launch timing varies by software.
- All components assume 8765 WebSocket/HTTP backend; no environment variable config; update if port changes.
