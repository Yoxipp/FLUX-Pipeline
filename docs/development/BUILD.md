# Build et dev - FLUX

> Deplace depuis `old/docs/Build_Pipeline.md` et corrige le 2026-09-16 (cible NSIS, sortie `INSTALLEURS/`,
> jeton API S1, installeur Python supprime). Les chemins sensibles au build sont listes dans `STRUCTURE.md`.

## Lancer en dev

* Double-clic `FLUX_DEV.bat` (fait `npm install` la premiere fois, puis `npm run dev`).
* `npm run dev` = `tsc -p tsconfig.electron.json` puis Vite (5173) + Electron. Electron spawn `python backend/main.py`
  (Python du PATH, 3.13 chez the maintainer) ; si un backend tourne deja sur `127.0.0.1:8765`, il est reutilise.
* Backend seul : `npm run dev:backend` (= `python backend/main.py`). Attention : un backend lance a la main garde
  l'ancien code tant qu'il n'est pas tue.

## Lancer un build

### Prerequis

* Node.js + npm. Dependances de preference via `npm ci` (strictement `package-lock.json`). `BUILD_INSTALLER.bat`
  fait `npm install` seulement si `node_modules/` manque.
* Python + dependances `backend/requirements.txt` + PyInstaller **dans le meme interpreteur** : le script utilise
  `python -m PyInstaller` (voir erreur "backend sans uvicorn" plus bas).

### Commande

* Double-clic `BUILD_INSTALLER.bat`, ou :

```powershell
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
npm run build
```

Sortie : `INSTALLEURS/FLUX-Setup-<version>.exe` (installeur NSIS assiste, par utilisateur, sans admin).

Diffusion a l'equipe : copier ce setup dans `<FLUX_ROOT>/FLUX_UPDATE/` (sans le renommer). Au lancement suivant, chaque FLUX installe plus ancien propose la mise a jour (`app/electron/updater.ts`).

### Version (x.x.xxx)

`npm run build` lance `scripts/build.cjs`, qui incremente la version avant de builder :

* chaque build : dernier nombre +1 (`0.1.011` -> `0.1.012`) ;
* question "Incrementer une version mineure ?" (Entree = N) : `x.mineure+1.000` ;
* question "Incrementer une version majeure ?" (Entree = N) : `majeure+1.0.000` (prioritaire sur mineure).

Flags sans question : `node scripts/build.cjs --minor | --major | --no-prompt`.
Source de verite : `package.json` `fluxVersion` (affichage). `version` reste un semver valide (`0.1.11`) car
electron-builder refuse les zeros en tete. Le script reecrit aussi `backend/core/constants.py` `APP_VERSION`
et `scripts/flux_version.nsh` (inclus par `installer.nsh`, cle registre `FluxVersion`). Si le build echoue,
ces fichiers sont remis a la version precedente. Committer ces 3 fichiers apres un build publie.

### Etapes individuelles (debug)

```powershell
npm run build:frontend   # Vite -> dist/
npm run build:backend    # python -m PyInstaller scripts/backend.spec --distpath backend/dist -> backend/dist/flux_backend/
npm run build:electron   # tsc -> dist-electron/
npx electron-builder --config scripts/electron-builder.yml         # -> INSTALLEURS/ (sans bump de version, nom en semver)
npx electron-builder --config scripts/electron-builder.yml --dir   # binaire sans installeur -> INSTALLEURS/win-unpacked/FLUX.exe
```

## Ce que fait chaque etape

### 1. `build:frontend` (Vite)

Compile `app/src/` en bundle statique `dist/`. `base: './'` dans `vite.config.ts` est critique : Electron charge
`index.html` en `file://`. Vite vide `dist/` a chaque build : le backend doit sortir dans `backend/dist/`.

### 2. `build:backend` (PyInstaller, onedir, sans UPX)

`scripts/backend.spec` : entree `backend/main.py`, `datas=[("resources", "resources")]`, `collect_submodules`
uvicorn/fastapi/pydantic (imports dynamiques), `collect_all("pxr")` (usd-core importe en lazy), exclut PySide6/PyQt5/tkinter.
`app_datas` liste les fichiers non Python lus a cote du code (`Path(__file__)`) : YAML `flux_actions/config/*.yml`,
`schema.json` des recettes USD, sources des plugins DCC copies dans les logiciels. Tout nouveau fichier de ce type
doit y etre ajoute (sinon FileNotFoundError -> HTTP 500 en build seulement ; test `tests/system/test_frozen_bundle.py`).
En mode frozen, `shelf_core.py` retrouve `resources/` via `sys._MEIPASS` ; `config.json` vit dans `%APPDATA%/FluxPipeline/`.

