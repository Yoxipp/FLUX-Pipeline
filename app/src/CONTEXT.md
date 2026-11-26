# CONTEXT - `app/src/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee de mai 2026 retiree (lisible au tag `archive/pre-cleanup`).
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`.

Renderer React 18 + TypeScript + Tailwind + Radix. `App.tsx` : HashRouter + routes. `ProjectContext.tsx` : projet courant. `i18n.tsx` : FR/EN. `lib/pollIntervals.ts` : cadences de polling centralisees. `lib/*ExportOptions.ts` : options d'export par DCC.

Verif : `npx tsc --noEmit -p tsconfig.json`.
