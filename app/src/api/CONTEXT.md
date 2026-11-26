# CONTEXT - `app/src/api/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee de mai 2026 retiree (lisible au tag `archive/pre-cleanup`).
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`client.ts` : client HTTP unique vers `127.0.0.1:8765` (GET conditionnels ETag `If-None-Match` pour les feeds). Le header `X-Flux-Token` est injecte par `electron/main.ts`, pas ici.

Toute nouvelle route backend s'appelle d'ici, jamais par `fetch` direct dans une page.

`flows.ts` : appels de l'editeur de Flows (routes `/flows`, 2026-10-22) par `apiCall` (exporte de `client.ts`). Une erreur HTTP
porte `status` et `detail` (un `detail` objet `{message, ...}` donne `message` comme texte) : sert au 409 de conflit.
