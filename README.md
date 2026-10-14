# FLUX

Desktop 3D / VFX pipeline for ESMA student teams: project tree from naming tokens, immutable versioned publishes
(`vNNN` + `LAST`), one-click import into the DCCs, USD assembly (assets, sets, shots), production tracking,
team activity, chat and calendar.

* Windows only, local-first (local folder, OneDrive or school server).
* Apache-2.0, permissive dependencies only, no DCC license token consumed by any step.
* DCCs: Maya, Houdini, ZBrush (validated); Nuke, Substance Painter / Designer, Mari, Marvelous, Photoshop (bridges).

**Artists**: read the manual, `backend/resources/manual/FLUX_Manuel.html` (French). FLUX copies it into
`<workspace>/FLUX_DOC/` at every start, and shows it in Settings > Doc.

## Architecture

```
app/electron (Electron main)  --spawn-->  backend/main.py  FastAPI on 127.0.0.1:8765 (per-launch X-Flux-Token)
app/src      (React + TS)     --HTTP-->   backend/routers  ->  features/*        domain logic
                                                           ->  flux_actions + flux_core   YAML action engine (publish)
                                                           ->  core/*            config, paths, metadata repository, storage
                                                           ->  dcc/<soft>        backend clients + in-DCC plugins
Metadata: MetadataRepository (JSON default | SQLite | remote)     Bytes: filesystem only, never through the API
```

## Quick start (dev)

Requirements: Windows, Node.js + npm, Python 3.13.

```bash
pip install -r backend/requirements.txt
npm install
npm run dev
```

Or double-click `FLUX_DEV.bat`. Electron starts Vite and spawns the Python backend (an already running backend on
port 8765 is reused).

| Task | Command |
|---|---|
| Backend tests (from `backend/`) | `python tests/run_tests.py` (expects `verdict: PASS`) |
| One test suite (from `backend/`) | `python -m unittest discover -s tests/<suite> -t .` |
| Front-end types | `npx tsc --noEmit -p tsconfig.json` |
| Electron types | `npx tsc --noEmit -p tsconfig.electron.json` |
| Installer | `BUILD_INSTALLER.bat` or `npm run build`, output in `INSTALLEURS/` |

Never run a global `python -m unittest`: `usd-core` aborts at teardown on Windows, `run_tests.py` works around it.

## Repository map

| Path | Content |
|---|---|
| `app/electron/` | Electron main process: windows, sidecar launch, API token, updater |
| `app/src/` | React UI: `pages/`, `components/shared/`, `api/client.ts`, `i18n.tsx` |
| `backend/` | FastAPI sidecar: `routers/`, `features/`, `core/`, `flux_core/`, `flux_actions/`, `dcc/`, `resources/`, `tests/` |
| `scripts/` | Build: PyInstaller spec, electron-builder config, NSIS, HDA build |
| `docs/` | Documentation, see [docs/README.md](docs/README.md) |
| `public/` | Static assets |

Every important folder has a short `CONTEXT.md` (role and pitfalls). Build-sensitive paths: `STRUCTURE.md`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Architecture decisions live in `docs/decisions/` (ADR).

## License

Apache-2.0, see `LICENSE` and `NOTICE`.
