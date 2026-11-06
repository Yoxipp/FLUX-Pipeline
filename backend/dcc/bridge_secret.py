# bridge_secret.py — the per-machine secret that gates code execution on the DCC bridges.
#
# The TCP bridges (Painter, Mari, ZBrush, Designer) listen on 127.0.0.1 without auth. Their
# `run` action executes free Python inside the soft, so it requires this secret (the maintainer
# 2026-10-24). One secret per machine, stable across installs (reinstalling one bridge must
# not break the others): %APPDATA%/FluxPipeline/bridge_secret.txt, created on first use.
# The install of a bridge copies it next to the script (<script>.json, {"secret": ...}),
# where the bridge reads it. It stops web pages and port scanners, not a local program
# that reads the user's files (same level as the X-Flux-Token).
# Delete the file and reinstall the bridges to rotate it.

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

ENV_FILE = "FLUX_BRIDGE_SECRET_FILE"   # tests and custom setups


def secret_path() -> Path:
    override = os.environ.get(ENV_FILE)
    if override:
        return Path(override)
    from core.paths import _frozen_appdata_dir

    return _frozen_appdata_dir() / "bridge_secret.txt"


def get_secret() -> str:
    """The machine secret, created on first use."""
    p = secret_path()
    try:
        text = p.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    value = secrets.token_urlsafe(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value, encoding="utf-8")
    return value


def sidecar_path(script: Path) -> Path:
    return Path(script).with_suffix(".json")


def write_sidecar(script: Path) -> Path:
    """Write <script>.json next to an installed bridge script; returns its path."""
    dest = sidecar_path(script)
    dest.write_text(json.dumps({"secret": get_secret()}), encoding="utf-8")
    return dest


def remove_sidecar(script: Path) -> None:
    try:
        sidecar_path(script).unlink()
    except OSError:
        pass
