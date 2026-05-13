# CONTEXT — Activity Management

> Domain: backend
> Path: backend/features/activity/
> Last updated: 2026-05-13
> Key internal dependencies: core.json_manager, core.paths, core.logger

## 1. Module Role

Manages centralized event logging and team chat for the FLUX pipeline. Tracks user actions (publish, import, connect) in activite.json and team messages in teamChat.json. Provides read/write access with optional filtering and status tracking.

## 2. When to Read This Module

When implementing user activity feeds, logging publish/import operations, sending team messages, marking notifications as read, or tracking DCC connection history.

## 3. Files Present

| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `activity_reader.py` | module | Query and status-read for activite.json | `get_all_events(limit, user?, action?, project?, path?)`, `get_unread_events(path?)`, `get_unread_count(path?)`, `mark_as_read(event_id, path?)`, `mark_all_as_read(path?)` |
| `activity_writer.py` | module | Append new events to activite.json | `log_event(user, action, project, filename?, path?)`, `log_publish(user, filename, project)`, `log_import(user, filename, project)`, `log_connect(user, dcc_name)` |
| `chat_manager.py` | module | Read/write teamChat.json and manage messages | `send_message(user, message, path?)`, `get_messages(limit?, path?)`, `get_user_list()`, `parse_pings(message)` |

## 4. Useful Relations

- **Consumed by**: WebSocket endpoints (activity feed, chat), DCC bridge (log_connect, log_publish), importer/publisher (activity logging)
- **Reads**: FLUX_ROOT/CONFIG/activite.json, FLUX_ROOT/CONFIG/teamChat.json
- **Writes**: activite.json (append mode), teamChat.json (append mode)
- **Depends on**: core.paths (get_activity_path, get_chat_path, get_users_dir), core.json_manager (read/write JSON)

## 5. Module Entry Points

1. **For published/imported files**: Call `log_publish()` or `log_import()` after successful file operations.
2. **For DCC connections**: Call `log_connect()` when a DCC establishes a socket connection.
3. **For activity feed**: Call `get_all_events(limit=50, user?, action?, project?)` sorted newest-first.
4. **For unread notifications**: Call `get_unread_count()` or `mark_as_read(event_id)` for UI updates.
5. **For team chat**: Call `send_message(user, message)` to append; `get_messages(limit)` to fetch; `parse_pings()` for @mentions.

## 6. Per-File Detail

### `activity_reader.py`

**Role:** Query-only access to activite.json. Filters by user/action/project, sorts by date+time, tracks read status.

#### `get_all_events(limit=50, user?, action?, project?, path?)`
Return up to *limit* events sorted newest-first with optional filters applied.
→ used by: activity feed endpoints, notification widgets

#### `get_unread_events(path?)`
Return all events where read=False in chronological order.
→ used by: notification counter, unread filter UI

#### `get_unread_count(path?)`
Return the count of unread events (shorthand for len(get_unread_events)).
→ used by: badge display, notification service

#### `mark_as_read(event_id, path?)`
Set read=True for event with matching id. Returns bool on success.
→ used by: click handlers on individual notifications

#### `mark_all_as_read(path?)`
Set read=True for all events. Returns bool on success.
→ used by: "mark all as read" button, bulk clearing

### `activity_writer.py`

**Role:** Append-only logging for user actions. Generates unique IDs and timestamps.

#### `log_event(user, action, project, filename?, path?)`
Append a single event entry. Returns True on success. Action types: "publish", "import", "connect", "update", "error".
→ used by: all action handlers (publish_core, import_core, launcher_core)

#### `log_publish(user, filename, project)`
Shorthand: log_event(user, "publish", project, filename).
→ used by: publisher module after successful file publish

#### `log_import(user, filename, project)`
Shorthand: log_event(user, "import", project, filename).
→ used by: importer module after successful DCC import

#### `log_connect(user, dcc_name)`
Shorthand: log_event(user, "connect", dcc_name). DCC name replaces project.
→ used by: connection_monitor after socket establishes

### `chat_manager.py`

**Role:** Team messaging with @mention parsing. Reads user list from USER/ directory.

#### `send_message(user, message, path?)`
Append a chat message entry. Returns True on success.
→ used by: chat input handler in WebSocket endpoint

#### `get_messages(limit=100, path?)`
Return up to *limit* messages in chronological order (oldest first).
→ used by: chat feed rendering (reverse in UI to show newest bottom)

#### `get_user_list()`
Return sorted user names from FLUX_ROOT/USER/ directory (no path param).
→ used by: @mention autocomplete dropdown

#### `parse_pings(message)`
Extract all @name mentions from message text. Returns list of user names.
→ used by: notification system, mention highlighting

## 7. Maintenance Notes

- **Timestamps**: Generated via `datetime.now()` as ISO strings (YYYY-MM-DD HH:MM).
- **Event IDs**: YYYYMMDDTHHmmss_{user}_{uuid_hex[:6]} ensures uniqueness without database.
- **JSON schema changes**: tokens.json has versions; activity.json does not — add fallback loading if new fields are required.
- **User directory**: get_user_list() lists directories under FLUX_ROOT/USER/; ensure this is populated when users are created.
- **OnDrive/network paths**: activity.json is user-specific in CONFIG; ensure proper path resolution on networked drives.
