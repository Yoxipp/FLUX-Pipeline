# CONTEXT - `app/src/hooks/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/app__src__hooks.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Hooks de donnees : `useFlowsWs` (WS `/flows/ws` des Flows, modele `useDccStatus` : reconnexion 3 s, `onReconnect` pour relire le run), `useDccStatus`, `useActiveInstances`, `useBackendStatus`, `useActivity`, `useMentions`, `useFeeds`, `useCommentReadState`, `useProduction`, `useSettings`, `useFavorites`, `useEnabledDccs`.

`useEnabledDccs` (V8 U10) : DCC actives par utilisateur (`/settings/enabled-dccs`, `USER/<user>/UserSettings/User.json` cle `enabled_dccs`). `null` = toutes. Evenement `flux:enabled-dccs`. Liste DCC partagee : `lib/dccs.ts`.

Les intervalles viennent de `lib/pollIntervals.ts`.

`useSessionState` (U3, 2026-09-24) : useState garde en memoire le temps de la session (Map de module, oublie au relancement). Folder Manager (`fm.*` : dossier, onglets), Production (`prod.selection` par projet, onglets de taches `prod.specTabs:<projet>`) : on revient ou on etait.
