# switch.py — the opt-in toggle that routes a publish through the engine.
#
# Phase 4 wires the engine UNDER the existing Publisher endpoints without
# replacing the legacy logic. Legacy stays the default. One environment
# variable, read fresh each call, flips a given DCC over to the engine runner.
#
# FLUX_ENGINE_PUBLISH is a comma-separated list of DCC keys, or "all":
#   ""                -> legacy everywhere (default)
#   "houdini"         -> engine for Houdini only
#   "maya,houdini"    -> engine for Maya and Houdini
#   "all"             -> engine everywhere
#
# YAGNI: no request field, no settings UI. Set the env var to validate a DCC in
# the real app, unset it to fall straight back to legacy.

from __future__ import annotations

import os

_ENV_VAR = "FLUX_ENGINE_PUBLISH"


def engine_publish_enabled(dcc: str) -> bool:
    """Return True when the engine should handle a publish for this DCC.

    ``dcc`` is a lowercase key: "local", "maya" or "houdini". The env var is
    read every call so the switch can flip without restarting the backend.
    """
    raw = os.environ.get(_ENV_VAR, "")
    tokens = {t.strip().lower() for t in raw.split(",") if t.strip()}
    if not tokens:
        return False
    if "all" in tokens:
        return True
    return dcc.strip().lower() in tokens
