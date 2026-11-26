# Flows : vue globale

Etat au 2026-10-23 (phases P0 a P4 codees). Ce qui manque encore est dans [02_DISPO_ET_A_VENIR.md](02_DISPO_ET_A_VENIR.md).

## 1. Un flow, c'est quoi

Un flow est une petite automatisation du pipeline dessinee en nodes, comme un reseau Houdini ou un Blueprint Unreal :
"chaque soir, copie les playblasts du jour dans le dossier des dailies", "quand je clique ce bouton, archive les
anciennes versions", "apres un publish de modeling, regenere le proxy". Chaque node fait une seule chose (lire une
valeur, tester une condition, copier un fichier, publier) ; les liens disent dans quel ordre et avec quelles donnees.

Un flow est un fichier texte `<nom>.flow.yml` : lisible, comparable d'une version a l'autre, versionne. L'editeur
n'est qu'une facon de le dessiner ; rien n'est cache dans l'app.

## 2. Objectifs

* **Automatiser sans coder** : les TD du projet montent eux-memes leurs outils avec des briques sures, au lieu de
  demander un script Python.
* **Difficile de se tromper** : les ports sont types (un lien impossible est refuse pendant le glisser, avec la
  raison), chaque probleme est liste avec sa correction en un clic, les nodes qui effacent ou ecrasent sont marques et
  demandent une confirmation, un essai a blanc montre ce qui se passerait sans rien ecrire.
* **Rien n'est perdu** : chaque enregistrement important fige une version, revenir en arriere cree une nouvelle
  version, supprimer met a la corbeille, l'effacement d'un fichier du projet passe par defaut par `ARCHIVE/`.
* **Remplacer les actions YAML v1** : le publish de chaque logiciel deviendra un flow (phase P8). En attendant, les
  actions v1 sont visibles comme flows `legacy_*` (lecture seule) et le publish tourne toujours sur v1.
* **Zero licence** : tout ce que FLUX sait faire seul (textures `.tx`, proxy USD, controle USD, copie, zip) se fait
  sans ouvrir de logiciel.

## 3. Vocabulaire

| Mot | Sens |
|---|---|
| Node | Une brique. Bande de titre a la couleur de sa famille, une ligne par port. |
| Famille | Le role du node : Evenements, Data, Logique, Operateurs, Actions, FLUX, Instances, DCC, Bridges, Sous-flow. |
| Port | Une entree (a gauche) ou une sortie (a droite). Il a un type : `exec`, `str`, `int`, `float`, `bool`, `path`, `dir`, `list[...]`, `dict`, `publish`, `any`... Survoler un port montre son type, sa doc et un exemple. |
| Lien exec | Lien blanc entre ports `exec` / `then` : l'ordre d'execution. Une sortie exec n'a qu'un seul lien (pour plusieurs suites : Sequence). |
| Lien data | Lien colore : une valeur passe d'une sortie vers une entree. Une entree non reliee prend la valeur ecrite dans ses parametres. |
| Evenement | Le node de depart d'un flow (Button, Manual ; plus tard Schedule, NewFile, OnPublish...). Il n'a pas d'entree exec. |
| Node a effet | Agit sur le monde (copie, publie, notifie). Pendant un essai a blanc il ne fait rien et dit ce qu'il aurait fait. |
| Node destructif `!` | Peut effacer ou ecraser (Delete en mode erase, Copy avec overwrite...). Marque `!`, demande une confirmation a l'enregistrement. |
| Portee | Ou vit le flow : livre (FLUX), Pipe / equipe, Projet, Perso. |
| Version | Copie figee `vNNN` du flow. Le fichier de travail est ce qu'on edite ; une version est ce qui s'active. |
| Run | Une execution. Chaque run est enregistre (etat de chaque node, logs, valeurs). |
| Essai a blanc | Run de la version enregistree ou les nodes a effet sont simules : rien n'est ecrit, aucun logiciel lance. |

## 4. Comment un flow s'execute

