# CONTEXT - `app/src/components/shared/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/app__src__components__shared.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Composants communs : `Sidebar`, `TitleBar` (tiroir console), `StatusBar` (DCC connectes), `Console` (logs `/logs`), `BackendBanner` (reconnexion), `ExportOptions` + `SoftwareSelector` (Publisher), `ActionForm`, `ui.tsx`, `Logo`.

## Profils de travail et interface allegee (2026-10-07, ADR 0042 + 0043)

* `WorkProfileDialog.tsx` + `workProfile.css` : seul endroit ou se gerent les profils (FLUX
  integres, projet, perso). Un profil pre-regle les colonnes de Show (Production), les
  notifications d'activite, la page de demarrage, le Launcher et le logiciel du Publisher.
  Pas de Folder Manager (ADR 0043). Ouvert par `openWorkProfile()` depuis Parametres, le clic
  droit du Launcher, Production > Show et Activity > Notifications. Monte une fois dans `App`.
* Etat : `app/src/WorkProfileContext.tsx` (User.json `work_profile`, sauvegarde debouncee 400 ms,
  profils du projet actif via `/folder/projects/{p}/work-profiles`) ; modele pur et validation
  dans `app/src/lib/workProfiles.ts` (tests `scripts/tests/work-profiles.test.cjs`).
* Notifications : `App.tsx` (MentionWatcher, FavoriteWatcher) suivent les prefs ; regle pure
  `lib/activityNotify.notificationReason` (tests `activity-notify.test.cjs`), categories
  `actionToType` partagees avec la page Activity.
* `Sidebar` Launcher : mode compact par defaut. Lancer reste visible ; chemin, bridge, Photoshop et
  New Scene au survol / focus et dans le clic droit de la ligne (aussi touche Menu / Shift+F10,
  Entree lance). Restent toujours visibles : chemin manquant, Maya bloque, plusieurs instances,
  chargements. "Auto-detecter" n'apparait que s'il manque un chemin. Mode complet par profil.
* `SoftwareSelector` : `isVisible` replie derriere `+N` les logiciels non actives par l'utilisateur
  (le logiciel actif reste affiche). Utilise par Publisher et Shelf Manager.
* `TitleBar` / Parametres : resume du profil actif (et "modifie"), couleurs de console repliees.
* `tooltipPosition.viewportRect` : Electron 31 (Chromium 126) renvoie des rects non zoomes sous un
  ancetre `zoom` CSS ; toute ancre `position: fixed` portee dans body doit passer par cette fonction.
