# CONTEXT - `app/electron/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee de mai 2026 retiree (lisible au tag `archive/pre-cleanup`).
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`.

Process main Electron. `main.ts` : fenetre, icone runtime (`scripts/icon.*`), IPC. `preload.ts` : `window.electronAPI`. `python_bridge.ts` : spawn du backend (dev `python backend/main.py`, prod `resources/backend/flux_backend.exe`), reutilise un backend deja sur 8765, retry antivirus, lecture du jeton API `GET /auth/token` (S1) ; `main.ts` injecte `X-Flux-Token` sur les requetes.

Ne pas casser : port 8765, chemin du sidecar package, `preload.js` dans `dist-electron/`.

Fenetres detachees (U4, ADR 0027) : `ipcMain.on('window:detach', route)` -> `createDetachedWindow` (liste blanche `DETACHABLE_ROUTES`, au curseur, meme preload / session, URL `?detached=1#<route>`). Les controles de fenetre visent `BrowserWindow.fromWebContents(sender)`. Fermer la principale ferme les autres.

Mise a jour au lancement (2026-09-27) : `updater.ts`, appele dans `main.ts` avant le splash. Lit `workspace` dans `config.json` (meme chemin que `backend/core/paths.py get_config_json_path`), prend le plus haut `FLUX_UPDATE/FLUX-Setup-x.x.xxx.exe` ; plus recent que `app.getVersion()` -> dialogue "Mettre a jour / Plus tard". Oui : installeur lance detache, FLUX quitte sans demarrer le backend. Non : demarrage normal, redemande au prochain lancement. App packagee seulement (dev : `FLUX_UPDATE_CHECK=1`). Lecture du dossier limitee a 3 s.
