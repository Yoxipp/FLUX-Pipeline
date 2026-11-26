# Flows : ce qui est dispo, ce qui arrive

Etat au 2026-10-24. Le chantier suit les phases P0 a P8 (`docs/yaml_update_refonte/prompts/README.md`, ADR 0057 et 0058).
P0 a P7 sont codees ; leur verification live par le mainteneur reste a faire. Catalogue prevu au total : 185 types de node,
dont **178 disponibles** aujourd'hui (liste dans [03_INDEX_NODES.md](03_INDEX_NODES.md)).

## 1. Disponible maintenant

| Domaine | Ce qui marche |
|---|---|
| Editeur | Shelf par famille, Tab, Catalogue, liens controles par type pendant le glisser, Params editable, undo / redo, copier / coller, groupes, notes, Layout, recherche, bypass, (i) doc du node |
| Fichiers | Nouveau, Ouvrir (Pipe, Projet, Perso), Enregistrer, Enregistrer sous, Enregistrer et incrementer, Versions (voir, revenir, historique), conflit entre postes, brouillon local, quitter = enregistrer |
| Garde-fous | Dock Problemes (erreurs et avertissements, zoom sur le node, Corriger en un clic), badge invalide, dialogue des nodes destructifs a l'enregistrement |
| Execution | Run du brouillon avec formulaire de l'interface, Stop, Essai a blanc du fichier enregistre, etats en direct sur les nodes, historique des runs avec logs |
| Logique | Branches (If, Switch, Sequence), boucles ForEach / For / While avec plafond, BreakLoop, variables, gestion d'erreur `on_error`, sous-flows (`FlowCall`, `FlowOutput`) |
| Pipeline | Lire la Production (assets, plans), trouver des publishs, resoudre un chemin publie, publier un fichier, archiver, notifier, pinguer, textures `.tx`, proxy USD, controle et aplatissement USD, mise a jour du component / stage |
| Flows actifs | Bouton Activer (0 erreur, avertissements lus, essai a blanc reussi), evenements `Schedule`, `NewFile`, `When`, `OnPublish`, `SceneOpened` (Maya, Houdini), un seul poste execute les flows d'equipe |
| Logiciels (Houdini, Maya) | `HoudiniInstance`, `MayaInstance` (Live : se connecte ou ouvre le logiciel ; Headless : `hython` / `mayapy`, une licence), nodes `hou*` et `may*` (ouvrir, enregistrer, script, export, import, publish, parms / attributs, cook, rendu, MAJ des imports, playblast), Bridges, `RunHeadless`, `Batch`, nodes livres verrouilles (double clic pour entrer, Deverrouiller en copie d'equipe, Revenir au defaut), flows livres `publish_maya` / `publish_houdini` (lances avec Run) |
| Autres logiciels | Nuke (scenes, script, export, import, rendu d'un Write, recherche), Painter, Designer (dont `sdCook` sans ouvrir Designer), Marvelous, ZBrush, Mari : Instance, export, infos, publish ; flows livres `publish_<logiciel>` |
| Extensions | Nodes Python d'equipe (`CONFIG/extensions/nodes/`, ecrits depuis l'editeur), migration des actions v1 de l'equipe en flows (Fichier > Migrer) |
| Pages TOOL | Onglet TOOL (groupe ASSETS) : pages de l'equipe ou du projet, boutons qui lancent un flow actif avec les champs de la page, etat du dernier run, editeur de page (palette, arbre, proprietes, apercu, "Au clic" ajoute le node Bouton), modeles Daily render, Team (chat d'equipe par canaux, fils, reactions, epingles, fichiers joints, appels par lien, presence, membres, calendrier) et Board facon Miro (notes, cartes, formes, texte, images, liens fleches, selection multiple, copier / coller, undo local, groupes, verrou, mini-carte, recherche, cadres + presentation, stylo, images collees / deposees, cartes FLUX, modeles, commentaires, reactions, minuteur, export PNG / PDF) ; donnees partagees entre postes (`PageData`, `PageDataRead`, `PageDataWrite`) |
| Publisher genere | Un logiciel ajoute en extension a son panneau Publisher, genere depuis l'interface de son flow `publish_<logiciel>` |
| Dispatcher | Nodes `Submit`, `JobStatus`, `WaitJob`, `CancelJob`, `RenderShot` (husk Karma / RenderMan) et ForEach `mode: dispatch` : le backend (`local` ou `tractor`) vient de `CONFIG/dispatcher.json`, surchargeable par projet. Tractor reste en simulation tant que le spool n'est pas valide sur la farm |
| Livres | 5 flows `legacy_*` (actions v1 en lecture seule), 4 exemples (`example_foreach`, `example_error`, `example_daily_render`, `example_rig_publish_notify`) |

Limites actuelles a connaitre :

* **Le publish tourne encore sur les actions v1** : un flow `legacy_publish_*` se lit mais ne s'active pas (P8).
* **Logiciels** : rien n'est encore valide dans les logiciels eux-memes (a verifier par le mainteneur), surtout `mayPlayblast`, le
  headless et chaque logiciel de P6b. Painter, Designer, ZBrush, Mari et Marvelous n'ont pas encore ouvrir / enregistrer /
  script (commande a ajouter dans leur bridge, sur accord).
* Le Publisher ne passe pas encore par `publish_maya` / `publish_houdini` (P8) ; `houPublish` publie dans le Houdini
  choisi dans FLUX.
* Le bouton **Subnet** de la barre est grise (sous-reseau dans un flow : P6).
* `SceneOpened` ne connait que Maya et Houdini (autres logiciels : P6b).

## 2. A venir, par phase

### Reste de P6a

* **Subnet** : regrouper des nodes dans un sous-reseau, U pour remonter (le bouton reste grise).

### P6c : bridge maison

Brancher un logiciel que FLUX ne connait pas (exemple : 3ds Max) avec un `bridge.yml` et deux flows (`session`,
`publish`) assembles avec les nodes Bridges. Aucun type de node en plus.

### P8 : bascule du publish

* Le publish de chaque logiciel passe par des flows `publish_<soft>` (retour arriere possible par un switch).
* Node `RefusePublish` : arrete un publish avec un message (controle maison avant publication).
* Retrait de l'ancien editeur d'actions v1.

## 3. Hors V1 (pas prevu pour l'instant)

* ForEach en parallele dans FLUX meme (work items facon PDG). Pour paralleliser sur la farm : ForEach `mode: dispatch`.
* Photoshop (`ps`) et Unreal (`ue`) : prefixes reserves, clients existants, aucun node en V1.
* Publish decoupe en petits nodes : le publish reste une boite noire.
* Fusion de deux versions en conflit.
