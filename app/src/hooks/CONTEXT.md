# CONTEXT — Hooks

> Domain: frontend
> Path: app/src/hooks/
> Last updated: 2026-05-13
> Key internal dependencies: types.ts, api/client.ts

## 1. Module Role
Three custom React hooks that manage real-time data streams for the FLUX app: DCC connection state via WebSocket, user activity feed via polling, and application settings bootstrap on startup.

## 2. When to Read This Module
When modifying status subscriptions in App.tsx, updating notification logic, or changing DCC connection behavior. Review here before adding new hooks for cross-cutting state patterns.

## 3. Files Present
| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| useDccStatus.ts | Hook | WebSocket subscriber to DCC connection state. Auto-reconnects every 3s on close/error. | `useDccStatus()` → `DccStatusMap` |
| useActivity.ts | Hook | Polling subscriber to activity feed. Polls `/activity` every 10s with event history and unread count. | `useActivity(limit?)` → `{ events, unreadCount, refresh, markAllRead }` |
| useSettings.ts | Hook | One-shot loader of user settings from `/settings` on mount. Caches result with loading/error states. | `useSettings()` → `{ settings, loading, error, setSettings }` |

## 4. Useful Relations
- **useDccStatus** feeds `DccStatusMap` to `Sidebar.tsx` and `StatusBar.tsx` for live connection dots.
- **useActivity** returns `unreadCount` badge to `App.tsx`, which passes to `TitleBar.tsx` and `Sidebar.tsx` for notification indicators.
- **useSettings** runs in `App.tsx` to load workspace/username on startup; result gates routing (first-launch setup vs. main shell).
- All three depend on `types.ts` for TypeScript interfaces and `api/client.ts` for backend communication.

## 5. Module Entry Points
Import and call in `App.tsx` at the component level:
```
const dccStatus = useDccStatus()
const { events, unreadCount } = useActivity()
const { settings, loading } = useSettings()
```

## 6. Per-File Detail
**useDccStatus.ts**
Establishes WebSocket to `ws://127.0.0.1:8765/dcc/ws/status`, parsing JSON messages into `DccStatusMap`. Uses internal `connect()` function with lifecycle teardown (close socket, clear timers on unmount). Returns empty object if WebSocket unavailable.

**useActivity.ts**
Fetches `/activity` on mount and every 10s via `setInterval`. Returns `{ events, unreadCount, refresh, markAllRead }`. Wraps `refresh()` in `useCallback` to avoid stale-closure issues in dependent components. Silent error handling (backend downtime keeps existing state).

**useSettings.ts**
Single async `api.getSettings()` call on mount via `useEffect`. Manages `loading` and `error` states. Returns full `Settings` object or `null` during load. Used by `App.tsx` to decide if first-launch wizard should run.

## 7. Maintenance Notes
- WebSocket reconnect delay (3s) is hardcoded; make configurable if DCC startup is slower in production.
- Activity polling interval (10s) trades freshness for backend load; adjust based on UI responsiveness requirements.
- `useSettings` does not refetch on manual trigger; cache invalidation requires page reload or explicit prop drilling of `setSettings`.
