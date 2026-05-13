# CONTEXT — Pages

> Domain: frontend
> Path: app/src/pages/
> Last updated: 2026-05-14
> Key internal dependencies: useActivity hook, api module (publish, browseImport, importFiles, getActivity, getShelves, installShelf, removeShelf, listUsers, updateSettings, initFirstLaunch), electronAPI.openFolder

## 1. Module Role
Home for all top-level page components in FLUX. Each page is a route handler for a feature (publishing, importing, activity feed, project management, shelf management, onboarding, user login).

## 2. When to Read This Module
When navigating the FLUX application structure, understanding how pages integrate with backend APIs, adding a new page route, or reviewing how pages pass data to child components.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| Hub.tsx | .tsx | Home page with activity feed and team chat | Hub (named export) |
| Publisher.tsx | .tsx | DCC publish interface with history | Publisher (named export) |
| Importer.tsx | .tsx | File import with browser and history | Importer (named export) |
| Activity.tsx | .tsx | Filterable activity feed with mark-as-read | Activity (named export) |
| Projects.tsx | .tsx | Project/folder manager with asset/seq/shot creators | Projects (named export) |
| ShelfManager.tsx | .tsx | DCC shelf install/remove interface | ShelfManager (named export) |
| FirstLaunch.tsx | .tsx | Multi-step onboarding with workspace path and username selection (avatar list + text input) | FirstLaunch (named export) |
| Login.tsx | .tsx | Compact user switch popover (below TitleBar, right-aligned) | Login (named export) |

## 4. Useful Relations
- Hub: consumes ActivityFeed, ChatBox, QuickShortcuts components; reads useActivity hook
- Publisher/Importer: call api.publish and api.importFiles; display file history panels
- Activity: extends Hub's feed with filtering; pairs with ChatPanel
- Projects: folder tree and asset creators; depends on folder manager API
- ShelfManager: reads DCC list from api.getShelves(); toggles install/remove
- FirstLaunch: first-run only; workspace path via electronAPI; username from api.listUsers()
- Login: user popover; calls api.updateSettings(); triggers reload on switch

## 5. Module Entry Points
- Hub → default home view on app load
- Publisher → click "Publish" in main nav
- Importer → click "Import" in main nav
- Activity → click "Activity" in main nav
- Projects → click "Projects" in main nav
- ShelfManager → click "Shelf Manager" in main nav
- FirstLaunch → on first launch (workspace + user setup)
- Login → user avatar click or user switch popover

## 6. Per-File Detail

### `Hub.tsx`
**Role:** Home page combining activity feed, team chat, and quick shortcuts for fast navigation.
#### Hub
Shows recent pipeline events + team chat in unified view. Props: none (reads context). useActivity hook provides event data.
→ used by: main router / app root

### `Publisher.tsx`
**Role:** Page for publishing assets to pipeline from a DCC (Maya, Houdini, etc).
#### Publisher
Renders SoftwareSelector, file path input, project selector. Calls api.publish(payload). Displays publish history file list.
→ used by: main router / publish route

### `Importer.tsx`
**Role:** Page for importing assets/sequences into active DCC from project folders.
#### Importer
File browser via api.browseImport. File selection UI. Calls api.importFiles. Shows import history panel.
→ used by: main router / import route

### `Activity.tsx`
**Role:** Full-page activity feed with filtering and mark-as-read actions.
#### Activity
Filterable event list from api.getActivity. ChatPanel section. Mark-as-read controls.
→ used by: main router / activity route

### `Projects.tsx`
**Role:** Project and asset management interface. Create/edit folders, assets, sequences, shots.
#### Projects
Folder tree view with create actions. Asset creator by CLASS token. Sequence/shot creator. Calls folder manager APIs.
→ used by: main router / projects route

### `ShelfManager.tsx`
**Role:** DCC plugin/shelf installation and removal interface.
#### ShelfManager
DCC selector (Maya, Houdini). Version list from api.getShelves(). Install/remove buttons via api.installShelf / removeShelf.
→ used by: main router / shelf-manager route

### `FirstLaunch.tsx`
**Role:** Multi-step onboarding wizard for initial FLUX setup.
#### FirstLaunch
Step 1: workspace path (electronAPI.openFolder with FolderOpen icon on browse button). Step 2: existing users displayed as clickable avatar list + text input for new username simultaneously (no mode toggle). Uses new design system (CSS variables: var(--paper), var(--ink), var(--accent-*)) with inline styles matching Login.tsx. Calls api.initFirstLaunch on complete.
→ used by: main router / shown once on first launch

### `Login.tsx`
**Role:** Compact user switch popover positioned below TitleBar.
#### Login
Redesigned from full-screen overlay to popover at top: 48px, right: 10px (aligned with user pill). Width: 280px. Combined view: existing user list (max-height 160px, scrollable) + "Nouvel artiste" text input always visible (no mode toggle). Transparent backdrop div closes on click. Uses new design system (CSS variables: var(--paper), var(--ink), var(--accent-*)) with inline styles. Calls api.updateSettings({username}). Triggers app reload on selection.
→ used by: user avatar click or manual switch overlay

## 7. Maintenance Notes
- All pages are named .tsx and use TypeScript. Keep API calls consistent with shared api module.
- FirstLaunch and Login interact with Electron IPC via window.electronAPI; ensure electronAPI contract is stable.
- FirstLaunch and Login use new design system (CSS variables) — maintain consistency with var(--paper), var(--ink), var(--accent-*) tokens.
- Pages rely on context/hooks (useActivity, etc) — verify hooks are exported from their modules.
- Each page should handle loading/error states for API calls; no assumed fast responses.
