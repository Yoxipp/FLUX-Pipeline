# CONTEXT - `app/src/api/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/app__src__api.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

`client.ts` : client HTTP unique vers `127.0.0.1:8765` (GET conditionnels ETag `If-None-Match` pour les feeds). Le header `X-Flux-Token` est injecte par `electron/main.ts`, pas ici.

Toute nouvelle route backend s'appelle d'ici, jamais par `fetch` direct dans une page.