1. **Depart** : un evenement part (clic sur Run dans l'editeur, bouton de page, appel par un autre flow).
2. **Chaine exec** : le moteur suit le lien `then` de l'evenement, execute le node relie, puis suit son `then`, et ainsi
   de suite. Un node de branchement (If, Switch, Sequence) choisit la sortie exec a suivre.
3. **Donnees tirees a la demande** : quand un node s'execute, ses entrees reliees vont chercher leur valeur. Un node sans
   port exec (Value, Path, Compare, Math...) est calcule a ce moment-la, une seule fois par tour. Un node de la chaine exec
   donne ses dernieres sorties ; lire une sortie d'un node pas encore execute est une erreur ("donnee lue avant d'etre
   produite").
4. **Boucles en blocs** comme Houdini : `ForEachBegin` ... `ForEachEnd`, `ForBegin` ... `ForEnd`, `WhileBegin` ...
   `WhileEnd`. Ce qui est relie entre les deux tourne a chaque tour ; `BreakLoop` sort de la boucle. Un While a toujours
   un plafond de tours : jamais de boucle infinie.
5. **Erreurs** : un node qui echoue s'entoure de rouge avec le message et le run s'arrete. Pour gerer l'erreur
   soi-meme (comme un try / except), relier sa sortie `on_error` : le node passe en "erreur geree" et la suite part de la.
6. **Bypass** : un node bypasse est saute, le flux continue par son `then`.
7. **Fin** : le run se termine quand la chaine exec n'a plus de suite. Chaque node garde son etat (fini, erreur, saute).

Limites : 4 runs a la fois sur le poste ; un node a 120 s par defaut (`timeout_s`). Le reglage du flow "Si deja en cours"
(`run_policy`) dit quoi faire quand un run est demande alors qu'un autre tourne : `skip_if_running` (ignore) ou
`queue` (file d'attente, 20 max).

### Textes : tokens, variables, motifs

Dans les parametres texte et chemin (pas dans une valeur arrivee par un lien) :

* `{token}` : un token du projet ou du run (`{project}`, `{user}`, `{shot}`, `{date:%Y%m%d}`...). Un token inconnu est
  une erreur avec une suggestion (`{shto}` -> `{shot}`).
* `${variable}` : une variable du flow (panneau Params du flow > Variables).
* `$FLUX/...` en tete d'un chemin : la racine FLUX, pour un chemin portable entre postes.
* Motifs facon Houdini (ListFilter, ListFiles, FindPublishes...) : `*` n'importe quoi, `**` sous-dossiers, `?` un
  caractere, `[abc]` un caractere parmi, `^` ou `!` exclut. Plusieurs motifs separes par des espaces, lus de gauche a
  droite : `*.abc ^*_tmp*` garde les .abc sauf les temporaires. Motif vide = ne garde rien.

### Comment lire un flow

Trois sortes de liens, trois questions :

* **Evenement = le depart.** Le node a bord arrondi a gauche (Manual, Button, OnPublish, Schedule...) dit QUAND le flow
  part. Il n'a pas d'entree exec.
* **Exec = l'ordre.** Les liens `exec` / `then` (port triangle) disent DANS QUEL ORDRE les nodes s'executent : on suit la
  chaine depuis l'evenement, de gauche a droite. `on_error` est la sortie prise si le node echoue.
* **Data = les valeurs.** Les autres liens (ronds et carres colores par type) disent D'OU VIENT chaque valeur. Un node
  sans port exec (Value, Template, Compare, PublishInfos...) est calcule quand un node de la chaine en a besoin.

Pour lire un flow inconnu : trouve l'evenement, suis les `then`, et pour chaque node regarde d'ou viennent ses entrees.
Le bouton (i) d'un node montre ses valeurs du dernier run en tete, et sa doc dans "Hints". Survoler le nom d'un port
ou d'un parametre dit a quoi il sert, son type, ses valeurs possibles et son defaut.

### Entrees et sorties d'un flow

Le chemin d'une valeur : formulaire du Run, page TOOL ou FlowCall (rempli avant le depart) > `FlowInput (id)` > nodes
du graph > `FlowOutput (id)` > sortie du FlowCall appelant (rendu a l'appelant).

* **Entrees (interface)** : ce que l'on remplit avant de lancer le flow (id, type, libelle, defaut, choix). Le Run de
  l'editeur les demande dans un formulaire, une page TOOL les montre en champs, un `FlowCall` les recoit en ports
  d'entree. Dans le graph, un node `FlowInput` (son `id` en gros sur le node) donne la valeur ; sans valeur, le defaut.
* **Sorties** : ce que le flow rend au `FlowCall` qui l'appelle. Un node `FlowOutput` les remplit ; elles sortent sur
  le port du meme nom du FlowCall. Lance seul, le flow garde ces valeurs dans son run.
* **Evenements** : une entree implicite. OnPublish, NewFile, PublishRequest... donnent leurs valeurs en sorties
  (`publish`, `path`, `infos`), sans passer par l'interface.

Le panneau du flow (clic dans le vide) suit le graph : sous chaque entree, les FlowInput qui la lisent (clic =
selection) ou un bouton "Poser FlowInput" ; un FlowInput dont l'id n'est pas declare est liste avec "Ajouter a
l'interface". Pareil pour les sorties et FlowOutput. Sur un FlowCall, choisir `flow` remplit ses ports avec l'interface
du flow appele ; si elle change, un bouton "Mettre a jour les ports" apparait.

Trois exemples :

1. **Flow lance par une page** : `InputsPageReader (page: daily_render)` montre le bouton `Lancer maintenant` et le
   champ `Dossier` de la page. `Lancer maintenant` > `FindPublishes` > ... ; `Dossier` > `PathJoin.base`. Le clic lance
   le flow avec la valeur du champ ; a 22 h (Horaire), le champ donne sa valeur par defaut. Un champ qui porte l'id d'une
   entree du flow remplit aussi cette entree (`FlowInput` marche toujours).
2. **Sous-flow** : `make_daily` declare l'entree `soft` et la sortie `movie` (`FlowOutput (movie)` a la fin). Dans
   `daily_maya`, un `FlowCall (flow: make_daily)` a une entree `soft` (saisie `maya`) et une sortie `movie`, reliee a
   `Notify.path`.
3. **Flow de publish** : `publish_maya` declare `name`, `format`, `scope`... Le Publisher remplit ces entrees ;
   `PublishRequest` les donne en sorties (`values`, une par champ, et `infos` pour PublishInfos) ; `FlowOutput (path)` et
   `FlowOutput (version)` rendent le fichier publie.

### Variables d'un flow

Sans node selectionne, le panneau Params montre aussi les **proprietes** (libelle, description, "Si deja en cours") et
les **variables** : valeurs locales a un run, lues par `GetVariable` ou `${nom}`, ecrites par `SetVariable`.

## 5. Ouvrir l'editeur

Parametres > Avance > carte "Actions (YAML)" > **Ouvrir le graph**. La fenetre s'ouvre a part.

* Il faut la **case TD** (Parametres > User > Flows) pour editer et lancer ; la **case Team TD** pour ecrire un flow
  d'equipe ou de projet, un node Python, ou migrer les actions v1. Ces cases sont un garde-fou, pas une securite.
* L'ancien editeur d'actions v1 reste joignable depuis Parametres avances (lecture et edition des actions v1) jusqu'a P8.

Disposition : barre du haut (fichier, version, problemes, Run, Essai, Runs, Layout, groupe, note, recherche) ; Shelf
(un onglet par famille, les nodes courants) ; le graph au centre ; le panneau Params a droite ; le dock en bas
(Problemes, Runs) ; le tiroir Catalogue (tous les nodes, recherche).

## 6. Creer un flow

1. **Fichier > Nouveau** (Ctrl+N) : un nom en minuscules (`daily_render`, lettres, chiffres, `_`), une portee et le
   depart du flow :
   * **Perso** : pour soi (`USER/<NOM>/flows/`), case TD ;
   * **Pipe (equipe)** : pour tout le studio (`CONFIG/extensions/flows/`), case Team TD ;
   * **Projet** : pour le projet actif seulement (`<projet>/_flux_setup/flows/`), case Team TD.
   * **Le flow part** : bouton de page (`InputsPageReader`), a la main (`Manual` : Run, ou appele par un autre flow),
     apres un publish (`OnPublish`), horaire (`Schedule`), nouveau fichier (`NewFile`). Le node choisi est pose seul.
2. **Brancher le depart** : pour une page, selectionne `InputsPageReader`, choisis la page (ou **Creer une page pour ce
   flow** : un champ par entree du flow, un bouton Lancer) ; ses boutons et ses champs deviennent ses sorties. D'autres
   departs se posent depuis l'onglet Evenements du Shelf.
3. **Ajouter des nodes** : clic sur un node du Shelf (pose a droite du node selectionne et relie a sa premiere sortie exec libre, comme on empile des blocs ; sans selection, au centre), glisser depuis le Shelf ou le Catalogue (pose au
   point de depot), ou **Tab** dans le graph (recherche par nom, type, alias ou doc ; Entree pour poser a la souris).
4. **Relier** : glisser d'une sortie vers une entree. Pendant le glisser, les ports compatibles sont entoures, les autres
   pales ; survoler un port refuse donne la raison ("Une liste de chemins ne va pas dans un chemin : mets un ForEach").
   Lacher un lien dans le vide ouvre le menu Tab limite aux nodes compatibles, deja relies.
5. **Regler** : cliquer un node, remplir ses parametres dans Params. Une entree reliee affiche `<- n4.items` en gris.
6. **Exposer** ce que l'artiste doit choisir : Params du flow > Entrees (interface), puis un `FlowInput` dans le graph.
7. **Verifier** : le dock Problemes se met a jour tout seul. Cliquer une ligne zoome sur le node ; "Corriger" applique
   la correction proposee.
8. **Tester** : Run (brouillon), puis Enregistrer et Essai a blanc (voir §8).

Un flow livre (`legacy_*`, `example_*`) est en lecture seule : **Fichier > Enregistrer sous** en fait une copie
modifiable dans une autre portee.

**Exemples** (ADR 0069) : Fichier > Ouvrir > Exemples liste les flows livres `example_*`, en lecture seule et jamais
actifs. Pour s'en servir : clic droit > **Dupliquer** : le nom est propose sans `example_`, on choisit la portee ; la
copie est un flow normal, et la page TOOL que l'exemple lit est creee dans le projet si elle manque. Exemples livres :
`example_daily_render`, `example_foreach`, `example_error`, `example_rig_publish_notify`, et ceux de T1 (page
**annonces** : annonce a l'equipe ; page **livraison_plan** : stage USD aplati ou zip du plan ; page **controle_usd** :
UsdCheck de tous les LAST USD du projet en tableau ; `example_journal_rig` apres un publish de rig ;
`example_rapport_publishs` chaque lundi).

**Gerer un flow** : clic droit sur un flow de Fichier > Ouvrir (ou menu Fichier pour le flow ouvert) :
* **Dupliquer** : une copie du fichier enregistre, sous un autre nom et / ou une autre portee ;
* **Renommer** : meme portee, nouveau nom ; les versions suivent ;
* **Changer de portee** (projet, perso, equipe) : le flow part avec ses versions et son historique ; l'ancien va a la
  corbeille ;
* **Supprimer** : a la corbeille de sa portee.
Renommer et Changer de portee **desactivent** le flow (a reactiver : droits et declencheurs changent) ; une page dont
un widget lit la sortie du flow par son nom est a mettre a jour.

## 7. Editer

| Geste | Effet |
|---|---|
| Clic node, Shift / Ctrl + clic | Selectionne, ajoute a la selection |
| Glisser le fond | Rectangle de selection. Pan : bouton du milieu ou Espace + glisser. Molette : zoom |
| Survol d'un node | Barre : bypass, (i) doc du node |
| Clic lien + Suppr | Supprime le lien. Une entree deja reliee : le nouveau lien remplace l'ancien |
| Tab | Ajouter un node a la souris |
| Suppr / Retour arriere | Supprime la selection |
| Ctrl+Z, Ctrl+Y | Annuler, refaire (200 pas) |
| Ctrl+C, Ctrl+V | Copier / coller des nodes (marche entre flows et entre fenetres) |
| Ctrl+G | Boite de groupe autour de la selection |
| N | Note a la souris |
| F | Cadrer la selection (sinon tout) |
| Ctrl+F | Chercher : les nodes qui correspondent ressortent |
| Maj+S | Liens droits ou courbes |
| Layout (barre) | Range le graph de gauche a droite (annulable). Rien ne se range tout seul sinon |

**Nouveau node Python** (tiroir Catalogue, case Team TD) : ecrit un node d'equipe dans `CONFIG/extensions/nodes/`,
partage avec tout le studio, a partir d'un modele. Il apparait au catalogue avec le tag `equipe`.

## 8. Enregistrer, versions, lancer

* **Enregistrer** (Ctrl+S) : ecrase le fichier de travail. Permis meme avec des erreurs (le flow est alors marque
  "invalide", non activable).
* **Enregistrer et incrementer** (Alt+Maj+S) : fige une nouvelle version `vNNN` (seulement si le contenu a change).
* **Enregistrer sous** (Ctrl+Maj+S) : copie sous un autre nom ou une autre portee.
* **Versions** (clic sur `v003` dans la barre) : liste des versions (date, artiste), Voir (lecture seule), **Revenir a
  cette version** (cree une nouvelle version identique : rien n'est perdu), onglet Historique (qui a fait quoi).
* **Nodes destructifs** : enregistrer un flow ou un node `!` a ete ajoute ou passe en mode destructif ouvre un dialogue
  qui les liste ; il faut glisser pour valider.
* **Quitter = enregistrer** : fermer la fenetre ou changer de flow enregistre (avec le meme
  dialogue si besoin). Un brouillon est aussi garde localement en cas de fermeture brutale et propose a la reouverture.
* **Conflit** : si quelqu'un a enregistre pendant que tu editais, FLUX le dit (qui, quand) : voir sa version,
  enregistrer par-dessus (la sienne reste dans l'historique) ou annuler.
* **Run** : lance le document ouvert tel quel (brouillon, aucune version creee), avec le formulaire de l'interface.
  Les nodes s'allument en direct (en cours, fini, erreur, saute). **Stop** annule.
* **Essai** (essai a blanc) : lance le fichier **enregistre** ; les nodes a effet ne font rien et ecrivent ce qu'ils
  auraient fait dans le rapport. A faire avant toute activation.
* **Flow de page** (InputsPageReader avec des boutons) : Run et Essai demandent d'abord quel bouton jouer et les
  valeurs des champs (pre-remplies avec les defauts de la page) ; le flow part comme apres ce clic. Le dialogue
  Activer a le meme choix du bouton a cote de "Lancer l'essai" (valeurs par defaut de la page).
* **Runs** (dock) : historique des runs du flow ; clic = logs et graph colore par l'etat de chaque node.

## 9. Activer

Un flow **actif** tourne tout seul quand son evenement arrive (bouton de page, horaire, nouveau fichier, publish...).
C'est la version activee qui tourne, pas le fichier de travail : on peut continuer a editer un flow actif sans risque.

Bouton **Activer** (barre du haut) : un dialogue a 3 voyants sur la derniere version figee (Enregistrer et incrementer) :

1. **0 erreur** ;
2. **avertissements lus** : une case par avertissement ;
3. **essai a blanc reussi sur cette version** : bouton dans le dialogue, rapport de ce qui se serait passe.

Un flow avec un node `!` s'active en glissant pour confirmer. Une nouvelle version ne change pas la version active
(tag "vN non activee") : il faut reactiver. Droits : perso = TD, equipe et projet = Team TD. Un `legacy_*` ne s'active pas.

**Qui execute** : les evenements locaux (Run, bouton, `OnPublish`, `SceneOpened`) tournent sur le poste ou ils arrivent.
Les evenements globaux (`Schedule`, `NewFile`, `When`) d'un flow d'equipe ou de projet tournent sur **un seul poste** :
le premier FLUX ouvert prend un verrou (`CONFIG/extensions/runs/host.lock`) ; s'il se ferme, un autre reprend en
une minute environ. Un flow perso tourne seulement sur le poste de son auteur. Sans FLUX ouvert, rien ne tourne.
Reglages avances : "Flows actifs sur ce poste" (`FLUX_FLOWS_SCHEDULER`) et "Flows apres publish" (`FLUX_FLOWS_HOOKS`).

## 10. Ou vivent les flows

| Portee | Dossier | Qui ecrit |
|---|---|---|
| Livre | dans FLUX (`backend/flux_flows/shipped/`, exemples `example_*`) | personne (Dupliquer ou Enregistrer sous) |
| Pipe (equipe) | `<FLUX_ROOT>/CONFIG/extensions/flows/` | Team TD |
| Projet | `<projet>/_flux_setup/flows/` | Team TD |
| Perso | `<FLUX_ROOT>/USER/<NOM>/flows/` | TD proprietaire |

A nom egal, perso gagne sur projet, projet sur equipe, equipe sur livre. Supprimer met le flow dans `_trash/`.
Chaque flow a a cote de lui `versions/`, `state.json` (version courante, version active) et, sauf perso, un
`history.jsonl`.

## 11. Pages TOOL

Une page TOOL est un ecran de boutons et de champs, construit sans code : onglet **TOOL** du groupe ASSETS (il apparait
des qu'une page existe, ou pour un Team TD). Tout le monde voit et utilise les pages ; un Team TD les cree et les edite.
**C'est le flow qui choisit sa page** (ADR 0068) : un node `InputsPageReader` pose dans le flow lit la page ; la page ne
connait aucun flow.

* **Creer** : TOOL > Nouvelle : libelle, portee (equipe = tous les projets, ou le projet ouvert), depart vide, depuis un
  modele (Daily render, Team, Board) ou copie d'une page.
* **Editer** (bouton Editer, 4 colonnes facon Edit Parameter Interface) : Palette (cliquer un widget l'ajoute sous la
  selection), Arbre (dossiers > lignes > widgets, 4 par ligne au plus, fleches pour deplacer), Proprietes, Apercu (les
  boutons n'y lancent rien). Ctrl+S enregistre, Fermer enregistre puis quitte, Ctrl+Z / Ctrl+Y annulent.
* **Bouton** : un clic lance **tous les flows actifs** dont un `InputsPageReader` relie ce bouton (flows perso de
  l'artiste qui clique, equipe, projet), chacun sur sa version active. Sans flow actif, le bouton est grise avec la
  raison. Sous le bouton : en cours (Stop), fini il y a 3 min par ..., ou l'erreur. Dans l'editeur de page, les
  proprietes du bouton listent les flows qu'il lance ("Lance"), actifs ou non, avec Ouvrir.
* **Champ** : sa valeur part avec le clic sur la sortie du meme nom de l'`InputsPageReader` ("Lu par" liste ces flows).
  "Se souvenir" garde la derniere saisie de chaque artiste.
* **Ids** : proposes depuis le libelle. Renommer un widget qu'un flow utilise casse ce lien : l'editeur de page previent,
  le flow l'affiche en avertissement (refaire le lien apres avoir selectionne le node).
* **Donnees partagees** : les widgets Fil, Tableau, Cartes, Calendrier et Board lisent une collection de la page
  (creee avec le widget). Chaque artiste ecrit dans son propre fichier (`pages_data/<page>/<collection>/<NOM>.jsonl`,
  dans le projet ou l'equipe), FLUX les fusionne a la lecture : pas de conflit sur un partage ou OneDrive. Les autres
  postes apparaissent en quelques secondes.
* **Flows lies aux donnees** : `PageData` part a chaque nouvel enregistrement (ex. un message > Notify),
  `PageDataRead` / `PageDataWrite` lisent et ecrivent (ex. rappels du calendrier chaque matin).

| Portee | Dossier des pages |
|---|---|
| Modeles | dans FLUX (`backend/flux_flows/shipped/pages/`) |
| Equipe | `<FLUX_ROOT>/CONFIG/extensions/pages/` |
| Projet | `<projet>/_flux_setup/pages/` |

Une page enregistree garde ses 20 versions precedentes dans `pages/_history/` ; deux TD qui enregistrent la meme page
en meme temps : le second voit "page modifiee par ...".
