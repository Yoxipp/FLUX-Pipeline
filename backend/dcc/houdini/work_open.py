"""
FLUX Work: open a task's scene from Production (ADR 0090 point 3 + addendum 2026-11-20).

A Houdini already running with the FLUX server gets the opening through ``POST /run``;
the code only schedules it (``hdefereval``) and answers at once, so the artist's dialog
never holds the request. In Houdini:

* the scene is already this work: nothing;
* blank scene (never saved, not modified): the work is loaded;
* otherwise the artist chooses: save the current scene then open (Save FLUX when it is
  a FLUX Work, else a Houdini save), open in a new Houdini (FLUX launches it), or
  cancel. Never a merge, never a load that drops unsaved changes without a choice.

No Houdini answering: FLUX launches one on the scene.
"""

from __future__ import annotations

import os
from typing import Callable

from core.logger import get_logger

log = get_logger(__name__)

# Scene state of an instance, to pick which one gets the opening.
STATE_CODE = '''
result = {"path": hou.hipFile.path(), "new": hou.hipFile.isNewFile(),
          "dirty": hou.hipFile.hasUnsavedChanges()}
'''

_OPEN_CODE = '''
import json, os, urllib.request

_FLUX_PATH = {path!r}

def _flux_port():
    try:
        return int(os.environ.get("FLUX_PORT") or
                   open(os.path.join(os.environ.get("APPDATA",""), "FLUX", "backend_port")).read())
    except Exception:
        return 8765

_FLUX_API = "http://127.0.0.1:%d/dcc/houdini/work" % _flux_port()
_FLUX_LAUNCH_URL = _FLUX_API + "/launch"

def _flux_same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

def _flux_post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={{"Content-Type": "application/json"}}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def _flux_work_nodes():
    out = []
    for cat in (hou.sopNodeTypeCategory(), hou.lopNodeTypeCategory()):
        t = cat.nodeTypes().get("flux_work")
        if t is not None:
            out += list(t.instances())
    return out

def _flux_save_current():
    """Save the open scene before replacing it. False = the opening is cancelled."""
    if not hou.hipFile.hasUnsavedChanges():
        return True
    bound = [n for n in _flux_work_nodes() if n.parm("loaded_task") and n.parm("loaded_task").eval()]
    if bound:
        return bool(bound[0].hdaModule().save(bound[0]))
    if hou.hipFile.isNewFile():
        path = hou.ui.selectFile(title="Sauver la scene courante", file_type=hou.fileType.Hip,
                                 chooser_mode=hou.fileChooserMode.Write)
        if not path:
            return False
        hou.hipFile.save(hou.text.expandString(path))
        return True
    hou.hipFile.save()
    return True

def _flux_release_current():
    """The FLUX Work being replaced frees its task's lock."""
    for n in _flux_work_nodes():
        ref = {{k: n.parm("loaded_" + k).eval() for k in ("project", "seq", "shot", "task")
               if n.parm("loaded_" + k) is not None}}
        if ref.get("task") and n.parm("read_only") is not None and not n.parm("read_only").eval():
            try:
                _flux_post(_FLUX_API + "/unlock", dict(ref, author="", host=__import__("socket").gethostname()))
            except Exception:
                pass

def _flux_open():
    if _flux_same(hou.hipFile.path(), _FLUX_PATH):
        hou.ui.setStatusMessage("FLUX : ce travail est deja ouvert")
        return
    blank = hou.hipFile.isNewFile() and not hou.hipFile.hasUnsavedChanges()
    if not blank:
        what = "modifiee" if hou.hipFile.hasUnsavedChanges() else "ouverte"
        choice = hou.ui.displayMessage(
            "FLUX ouvre le travail :\\n%s\\n\\nLa scene courante (%s) est %s." % (
                _FLUX_PATH, os.path.basename(hou.hipFile.path()), what),
            buttons=("Sauver puis ouvrir", "Nouvelle instance", "Annuler"),
            default_choice=0, close_choice=2, title="FLUX Work")
        if choice == 2:
            return
        if choice == 1:
            try:
                _flux_post(_FLUX_LAUNCH_URL, {{"path": _FLUX_PATH}})
            except Exception as exc:
                hou.ui.displayMessage("FLUX injoignable : %s" % exc, title="FLUX Work")
            return
        if not _flux_save_current():
            hou.ui.setStatusMessage("FLUX : ouverture annulee")
            return
        _flux_release_current()
    hou.hipFile.load(_FLUX_PATH, suppress_save_prompt=True)

try:
    import hdefereval
    hdefereval.executeDeferred(_flux_open)
    result = {{"scheduled": True}}
except ImportError:
    result = {{"scheduled": False, "error": "Houdini sans interface"}}
'''


def build_open_code(path: str) -> str:
    """Code sent to a running Houdini to open *path* (see module docstring)."""
    return _OPEN_CODE.format(path=str(path).replace("\\", "/"))


def pick_instance(states: list[tuple[int, dict]], path: str) -> int | None:
    """Port of the Houdini that gets the opening: the one already on this scene, else a
    blank one, else the first that answered. *states* = [(port, STATE_CODE result)]."""
    def _same(a: str) -> bool:
        return bool(a) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(path))

    answered = [(port, st) for port, st in states if isinstance(st, dict) and "path" in st]
    for rule in (lambda st: _same(st["path"]), lambda st: st.get("new") and not st.get("dirty"),
                 lambda st: True):
        for port, st in answered:
            if rule(st):
                return port
    return None


def open_in_houdini(path: str, *, ports: Callable[[], list[int]] | None = None,
                    client_factory: Callable[[int], object] | None = None,
                    launch: Callable[[str], bool] | None = None) -> dict:
    """Open *path* in a running Houdini (sent through /run) or launch one on it."""
    if ports is None:
        from core.dcc_instances import scan_instances

        ports = lambda: [i["port"] for i in scan_instances("Houdini") if i.get("connected")]
    if client_factory is None:
        from dcc.houdini.client import HoudiniClient

        client_factory = lambda port: HoudiniClient(port=port)
    states = []
    for port in ports():
        resp = client_factory(port).run(STATE_CODE, timeout=5)
        states.append((port, resp.get("result") if resp.get("ok") else None))
    port = pick_instance(states, path)
    if port is not None:
        code = build_open_code(path)
        resp = client_factory(port).run(code, timeout=10)
        if resp.get("ok") and (resp.get("result") or {}).get("scheduled"):
            log.info("Work opening sent to Houdini :%s -> %s", port, path)
            return {"ok": True, "mode": "sent", "port": port, "hip": path}
        log.warning("Houdini :%s refused the work opening: %s", port, resp)
    return launch_work(path, launch=launch)


def launch_work(path: str, *, launch: Callable[[str], bool] | None = None) -> dict:
    """A new Houdini on *path*."""
    if launch is None:
        from features.launcher.launcher_core import launch_dcc

        launch = lambda scene: launch_dcc("houdini", scene)
    ok = bool(launch(path))
    return {"ok": ok, "mode": "launched" if ok else "failed", "port": None, "hip": path}
