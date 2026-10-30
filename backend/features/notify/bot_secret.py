# bot_secret.py - the Discord bot token, kept on the PC that hosts the bot (ADR 0073).
#
# Never in the shared folder: with the token anyone reads every private message the bot
# sent. Stored in %APPDATA%/FluxPipeline/discord_bot_tokens.json, encrypted with Windows
# DPAPI for the current Windows account (another account or another PC cannot decrypt).
# {project: base64(DPAPI blob)}. Other OS: refused (FLUX targets Windows today).

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

PATH_OVERRIDE: Path | None = None       # tests
_lock = threading.Lock()


class SecretError(RuntimeError):
    pass


def tokens_path() -> Path:
    if PATH_OVERRIDE is not None:
        return PATH_OVERRIDE
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "FluxPipeline" / "discord_bot_tokens.json"


# ── DPAPI (ctypes, stdlib) ────────────────────────────────────────────────────

def _dpapi(data: bytes, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise SecretError("Le bot Discord n'est hebergeable que sous Windows pour l'instant")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))  # 0x1: no UI
    if not ok:
        raise SecretError("Chiffrement Windows (DPAPI) impossible")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(text: str) -> str:
    return base64.b64encode(_dpapi(text.encode("utf-8"), True)).decode("ascii")


def unprotect(value: str) -> str:
    return _dpapi(base64.b64decode(value), False).decode("utf-8")


# ── store ─────────────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        data = json.loads(tokens_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path = tokens_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def save_token(project: str, token: str) -> None:
    with _lock:
        data = _load()
        data[project] = protect(token)
        _save(data)


def load_token(project: str) -> str:
    """The token of *project* on this PC, '' when this PC does not host its bot."""
    value = _load().get(project)
    if not value:
        return ""
    try:
        return unprotect(value)
    except (SecretError, ValueError) as exc:
        log.warning("discord bot token of %s unreadable on this PC: %s", project, exc)
        return ""


def delete_token(project: str) -> None:
    with _lock:
        data = _load()
        if data.pop(project, None) is not None:
            _save(data)


def hosted_projects() -> list[str]:
    return sorted(_load())
