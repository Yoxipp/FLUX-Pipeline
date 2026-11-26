# FLUX documentation

Overview of the whole repository: [../README.md](../README.md).

| Folder | Read it for |
|---|---|
| `../backend/resources/manual/FLUX_Manuel.html` | The manual (French): artist guide (part A) and technical guide (part B). |
| `architecture/` | Living system docs: `PIPE_LOGIC` (pipeline logic), `USD_STRATEGY`, `USD_ASSEMBLER_V2`, `USD_PIPELINE_REFERENCE`, `HOUDINI_WORK` (FLUX Work), `ESMA_ENV` (school environment). |
| `decisions/` | Architecture Decision Records, `0001` to `NNNN`. Start with `README.md`. |
| `development/` | `BUILD.md` (dev launch, installer, versioning), `STRUCTURE.md` (tree and build-sensitive paths), `REZ.md`, `PUBLISH_ROLLBACK.md`, `FLOWS_BRIDGE_3DSMAX.md`. |
| `user/flows/` | User doc of the Flows editor (French): overview, available vs coming, node index. `03_INDEX_NODES.md` is bundled in the app and shown by the (i) button of each node; the HTML manual is generated from it (`python -m features.system.flows_doc`). |
| `history/` | `HISTORY_ANALYSIS.md` (old prompts against the code, section 4 lists what must not be redone), dated audits. |
| `notes/` | Living project memory: `PROJECT_CONTEXT.md`, `CURRENT_STATE.md`, `NEXT_STEPS.md`, `ISSUES_BACKLOG.md`, `GITNEXUS.md`, `PLAN_*.md`. `prompts/` holds the work briefs that still have open items. |
| `archive/` | Read-only. `studies/`: finished studies and analyses (stack, local / network / web, Prism vs USD, cross-platform, Unreal U0). `prompts/`: finished work briefs. Never a current spec. |

Rules: a finished prompt moves to `archive/prompts/`, a finished study to `archive/studies/`; open points go to
`notes/ISSUES_BACKLOG.md`. Anything removed before the 2026-11 cleanup is readable at the git tag `archive/pre-cleanup`.
