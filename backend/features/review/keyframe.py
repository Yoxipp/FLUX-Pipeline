# features/review/keyframe.py — open pipeline videos in Keyframe Pro (retake 09).
#
# Two ways in, checked on a real Keyframe Pro install (2026-10-08):
#
#   * External API (licensed Keyframe Pro only): Keyframe Pro listens on
#     127.0.0.1:18181. Each message is a 10-character, right-aligned length header
#     followed by a JSON object {"cmd": ..., args}; the reply uses the same framing
#     and carries {"success", "msg", ...}. "initialize" must come first. In demo
#     mode the server answers but refuses with "Keyframe Pro is not licensed".
#     With the API, FLUX builds a project: one timeline with the asked videos in
#     order (the auto edit of the Production Timeline), the other videos of the
#     same folders imported beside it, every source named after its shot / task /
#     version.
#   * Command line (any edition, demo included): `KeyframePro.exe <file>` opens
#     that one file. Several files on one command line were not verified, so the
#     fallback opens the first video only and says so.
#
# Nothing is copied: Keyframe reads the files where the pipeline wrote them.
# Opening never publishes anything.

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

from core import config
from core.logger import get_logger

log = get_logger(__name__)

API_PORT = 18181
API_VERSION = "1.14.1"
HEADER_SIZE = 10
CONFIG_KEY = "keyframe"            # config.json dcc_paths entry, optional override

# What Keyframe Pro decodes (FFmpeg based). Anything else is reported, not sent.
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mpg", ".mpeg", ".mxf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".dpx", ".tga", ".bmp"}
SUPPORTED_EXTS = VIDEO_EXTS | IMAGE_EXTS

_EXE_NAMES = ("KeyframePro.exe", "KeyframeMPX.exe", "KeyframeMP.exe")


class KeyframeError(RuntimeError):
    """A failure the UI shows as is (code = machine readable reason)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ── executable ───────────────────────────────────────────────────────────────

def _flavor(exe: Path) -> str:
    return "pro" if "pro" in exe.name.lower() else "mp"


def find_executable() -> Path | None:
    """The Keyframe executable: config override, then the usual install folders."""
    configured = config.get_dcc_exe(CONFIG_KEY)
    if configured and Path(configured).is_file():
        return Path(configured)
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.environ.get("LOCALAPPDATA", "")]
    for root in filter(None, roots):
        base = Path(root)
        if not base.is_dir():
            continue
        for folder in sorted(base.glob("Keyframe*"), reverse=True):
            for name in _EXE_NAMES:
                for cand in (folder / "bin" / name, folder / name):
                    if cand.is_file():
                        return cand
    return None


# ── wire protocol ────────────────────────────────────────────────────────────

class _Client:
    """Minimal client for the Keyframe Pro external API (see the header)."""

    def __init__(self, port: int | None = None, timeout: float = 5.0):
        self.port = port or API_PORT
        self.timeout = timeout
        self.sock: socket.socket | None = None

    def connect(self) -> bool:
        try:
            self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)
            return True
        except OSError:
            self.sock = None
            return False

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _read(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Keyframe Pro closed the connection")
            buf += chunk
        return buf

    def send(self, cmd: dict) -> dict:
        body = json.dumps(cmd).encode("utf-8")
        self.sock.sendall(f"{len(body):{HEADER_SIZE}d}".encode("ascii") + body)
        size = int(self._read(HEADER_SIZE).decode("ascii").strip())
        reply = json.loads(self._read(size).decode("utf-8"))
        return reply if isinstance(reply, dict) else {"success": False, "msg": "invalid reply"}

    def call(self, cmd: str, **args) -> dict:
        reply = self.send({"cmd": cmd, **args})
        if not reply.get("success"):
            raise KeyframeError("api_error", f"Keyframe Pro : {cmd} refusé ({reply.get('msg', '?')})")
        return reply


def _initialize(client: _Client) -> str:
    """'ready', 'not_licensed' or 'error' (message logged)."""
    try:
        reply = client.send({"cmd": "initialize", "api_version": API_VERSION})
    except (OSError, ValueError, ConnectionError) as exc:
        log.warning("Keyframe initialize failed: %s", exc)
        return "error"
    if reply.get("success") and reply.get("result") == 0:
        return "ready"
    msg = str(reply.get("msg", ""))
    log.info("Keyframe initialize refused: %s", msg)
    return "not_licensed" if "licens" in msg.lower() else "error"


def _port_open(port: int | None = None) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port or API_PORT), timeout=0.4):
            return True
    except OSError:
        return False


def status() -> dict:
    """What this machine offers: installed exe and the state of the external API."""
    exe = find_executable()
    api = "not_running"
    if _port_open():
        client = _Client(timeout=3)
        api = _initialize(client) if client.connect() else "error"
        client.close()
    return {
        "installed": exe is not None,
        "exe": str(exe) if exe else "",
        "flavor": _flavor(exe) if exe else "",
        "api": api,
    }


# ── media selection ──────────────────────────────────────────────────────────

def supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTS


def folder_videos(folder: Path) -> list[Path]:
    """Other videos of a folder, oldest version first.

    In a FLUX /ref zone LAST.* is a copy of the newest vNNN: it is skipped when
    versions exist so the same take is not listed twice.
    """
    if not folder.is_dir():
        return []
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXTS]
    has_versions = any(f.stem.lower().startswith("v") and f.stem[1:].isdigit() for f in files)
    if has_versions:
        files = [f for f in files if f.stem.upper() != "LAST"]
    return sorted(files, key=lambda f: f.name.lower())


def split_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separate openable items from the ones to report (missing / unsupported)."""
    ok: list[dict] = []
    skipped: list[dict] = []
    for item in items:
        path = Path(str(item.get("path") or ""))
        if not str(path) or not path.is_file():
            skipped.append({**item, "reason": "introuvable"})
        elif not supported(path):
            skipped.append({**item, "reason": f"format non supporté ({path.suffix or 'sans extension'})"})
        else:
            ok.append({**item, "path": str(path)})
    return ok, skipped


