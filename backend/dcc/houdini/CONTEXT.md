# CONTEXT — Houdini DCC Integration

> Domain: backend / DCC integration
> Path: backend/dcc/houdini/
> Last updated: 2026-05-15
> Key internal dependencies: core.constants (HOUDINI_HTTP_PORT via DCC_PORTS), routers/dcc.py (consumer)

## 1. Module Role

Provides HTTP client and autostart management for Houdini DCC integration. The module encapsulates two concerns:
- **Client side** (backend FLUX) : synchronous HTTP client that communicates with a server running inside Houdini
- **Autostart management** : installs and removes FLUX bootstrap code in Houdini's startup script (123.py) without requiring Houdini to be open

The Houdini server (`flux_houdini_server.py`) runs inside Houdini on port 48884, exposing endpoints for code execution, state queries, and event streaming. The client and autostart utilities operate independently of Houdini's process, allowing backend FLUX to manage the DCC lifecycle and communication.

## 2. When to Read This Module

- **Integrating new DCC (Maya, Nuke, etc.)** : Use this module as a reference pattern — replicate client.py + autostart.py structure
- **Adding commands to Houdini execution** : Read client.py to understand available methods and SSE subscription pattern
- **Debugging autostart failures** : Read autostart.py to understand prefs dir detection, startup file location, and idempotent marker logic
- **Extending HTTP server endpoints** : Read flux_houdini_server.py and client.py in parallel to add new request/response pairs
- **Handling DCC lifecycle from routers** : Read routers/dcc.py alongside this module to see how autostart and client are invoked

## 3. Files Present

| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `__init__.py` | module | Package entry point, exports singleton and autostart module | `HoudiniClient`, `houdini_client`, `autostart` |
| `flux_houdini_server.py` | script | HTTP server that runs inside Houdini; deployed to AppData on install | `start(port)`, `stop()` |
| `client.py` | module | Synchronous HTTP client for backend FLUX → Houdini server | `HoudiniClient`, `houdini_client`, `HOUDINI_HTTP_PORT` |
| `autostart.py` | module | Installs/removes FLUX bootstrap block in Houdini's 123.py | `get_prefs_dir`, `get_startup_file`, `is_installed`, `install`, `uninstall` |
| `startup/__init__.py` | module | Reserved for future Houdini startup hooks | (empty stub) |

## 4. Useful Relations

**Consumed by** : `routers/dcc.py` — endpoints `GET/POST/DELETE /{dcc_key}/autostart` et `GET /{dcc_key}/ping`

**Déployé vers** : `%APPDATA%/FLUX/dcc/houdini/flux_houdini_server.py` (copié par `autostart.install()`)

**Modifie** : `%USERPROFILE%/Documents/houdiniX.Y/scripts/123.py` (bloc autostart délimité par marqueurs)

**Référence de pattern** : Ce module définit le template pour les futures intégrations DCC — client, autostart, serveur in-process

## 5. Module Entry Points

- **Depuis routers/dcc.py** :
  - `from dcc.houdini import autostart` — gérer le script de démarrage
  - `from dcc.houdini.client import houdini_client` — exécuter du code et interroger l'état

- **Depuis Houdini (123.py)** :
  - `import flux_houdini_server` → appelle automatiquement `start()` à l'import

- **Pour publisher/importer futurs** :
  - `houdini_client.run(code_str)` — exécuter du Python dans le main thread de Houdini
  - `houdini_client.subscribe(callback)` — écouter les événements SSE de Houdini

## 6. Per-File Detail

### `__init__.py`
**Role:** Namespace du package ; exporte le singleton client et le module autostart pour consommation par routers/dcc.py.

### `flux_houdini_server.py`
**Role:** Serveur HTTP tournant dans l'interpréteur Python de Houdini. Déployé dans `%APPDATA%/FLUX/dcc/houdini/` et importé par 123.py au démarrage de Houdini. Expose des endpoints REST et SSE pour que le backend FLUX interroge l'état, exécute du code, et reçoive des événements en temps réel.

Exécute le code soumis sur le main thread de Houdini via `hou.ui.addEventLoopCallback`. Affiche un `hou.ui.setStatusMessage` à l'activation.

**Exports publics :** `start(port)`, `stop()` — endpoints : `/ping`, `/state`, `/run`, `/events`

### `client.py`
**Role:** Client HTTP synchrone (stdlib urllib) côté backend FLUX. Communique avec `flux_houdini_server` sans dépendance Houdini ; importable dans tout environnement Python.

**Exports publics :**
- `HoudiniClient(host, port)` — méthodes : `ping()`, `is_connected()`, `state()`, `run(code)`, `selected_nodes()`, `get_parm(path, name)`, `set_parm(path, name, value)`, `subscribe(callback)`
- `houdini_client` — singleton par défaut (localhost:48884)
- `HOUDINI_HTTP_PORT` — constante port (48884)

### `autostart.py`
**Role:** Gère l'installation et la suppression du bloc FLUX dans 123.py sans Houdini ouvert. Détecte le dossier prefs, déploie le script serveur dans AppData, et insère un bloc délimité par marqueurs (idempotent).

Ordre de détection du dossier prefs : `HOUDINI_USER_PREF_DIR` env var → version extraite du chemin exe → scan `Documents/houdiniX.Y`.

**Exports publics :** `get_prefs_dir(exe_path)`, `get_startup_file(exe_path)`, `is_installed(exe_path)`, `install(exe_path)`, `uninstall(exe_path)` — toutes retournent `{"success": bool, "message": str, ...}`

### `startup/__init__.py`
**Role:** Stub vide, réservé pour de futurs hooks de démarrage Houdini spécifiques.

## 7. Maintenance Notes

- **Déploiement serveur** : `flux_houdini_server.py` est recopié dans AppData à chaque `autostart.install()` — la version en production est toujours à jour après installation.
- **Port** : 48884 défini dans `core.constants.DCC_PORTS["Houdini"]` — utilisé pour le probe TCP du WebSocket de statut et par le client HTTP.
- **Idempotence** : Les marqueurs `# >>> FLUX autostart` / `# <<< FLUX autostart` garantissent qu'un double appel à `install()` n'insère pas de doublon.
- **Ajout d'un nouveau DCC** : Répliquer client.py + autostart.py, enregistrer dans `_AUTOSTART_MODULES` de routers/dcc.py, ajouter le port dans constants.DCC_PORTS.
