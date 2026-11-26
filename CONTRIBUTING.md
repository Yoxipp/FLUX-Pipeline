# Contributing to FLUX

## Before coding

1. Read `docs/architecture/OVERVIEW.md` (architecture, systems), then `docs/notes/CURRENT_STATE.md` (what works,
   known bugs, debt).
2. Read the ADR of the topic in `docs/decisions/`. An accepted decision is only changed by a new ADR, never by editing
   the old one.
3. Read the `CONTEXT.md` of the folder you touch.

## Conventions

* Python: snake_case, code and comments in English, type hints where the file already uses them.
* TypeScript / React: follow the conventions of the file. `tsconfig.json` is strict (no unused locals / parameters).
* UI text: French and English through `app/src/i18n.tsx`. No em dash, no neon / glow (flat fills, light elevation).
* Commits: conventional (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`), one logical unit per commit.
  Stage files by name, never `git add -A`.
* New dependency: permissive license only (MIT / BSD / Apache), no linked GPL, nothing that consumes a DCC license
  (ADR 0007).

## Tests

* Backend: `python tests/run_tests.py` from `backend/`, must end with `verdict: PASS`. Add tests for every changed
  behavior, one folder per suite under `backend/tests/`.
* Front-end: `npx tsc --noEmit -p tsconfig.json` and `-p tsconfig.electron.json`.
* Anything that runs inside a DCC (autostart, HDA, bridges) must also be checked live in the software.
* USD golden file: `FLUX_REGEN_GOLDEN=1 python tests/run_tests.py` rewrites
  `backend/tests/usd_assembler/golden/CHAR_hero.usda`; review the git diff before committing it.

## Risky areas (check every caller first)

| Area | Why |
|---|---|
| `backend/features/publisher/publish_core.py`, `publish_layout.py`, `resolve_publish_path` | Every publish of every DCC, compatibility of existing projects. |
| `backend/core/paths.py`, `backend/core/config.py` | FLUX_ROOT and frozen mode: an installed app that no longer starts. |
| Metadata document keys, stores, `migrate_json_to_sqlite.py` | Data of existing projects (ADR 0004). |
| `backend/dcc/*/autostart.py`, `dcc/houdini/flux_houdini_server.py`, HDA sources | Code copied into the DCC preferences. |
| `scripts/backend.spec`, `scripts/electron-builder.yml`, `app/electron/python_bridge.ts` | Installer build (paths listed in `docs/development/STRUCTURE.md`). |

## Never

* Write into `houdini.env` (Houdini 22 crash); `$FLUX` comes from the `flux.json` package and the autostart.
* Let the pip `usd-core` reach Houdini's Python.
* Put SQLite on OneDrive or a network share; send file bytes through the HTTP API.
* Commit `config.json`, `USER/`, `CONFIG/`, `DOSSIER_PROJETS/`, `scratchpad/`, build outputs.
* Add a YAML in `backend/flux_actions/config/` without checking it is tracked (`git check-ignore`).

Full list of things not to redo: `docs/history/HISTORY_ANALYSIS.md` section 4.

## After coding

Update the folder `CONTEXT.md`, `docs/development/STRUCTURE.md` if the tree or a build path changed, `docs/notes/CURRENT_STATE.md`,
`docs/notes/NEXT_STEPS.md` if the roadmap moved, and write an ADR for any architecture choice.