### 3. `build:electron` (tsc)

`app/electron/*.ts` -> `dist-electron/` (`main.js`, `preload.js`, `python_bridge.js`).

### 4. `electron-builder`

| Source | Destination |
|---|---|
| `dist/**`, `dist-electron/**`, `scripts/icon.ico`, `scripts/icon.png` | `resources/app.asar` |
| `backend/dist/flux_backend/**` | `resources/backend/` (`extraResources`) |

Cible `nsis` x64, `oneClick: false`, `perMachine: false`, hooks `scripts/installer.nsh` (detection MAJ vs installation neuve).

## Specificites

* `signAndEditExecutable: false` : sans Developer Mode, l'extraction de `winCodeSign` echoue (symlinks). Pour une release signee : certificat + retirer la ligne.
* `CSC_IDENTITY_AUTO_DISCOVERY=false` : evite la recherche de certificat dans le store Windows.
* Toutes les deps UI sont en `devDependencies` : Vite les bundle ; sinon electron-builder embarquerait `node_modules/`.
* En prod, `python_bridge.ts` spawn `process.resourcesPath/backend/flux_backend.exe` avec `FLUX_PORT=8765`, puis lit le
  jeton API sur `GET /auth/token` (S1) et le passe au renderer.

## Erreurs connues

### Backend packagé qui ne demarre pas (`ModuleNotFoundError: uvicorn`), pris pour un blocage antivirus

**Cause :** PyInstaller lance depuis un autre Python que celui qui a les dependances. **Fix :** `build:backend` utilise
`python -m PyInstaller` ; verifier `python -c "import uvicorn, fastapi"` avec le meme `python`.

### `Cannot find module '@tootallnate/once'`

**Cause :** residu d'une ancienne version d'electron-builder dans `node_modules/`. **Fix :**

```powershell
Remove-Item -Recurse -Force node_modules
npm ci
```

### UI visible mais pages vides, aucune requete

**Cause historique :** `BrowserRouter` avec `loadFile()` (pathname = chemin disque). **Deja corrige :** `HashRouter` (`app/src/App.tsx`).

### UI visible mais backend injoignable

* CORS : en `file://`, Chromium envoie `Origin: null`. `main.py` autorise `"null"` (garde-fou : le jeton S1 est exige sur toutes les routes).
* Jeton : si le renderer n'a pas le jeton (backend relance avec un nouveau jeton), les requetes sont refusees ; `python_bridge.ts` le relit a chaque transition.
* Debug : `Ctrl+Shift+I` (DevTools). Logs Python : `%APPDATA%\Flux\logs\flux_YYYY-MM-DD.log`.

### `Access is denied` sur `app.asar`

**Cause :** Windows Defender/antivirus scanne `app.asar` pendant qu'electron-builder le supprime. L'ancienne parade
(sortie dans `C:/Temp/flux-release`) n'est plus en place : la sortie est `INSTALLEURS/` dans le repo. **Fix :** fermer
toute instance de `FLUX.exe`, relancer ; sinon exclusion antivirus sur `INSTALLEURS/`.

```powershell
Stop-Process -Name FLUX -Force -ErrorAction SilentlyContinue
```

### Icone Electron par defaut une fois build

**Cause :** le whitelist `files` excluait `scripts/`, or `main.ts` lit l'icone runtime dans `scripts/icon.*`.
**Corrige :** `scripts/icon.ico` et `scripts/icon.png` sont dans `files`.

**Suite (2026-09-26) :** `FLUX.exe` lui-meme gardait l'icone Electron (raccourci bureau, barre des taches,
Explorateur) : `win.signAndEditExecutable: false` desactive rcedit (il vient du telechargement winCodeSign, en
echec sans certificat). Hook `afterPack: scripts/set_exe_icon.cjs` : remplace le groupe d'icones de l'exe par
`scripts/icon.ico` avec `resedit` (MIT, JS pur, deja dependance d'electron-builder). Log de build :
`[FLUX] exe icon set`. Windows peut garder l'ancienne icone en cache sur un raccourci existant : le recreer.

### Au demarrage, le backend ne se lance pas tant que l'antivirus (Avast) n'a pas valide

**Cause :** `flux_backend.exe` non signe, quarantaine breve au premier lancement. **Corrige cote logiciel :**
`python_bridge.ts` retente le spawn (4 fois, backoff 2 s) puis affiche un message clair. Seule vraie solution :
signer le code, ou exclusion antivirus du dossier d'installation.

### Historique (cible MSI/WiX abandonnee)

`LGHT0094 Icon:FLUXIcon.exe` concernait l'ancienne cible MSI (WiX). La cible est NSIS depuis : ne plus en tenir compte.