# ── open ─────────────────────────────────────────────────────────────────────

def _launch(exe: Path, file: str | None = None) -> None:
    args = [str(exe)] + ([file] if file else [])
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(args, cwd=str(exe.parent), creationflags=flags, close_fds=True)  # noqa: S603


def _wait_port(seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if _port_open():
            return True
        time.sleep(0.3)
    return False


def _build_project(client: _Client, title: str, items: list[dict], siblings: list[Path]) -> dict:
    client.call("new_project", empty=True)
    timeline = client.call("add_timeline", name=title, parent_id="")["timeline"]
    for item in items:
        src = client.call("import_file", file_path=item["path"], name=item.get("label") or "",
                          range_start=-1, range_end=-1, parent_id="")["source"]
        client.call("insert_element_in_timeline", source_id=src["id"], timeline_id=timeline["id"], index=-1)
    extra = 0
    if siblings:
        folder = client.call("add_folder", name="Même dossier (FLUX)", parent_id="")["folder"]
        for path in siblings:
            try:
                client.call("import_file", file_path=str(path), name="", range_start=-1,
                            range_end=-1, parent_id=folder["id"])
                extra += 1
            except KeyframeError as exc:
                log.warning("Keyframe sibling import failed %s: %s", path, exc)
    client.call("set_active_in_viewer", id=timeline["id"], index=0)
    client.call("set_viewer_layout", layout="single")
    return {"timeline": timeline.get("name", title), "siblings": extra}


def open_media(items: list[dict], title: str = "FLUX", with_siblings: bool = True,
               launch_wait: float = 20.0) -> dict:
    """Open *items* ([{path, label}], in order) in Keyframe.

    Returns {mode: 'api' | 'cli', opened, skipped, siblings, message}. Raises
    KeyframeError('not_installed' | 'nothing_to_open' | 'launch_failed' | ...).
    """
    ok, skipped = split_items(items)
    for s in skipped:
        log.info("Keyframe skip %s: %s", s.get("path"), s["reason"])
    if not ok:
        raise KeyframeError("nothing_to_open", "Aucune vidéo lisible à ouvrir"
                            + (f" ({skipped[0]['reason']})" if skipped else ""))
    exe = find_executable()

    siblings: list[Path] = []
    if with_siblings:
        asked = {Path(i["path"]).resolve() for i in ok}
        seen: set[Path] = set()
        for folder in dict.fromkeys(Path(i["path"]).parent for i in ok):
            for f in folder_videos(folder):
                r = f.resolve()
                if r not in asked and r not in seen:
                    seen.add(r)
                    siblings.append(f)

    launched_with_file = False
    if not _port_open():
        if exe is None:
            raise KeyframeError("not_installed", "Keyframe Pro n'est pas installé sur ce poste")
        try:
            # The first file on the command line: if the API turns out to be
            # unavailable (demo mode), this is already the fallback.
            _launch(exe, ok[0]["path"])
            launched_with_file = True
        except OSError as exc:
            raise KeyframeError("launch_failed", f"Lancement de Keyframe impossible : {exc}")
        _wait_port(launch_wait)

    api = "not_running"
    if _port_open():
        client = _Client()
        if client.connect():
            try:
                api = _initialize(client)
                if api == "ready":
                    built = _build_project(client, title, ok, siblings)
                    log.info("Keyframe API: opened %d item(s) + %d sibling(s) in '%s': %s",
                             len(ok), built["siblings"], title, [i["path"] for i in ok])
                    return {"mode": "api", "opened": ok, "skipped": skipped,
                            "siblings": built["siblings"], "message": ""}
            except (OSError, ValueError, ConnectionError) as exc:
                log.warning("Keyframe API session failed: %s", exc)
                api = "error"
            finally:
                client.close()

    # Fallback: one file on the command line.
    if exe is None:
        raise KeyframeError("not_installed", "Keyframe Pro n'est pas installé sur ce poste")
    if not launched_with_file:
        try:
            _launch(exe, ok[0]["path"])
        except OSError as exc:
            raise KeyframeError("launch_failed", f"Lancement de Keyframe impossible : {exc}")
    reason = ("API externe désactivée (Keyframe Pro sans licence, mode démo)" if api == "not_licensed"
              else "API externe de Keyframe injoignable")
    message = reason + (" : seule la première vidéo est ouverte" if len(ok) > 1 or siblings else "")
    log.info("Keyframe CLI fallback (%s): %s", api, ok[0]["path"])
    return {"mode": "cli", "opened": ok[:1], "skipped": skipped, "siblings": 0,
            "api": api, "message": message}
