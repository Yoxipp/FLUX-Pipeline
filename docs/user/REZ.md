# FLUX avec Rez

> Statut : `package.py` n'a **pas** été résolu ni construit avec un vrai Rez (non installé).
> Les commandes `rez-*` ci-dessous suivent la doc Rez et restent à vérifier.

## 1. C'est quoi Rez

Rez est un gestionnaire d'environnements, utilisé en studio. Il n'installe rien dans Windows :
il range des **packages** dans un dossier (le *repository*), un sous-dossier par nom et version :

```
<repository>/flux/0.11.1/package.py
<repository>/flux/0.11.1/app/FLUX.exe ...
```

Chaque `package.py` dit : son nom, sa version, ce dont il a besoin (`requires`) et ce qu'il change
dans l'environnement (`commands()`).

## 2. Résolution et environnement

`rez-env flux` fait trois choses :

1. **Résoudre** : choisir une version de `flux` et de tout ce qu'il demande, sans conflit. Sans numéro,
   la plus récente est prise. FLUX ne verrouille aucune version.
2. **Construire l'environnement** : exécuter le `commands()` de chaque package retenu (PATH, variables).
3. **Ouvrir un shell** avec cet environnement. En le fermant, tout disparaît ; la machine n'est pas modifiée.

On peut combiner : `rez-env flux maya-2025` (si le studio a un package `maya`). Sans ouvrir de shell :

```powershell
rez-env flux -- flux
```

## 3. Construire et installer le package FLUX

Le package contient l'application **déjà construite** (même contenu que l'installeur, sans NSIS) :
il n'y a besoin ni de Python ni de Node sur les postes qui l'utilisent.

1. Construire l'application : `BUILD_INSTALLER.bat`. Il doit rester le dossier
   `INSTALLEURS/win-unpacked/` (contenant `FLUX.exe`).
2. Depuis la racine du repo, avec Rez installé et `python` accessible :

```powershell
rez-build --install
```

Le package va dans le repository local de Rez (`~/packages` par défaut). Pour toute l'équipe :
`rez-release`, ou `rez-build --install --prefix <repository partagé>`.
`rez-build` crée un dossier `build/` dans le repo : ne pas le committer.

3. Vérifier puis lancer :

```powershell
rez-env flux -- flux
```

La version du package est celle de `package.json` (`version`).

## 4. Variables d'environnement

Toutes sont optionnelles. **Non définie ou vide = comportement habituel.** Elles sont lues au
démarrage du backend.

| Variable | Effet | Défaut |
|---|---|---|
| `FLUX_USER_DIR` | Dossier de `config.json`, `prefs.json`, `bridge_secret.txt` (dev et app installée). | App installée : `%APPDATA%/FluxPipeline`. Dev : racine du repo. |
| `FLUX_BRIDGE_SECRET_FILE` | Fichier du secret des bridges (existait déjà). | `<dossier ci-dessus>/bridge_secret.txt` |
| `FLUX_PORT` | Port du backend (existait déjà). Voir limites. | `8765` |
| `FLUX_MAYA_EXE` | Exécutable Maya. | recherche automatique |
| `FLUX_HOUDINI_EXE`, `FLUX_NUKE_EXE`, `FLUX_MARI_EXE`, `FLUX_ZBRUSH_EXE`, `FLUX_MARVELOUS_EXE`, `FLUX_PHOTOSHOP_EXE`, `FLUX_UNREAL_EXE`, `FLUX_SUBSTANCE_PAINTER_EXE`, `FLUX_SUBSTANCE_DESIGNER_EXE` | Exécutable du logiciel : remplace les chemins de recherche. | recherche automatique |
| `FLUX_MAYA_PORT` | Premier port de la plage Maya (8 ports). | `7001` |
| `FLUX_SUBSTANCE_PORT` | Port Painter. | `7030` |
| `FLUX_DESIGNER_PORT` | Port Designer. | `7040` |
| `FLUX_MARI_PORT` | Port Mari. | `7070` |

Priorité pour un exécutable : chemin choisi dans les réglages FLUX, puis la variable, puis la
détection automatique (registre Windows, launcher Epic, dossiers par défaut). Une variable qui
désigne un fichier absent est signalée une fois dans le log et ignorée. Un chemin venant de la
variable n'est pas enregistré dans les réglages.

Les variables de port doivent être vues **à la fois** par FLUX et par le logiciel : lancer les deux
depuis le même environnement, et réinstaller le bridge Maya après un changement de port.

Pour les imposer à toute l'équipe, décommenter les lignes dans `commands()` de `package.py`.

## 5. Limites connues

* **Port du backend** : l'interface Electron utilise `8765` en dur. `FLUX_PORT` ne sert qu'au backend
  lancé seul.
* **Ports Houdini, ZBrush, Nuke, Unreal, Marvelous, Photoshop** : pas de variable côté FLUX.
* **Hors `FLUX_USER_DIR`** : les logs (`%APPDATA%/Flux/logs`), le fichier `%APPDATA%/FLUX/backend_port`
  et les données propres à Electron restent dans `%APPDATA%`.
* **Mise à jour automatique** : l'interface lit `config.json` dans `%APPDATA%/FluxPipeline` uniquement.
  Avec `FLUX_USER_DIR`, elle ne propose plus d'installeur depuis `FLUX_UPDATE`. Sans, elle peut en
  proposer un alors que Rez gère les versions.
* **Plugins DCC** : certains bridges installés pointent vers des fichiers dans le dossier de
  l'application. Sous Rez ce dossier change à chaque version : réinstaller les bridges après une mise à jour.
* **Installation en lecture seule** : prévue pour l'app construite (ses fichiers utilisateur sont hors
  du dossier), à vérifier sur un vrai partage.
