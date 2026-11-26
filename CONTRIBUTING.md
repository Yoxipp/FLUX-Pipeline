# Contributing to FLUX

Thanks for taking the time to help. Bug reports, ideas, docs fixes and code are all welcome, whatever your level.
Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) in every exchange.

## Ways to help

* **Report a bug**: open an issue with what you did, what you expected, what happened, your FLUX version
  (Settings) and the software involved (Maya 2025, Houdini 21, ...). Logs help a lot.
* **Suggest a feature**: open an issue that describes the problem first, then your idea of a solution.
* **Fix or improve something**: comment on the issue you want to take so nobody does the same work twice, then send a
  pull request.
* **Security issue**: do not open a public issue, see [SECURITY.md](SECURITY.md).

## Set up a dev environment

Windows 10 / 11, [Node.js](https://nodejs.org/) with npm, Python 3.13.

```bash
pip install -r backend/requirements.txt
npm install
npm run dev
```

Build and packaging details: [docs/development/BUILD.md](docs/development/BUILD.md).

## Before you code

1. Read the overview in [README.md](README.md), then the system docs in [docs/architecture/](docs/architecture/).
2. Look for the decision record of your topic in [docs/decisions/](docs/decisions/README.md). An accepted decision is
   changed by a new record, never by editing the old one. If your change needs a new decision, propose it in the issue.
3. Read the `CONTEXT.md` of the folder you touch: it gives the role of the folder and its pitfalls.

## Branches and pull requests

* `main` is the released version, `dev` is where work is integrated.
* Branch from `dev`: `feat/<issue>-<short-name>`, `fix/...`, `docs/...`, `chore/...`.
* One pull request per issue, targeting `dev`, with `Closes #<issue>` in the description.
* Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`,
  `refactor:`, `test:`. One logical change per commit.

## Conventions

* Python: snake_case, code and comments in English, type hints where the file already uses them.
* TypeScript / React: follow the style of the file. `tsconfig.json` is strict (no unused locals or parameters).
* UI text goes through `app/src/i18n.tsx` (French and English). No em dash in UI text, flat colours with light
  elevation (no neon or glow).
* New dependency: permissive license only (MIT, BSD, Apache), no linked GPL, and nothing that consumes a DCC license.

## Tests

| What | Command |
|---|---|
| Backend (from `backend/`) | `python tests/run_tests.py`, must end with `verdict: PASS` |
| One backend suite (from `backend/`) | `python -m unittest discover -s tests/<suite> -t .` |
| Front-end logic | `npm run test:js` |
| Types | `npx tsc --noEmit -p tsconfig.json` and `npx tsc --noEmit -p tsconfig.electron.json` |

* Add or update tests for every behaviour you change.
* Do not run a global `python -m unittest`: `usd-core` aborts at teardown on Windows, `run_tests.py` works around it.
* Code that runs inside a DCC (plugins, autostart, HDA, bridges) must also be checked live in that software. Say in
  the pull request which versions you tested.
* USD golden file: `FLUX_REGEN_GOLDEN=1 python tests/run_tests.py` rewrites
  `backend/tests/usd_assembler/golden/CHAR_hero.usda`; review its diff before committing it.

## Areas that need extra care

These files affect every user or the installer. Check every caller before changing them and say so in the pull request.

| Area | Why |
|---|---|
| `backend/features/publisher/publish_core.py`, `publish_layout.py`, `resolve_publish_path` | Every publish of every DCC, compatibility with existing projects. |
| `backend/core/paths.py`, `backend/core/config.py` | Workspace root and installed mode: an app that no longer starts. |
| Metadata document keys, stores, `migrate_json_to_sqlite.py` | Data of existing projects. |
| `backend/dcc/*/autostart.py`, `backend/dcc/houdini/flux_houdini_server.py`, HDA sources | Code copied into the DCC preferences. |
| `scripts/backend.spec`, `scripts/electron-builder.yml`, `app/electron/python_bridge.ts` | Installer build (paths listed in `docs/development/STRUCTURE.md`). |

A few known traps:

* Never write into `houdini.env` (Houdini 22 crash); `$FLUX` comes from the `flux.json` package.
* Never let the pip `usd-core` reach Houdini's own Python.
* No SQLite on OneDrive or a network share. File bytes never go through the HTTP API.
* Never commit `config.json`, `USER/`, `CONFIG/`, `DOSSIER_PROJETS/` or build outputs.
* A new YAML in `backend/flux_actions/config/` must be tracked: check with `git check-ignore`.

## After you code

Update the `CONTEXT.md` of the folder you changed, and `docs/development/STRUCTURE.md` if the tree or a build path moved.

## License of contributions

FLUX is licensed under the [Mozilla Public License 2.0](LICENSE). By sending a contribution you agree that it is
licensed under the same terms.
