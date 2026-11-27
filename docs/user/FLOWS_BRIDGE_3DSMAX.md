# NON TESTE : 3ds Max indisponible

> Exemple de bridge d'extension (Flows P6c). Rien de ce qui tourne DANS 3ds Max n'a ete lance :
> le dossier de demarrage, le thread principal via Qt et le code d'enregistrement sont a valider
> en live par le mainteneur. Ce qui est teste (contre un faux logiciel) : `bridge.yml`, installation,
> protocole TCP JSON, Instance, ExtRunScript, publish par fichier temporaire.

## 1. Principe

Un logiciel que FLUX ne livre pas s'ajoute **sans recompiler l'exe** :

```
CONFIG/extensions/bridges/max/
  bridge.yml               le manifeste (strict : une cle inconnue est une erreur)
  dcc_side/
    flux_max_bridge.py     le script que 3ds Max lance (copie adaptee de tcp_json_server.py)
  flows/                   optionnel : session.flow.yml, publish.flow.yml (sinon les modeles)
```

* Modeles : `backend/flux_flows/bridges/templates/tcp_json_server.py` (TCP, un objet JSON par
  ligne, 127.0.0.1) et `file_mailbox_server.py` (dossier boite aux lettres, protocole Marvelous,
  pour un Python sans `_socket`). Stdlib seulement, Python 3.7+.
* **Securite** : le script execute le Python que FLUX lui envoie. Il a la meme confiance que les
  nodes Python de l'equipe (00_LOGIQUE §13) et n'ecoute que sur 127.0.0.1.

## 2. bridge.yml

```yaml
soft: max                 # id du logiciel (dossier du meme nom), minuscules
label: 3ds Max
icon: Box
prefix: max               # 2 a 4 lettres, unique : nodes session.max_instance, dcc.max_publish
exe_hints:                # globs, newest first ; %VAR% / ~ developpes
  - "C:/Program Files/Autodesk/3ds Max */3dsmax.exe"
port_range: [7100, 8]     # ne doit chevaucher ni DCC_PORT_RANGES ni une autre extension
transport: tcp_json       # tcp_json | file_mailbox | http
install:
  # A CONFIRMER PAR ADAM : le dossier que 3ds Max execute au demarrage.
  target: "%LOCALAPPDATA%/Autodesk/3dsMax/2026 - 64bit/ENU/scripts/startup"
  files: [flux_max_bridge.py]
```

Plages deja prises : 7001-7008, 7020-7027, 7030-7037, 7040-7047, 7050-7057, 7060-7067,
7070-7077, 7080-7087, 9876-9883, 48884-48891. Un conflit (soft livre, prefixe deja pris ou
reserve, ports qui chevauchent) est affiche dans Flows > Bridges, le bridge est ignore, les
autres chargent.

## 3. dcc_side/flux_max_bridge.py

Copier `tcp_json_server.py` sous ce nom, puis remplacer le bloc `if __name__ == "__main__":` de la
fin par le demarrage cote 3ds Max. pymxs doit tourner sur le thread principal : le thread TCP
pose le travail dans une file, un `QTimer` du thread principal l'execute.

```python
# --- 3ds Max (NON TESTE) -----------------------------------------------------------------
import queue

import pymxs

try:
    from PySide6 import QtCore          # 3ds Max 2025+
except ImportError:
    from PySide2 import QtCore          # 3ds Max 2018-2024

_jobs = queue.Queue()


def _main_thread(fn):
    done = threading.Event()
    _jobs.put((fn, done))
    done.wait(600)


def _pump():
    while True:
        try:
            fn, done = _jobs.get_nowait()
        except queue.Empty:
            return
        try:
            fn()
        finally:
            done.set()


_timer = QtCore.QTimer()
_timer.timeout.connect(_pump)
_timer.start(50)
_bridge = start(_main_thread, {"rt": pymxs.runtime, "pymxs": pymxs}, soft_version="3ds Max")
print("FLUX: bridge 3ds Max sur 127.0.0.1:%d" % _bridge.port)
```

L'installation ecrit `flux_max_bridge.json` a cote (soft, ports) : le script le lit au demarrage.

## 4. Installer

* Flows > Bridges : etat (absent, installe, a jour, conflit), Installer / Desinstaller.
* Parametres > Utilisateur > "Installer tous les bridges" installe aussi les extensions dont
  l'exe est trouve (`exe_hints`).
* Jamais d'ecrasement silencieux : un fichier different que FLUX n'a pas ecrit = conflit ;
  Remplacer fait une sauvegarde `<nom>.flux_backup_<date>`. Desinstaller retire seulement les
  fichiers ecrits par FLUX (recu `.flux_bridge_max.install.json`) et restaure les sauvegardes ;
  un fichier modifie depuis l'installation est garde.

## 5. Nodes et publish

Flows > Bridges > "Creer les nodes" (Team TD, extension de scene `.max`) ecrit dans
`CONFIG/extensions/flows/` :

* `max_instance` = node `3dsMaxInstance` (`session.max_instance`) : se connecte a 3ds Max ouvert,
  sinon le lance (`exe_hints`) et attend le bridge. Live seulement.
* `max_publish` = node `maxPublish` (`dcc.max_publish`) : `ExtRunScript` enregistre une copie
  dans un fichier temporaire `.max`, puis `PublishFile` la publie (vNNN + LAST). Le code
  d'enregistrement est a ecrire dans le node `save` (le modele echoue tant qu'il ne l'est pas) :

```python
rt.saveMaxFile(args["path"], useNewFile=False, quiet=True)
result = args["path"]
```

Les verifications avant publish se placent entre `save` et `publish`.

## 6. Verification live

Sans 3ds Max (possible tout de suite) :
1. `python backend/flux_flows/bridges/templates/tcp_json_server.py` dans un terminal (faux logiciel).
2. `bridge.yml` ci-dessus avec `port_range: [7100, 8]` et un `target` dans un dossier de test ;
   Flows > Bridges : le bridge apparait sans erreur ; Installer puis Desinstaller.
3. Creer les nodes ; flow `3dsMaxInstance (live_connect_only)` > `ExtRunScript` (`result = 1 + 1`) :
   la valeur 2 revient.
4. Un deuxieme bridge avec le meme prefixe ou une plage qui chevauche : erreur affichee.

Avec 3ds Max : dossier de demarrage, script charge au lancement, `ExtRunScript` sur `rt`,
publish d'une scene. Tant que ce n'est pas fait, ce bridge reste **non valide**.
