# FLUX

Desktop 3D / VFX pipeline for ESMA student teams: project tree from naming tokens, immutable versioned publishes
(`vNNN` + `LAST`), one-click import into the DCCs, USD assembly (assets, sets, shots), production tracking,
render farm submission, node-based Flows, team activity, chat and calendar.

* Windows only, local-first (local folder, OneDrive or school server).
* Apache-2.0, permissive dependencies only, no DCC license token consumed by any step.
* DCCs: Maya, Houdini, ZBrush (validated); Nuke, Substance Painter / Designer, Mari, Marvelous, Photoshop (bridges).

This file is the entry point of the repository: what FLUX is, how to run it, where everything lives and what to read
for each kind of work.

## 1. Who reads what

| You are | Start with |
|---|---|
| Artist using FLUX | The manual `backend/resources/manual/FLUX_Manuel.html` (French). FLUX copies it into `<workspace>/FLUX_DOC/` at every start and shows it in Settings > Doc. Flows: Settings > Doc > Flows, source in `docs/user/flows/`. |
| TD / pipeline developer | Section 3 (quick start), then `docs/architecture/OVERVIEW.md` (systems), `docs/architecture/` (pipeline logic, USD), `docs/decisions/` (ADR). |
| Contributor | [CONTRIBUTING.md](CONTRIBUTING.md), `docs/development/BUILD.md`, `docs/development/STRUCTURE.md` (build-sensitive paths). |
| local tool session | [NOTES.md](NOTES.md): reading order, rules, risky zones. |

## 2. Architecture

```
app/electron (Electron main)  --spawn-->  backend/main.py  FastAPI on 127.0.0.1:8765 (per-launch X-Flux-Token)
app/src      (React + TS)     --HTTP-->   backend/routers  ->  features/*        domain logic
                                                           ->  flux_actions + flux_core   YAML action engine (publish)
                                                           ->  flux_flows        Flows engine (nodes, runs, pages)
                                                           ->  core/*            config, paths, metadata repository, storage
                                                           ->  dcc/<soft>        backend clients + in-DCC plugins
Metadata: MetadataRepository (JSON default | SQLite | remote)     Bytes: filesystem only, never through the API
```

Packaged app: the backend is frozen by PyInstaller (`scripts/backend.spec`) and shipped inside the Electron
installer (`scripts/electron-builder.yml`, NSIS). Details: `docs/development/BUILD.md`.

## 3. Quick start (dev)

Requirements: Windows, Node.js + npm, Python 3.13.

```bash
pip install -r backend/requirements.txt
npm install
npm run dev
```

Or double-click `INSTALL_DEV.bat` once, then `FLUX_DEV.bat`. Electron starts Vite and spawns the Python backend
(an already running backend on port 8765 is reused). Optional Rez launch: `package.py`, `docs/development/REZ.md`.

| Task | Command |
|---|---|
| Backend tests (from `backend/`) | `python tests/run_tests.py` (expects `verdict: PASS`) |
| One test suite (from `backend/`) | `python -m unittest discover -s tests/<suite> -t .` |
| Front-end logic tests | `npm run test:js` |
| Front-end types | `npx tsc --noEmit -p tsconfig.json` |
| Electron types | `npx tsc --noEmit -p tsconfig.electron.json` |
| Installer | `BUILD_INSTALLER.bat` or `npm run build`, output in `INSTALLEURS/` |

Never run a global `python -m unittest`: `usd-core` aborts at teardown on Windows, `run_tests.py` works around it.

## 4. Repository map

```
README.md  NOTES.md  CONTRIBUTING.md  LICENSE  NOTICE
package.py                         Rez package of FLUX
FLUX_DEV.bat  INSTALL_DEV.bat  BUILD_INSTALLER.bat
index.html  vite / tsconfig / tailwind / postcss configs  package.json   (tooling, must stay at the root)
app/
  electron/                        Electron main process: windows, sidecar launch, API token, updater
  src/                             React UI: pages/, components/shared/, api/client.ts, i18n.tsx
backend/
  main.py                          FastAPI entry (routers + token middleware)
  routers/                         HTTP layer
  features/                        domain: publisher, importer, production, render, usd_assembler, usd_export, ...
  core/                            config, paths, constants, metadata repository (JSON / SQLite / remote), storage
  flux_core/  flux_actions/        YAML action engine and its commands (publish, proxy, textures)
  flux_flows/                      Flows v2: model, engine, runs, scheduler, bridges, nodes, pages
  dcc/<soft>/                      per-DCC backend client + plugin copied into the DCC preferences
  resources/                       bundled assets: manuals, shelves, scene templates, rigs
  tests/                           run_tests.py + one suite per folder
scripts/                           build: build.cjs, backend.spec, electron-builder.yml, NSIS, HDA build, JS tests
tools/                             standalone scripts outside the app (loadtest/: server load test, cross_platform/: path audit)
public/                            static Vite assets
docs/                              documentation, index in docs/README.md
```

Every important code folder has a short `CONTEXT.md` (role and pitfalls). Full tree and the paths the build depends
on: `docs/development/STRUCTURE.md`.

## 5. Documentation map

| Folder | Content |
|---|---|
| `docs/architecture/` | Living system docs: pipeline logic, USD strategy and assembler, Houdini Work, school environment. |
| `docs/decisions/` | Architecture Decision Records. An accepted ADR is only changed by a new ADR. |
| `docs/development/` | Build, repository structure, Rez, publish rollback, bridge notes. |
| `docs/user/flows/` | User doc of the Flows editor (French); `03_INDEX_NODES.md` is bundled in the app. |
| `docs/history/` | What happened and what must not be redone (`HISTORY_ANALYSIS.md` section 4), dated audits. |
| `docs/notes/` | Living project memory: context, current state, next steps, issues backlog; `prompts/` = open work briefs. |
| `docs/archive/` | Read-only: finished studies and analyses (`studies/`), finished prompts (`prompts/`). Never a current spec. |

Anything removed before the 2026-11 cleanup is still readable at the git tag `archive/pre-cleanup`.

## 6. Runtime data (not in git)

FLUX works inside a workspace folder (`FLUX_ROOT`; in dev, the repository root) that holds `USER/` (per-user
settings), `DOSSIER_PROJETS/` (projects), `CONFIG/` (team config and extensions), `FLUX_UPDATE/` and `FLUX_DOC/`.
`config.json` is the machine config. All of these are ignored by git.

## 7. Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md): conventional commits, one logical unit per commit, permissive licenses only,
tests before merge. Architecture decisions go to `docs/decisions/` as a new ADR.

## 8. License

Apache-2.0, see `LICENSE` and `NOTICE`.
