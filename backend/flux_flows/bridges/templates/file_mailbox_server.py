# file_mailbox_server.py - FLUX extension bridge through files (template, Flows P6c).
#
# For a soft whose Python has no network (Marvelous Designer had no _socket). FLUX and
# this script talk through a folder: %TEMP%/<mailbox> (or FLUX_MD_MAILBOX_ROOT/<mailbox>).
#   alive.json   rewritten every second by poll(): {time, pid, version} (FLUX's ping)
#   <id>.req     a request written by FLUX, claimed here (renamed <id>.work)
#   <id>.resp    the answer, written atomically
# Requests: {"cmd": "run", "code": "..."} -> {"ok": true, "result": ...} | {"ok": false, "error"}
# FLUX writes flux_bridge.json next to this file: {"soft", "label", "mailbox"}.
# Call poll() from the soft's own timer / idle callback (its main thread), or run
# serve_forever() in a thread when the soft allows it.
# SECURITY: runs the Python code FLUX sends: same trust as the team's Python nodes.
# Stdlib only, Python 3.7+.

import json
import os
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "flux-extension-mailbox 1"


def load_config():
    cfg = {"soft": "extension", "label": "Extension", "mailbox": "flux_extension_bridge"}
    try:
        with open(os.path.join(HERE, "flux_bridge.json"), encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def mailbox():
    root = os.environ.get("FLUX_MD_MAILBOX_ROOT") or tempfile.gettempdir()
    path = os.path.join(root, load_config()["mailbox"])
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _write_json(path, data):
    tmp = path + ".tmp"
    try:
        text = json.dumps(data)
    except (TypeError, ValueError):
        data = dict(data)
        data["result"] = repr(data.get("result"))
        text = json.dumps(data)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def run_code(code, extra_globals=None):
    ns = {"__name__": "__flux_flows__"}
    ns.update(extra_globals or {})
    try:
        exec(compile(code, "<flux flow>", "exec"), ns)
        return {"ok": True, "result": ns.get("result")}
    except Exception as exc:  # reported to FLUX
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc), "trace": traceback.format_exc()}


_last_beat = [0.0]


def poll(extra_globals=None, soft_version=""):
    """One step: heartbeat (at most once per second) and every pending request."""
    box = mailbox()
    now = time.time()
    if now - _last_beat[0] >= 1.0:
        _write_json(os.path.join(box, "alive.json"), {"time": now, "pid": os.getpid(),
                                                      "version": soft_version or VERSION})
        _last_beat[0] = now
    for name in sorted(os.listdir(box)):
        if not name.endswith(".req"):
            continue
        rid = name[:-4]
        work = os.path.join(box, rid + ".work")
        try:
            os.replace(os.path.join(box, name), work)
        except OSError:
            continue
        try:
            with open(work, encoding="utf-8") as fh:
                request = json.load(fh)
        except (OSError, ValueError) as exc:
            answer = {"ok": False, "error": "requete illisible: %s" % exc}
        else:
            cmd = request.get("cmd") if isinstance(request, dict) else None
            if cmd == "run":
                answer = run_code(str(request.get("code") or ""), extra_globals)
            elif cmd == "ping":
                answer = {"ok": True, "version": soft_version or VERSION}
            else:
                answer = {"ok": False, "error": "commande inconnue: %r" % (cmd,)}
        _write_json(os.path.join(box, rid + ".resp"), answer)
        try:
            os.remove(work)
        except OSError:
            pass


def stop():
    try:
        os.remove(os.path.join(mailbox(), "alive.json"))
    except OSError:
        pass


def serve_forever(extra_globals=None, soft_version="", interval=0.05, should_stop=None):
    try:
        while not (should_stop and should_stop()):
            poll(extra_globals, soft_version)
            time.sleep(interval)
    finally:
        stop()


if __name__ == "__main__":
    # A fake soft from a terminal: python file_mailbox_server.py
    print("FLUX extension mailbox in %s (Ctrl+C to stop)" % mailbox())
    try:
        serve_forever()
    except KeyboardInterrupt:
        pass
