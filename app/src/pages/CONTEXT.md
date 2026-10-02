# CONTEXT - `app/src/pages/`

> Reecrit court le 2026-09-16 (V7-05). Ancienne fiche detaillee (mai 2026, en partie perimee) : `docs/archive/context_md_2026-05/app__src__pages.md`.
> Vue d'ensemble : `docs/architecture/OVERVIEW.md`. Etat, bugs, dette : `docs/notes/CURRENT_STATE.md`.

Pages : `Hub`, `Projects` (Folder Manager, 1630 l. + `folder_manager/`), `Production/`, `Publisher` (1999 l.), `UsdAssembler` (vue Bibliotheque par defaut `usd/UsdLibrary.tsx` : assets, decors ; onglet Shots retire, ADR 0023), `Activity`, `ShelfManager`, `TemplateEditor`, `ActionPublish`, `ActionGraph` (node flow lecture seule, route cachee `/action-graph`), `FirstLaunch`, `Login`.

Pages geantes = dette connue, ne pas les decouper sans demande.

## Production (2026-10-02)

* `ProductionTracking.tsx` + `tracking.css` : table Shots/Assets par departement, recherche,
  filtre de sequence/categorie, miniatures, casting, dependances, zoom et editeur de colonnes
  de projet. Style plat, fonds chauds et accent Flux. Les panneaux restent accessibles par
  Proprieties et Taches/retakes ; anciennes preferences conservees.
* `tracking.ts` : statuts agreges, heritage des taches/casting, dependances, materialisation
  des taches et patch de review sans perdre les notes. Configuration optionnelle
  `production.tracking.departments`, review dans `task_details.status` (ADR 0041).
* Un badge ouvre `MenuSpec.initialOpen` avec l'entite, la tache et la sous-tache choisies.
  Aucun nouveau store de review. N/A + cree une tache explicitement. Les miniatures utilisent
  les references versionnees existantes, sous `_production/thumbnails/<id>`.
* La timeline et les categories/groupes restent dans le selecteur de vue ; le suivi
  tabulaire est la vue initiale. La configuration globale de presets utilisateurs reste hors scope.

## Folder Manager (`Projects.tsx` + `folder_manager/`, B2 2026-09-28)

* `Projects.tsx` : la page. Barre laterale (listes sauvegardees, presets, tailles), Token Finder, onglets de creation,
  panneau droit, choix des vues (1 / 2 empilees / 2 cote a cote / 4), et l'etat partage par les vues
  (`FolderManagerContext` : favoris, presse-papier, undo, `transfer` = tout deplacement / copie, `fsTick` = relecture
  de toutes les vues apres une ecriture). La vue active (dernier clic, cadre accent) pilote le panneau droit, le projet
  actif, les presets et les resultats du Token Finder.
* `folder_manager/ExplorerPane.tsx` : une vue (historique, barre de chemin, recherche, grille, selection, menu clic
  droit, modales). Memoire de session par vue (`fm.navStack` pour la vue 0, `fm.paneN.*` pour les autres). Glisser
  d'une vue a l'autre : Ctrl = copie, sinon deplacement, meme projet seulement.
* `folder_manager/shared.ts` (types, helpers, contexte), `open_in.ts` (actions "Open in" DCC), `ItemModals.tsx`,
  `icons.tsx`.
