# CONTEXT - `app/electron/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/app__electron.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Process main Electron. `main.ts` : fenetre, icone runtime (`scripts/icon.*`), IPC. `preload.ts` : `window.electronAPI`. `python_bridge.ts` : spawn du backend (dev `python backend/main.py`, prod `resources/backend/flux_backend.exe`), reutilise un backend deja sur 8765, retry antivirus, lecture du jeton API `GET /auth/token` (S1) ; `main.ts` injecte `X-Flux-Token` sur les requetes.

Ne pas casser : port 8765, chemin du sidecar package, `preload.js` dans `dist-electron/`.
