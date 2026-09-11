# switch.py — routes a publish through the engine, with a legacy escape hatch.
#
# The engine now runs UNDER the Publisher endpoints by default. The legacy logic
# (publish_file, publish_houdini_rop, run_publish_export) stays in the tree as a
# fallback, reachable per DCC through one environment variable, read fresh each
# call so the switch flips without restarting the backend.
#
# FLUX_LEGACY_PUBLISH is a comma-separated list of DCC keys, or "all":
#   ""                -> engine everywhere (default)
#   "houdini"         -> legacy for Houdini only, engine elsewhere
#   "maya,houdini"    -> legacy for Maya and Houdini, engine elsewhere
#   "all"             -> legacy everywhere (full rollback)
#
# YAGNI: no request field, no settings UI. Set the env var only to fall back to
# legacy for a DCC; unset it for the engine everywhere.

from __future__ import annotations

import os

_ENV_VAR = "FLUX_LEGACY_PUBLISH"


def engine_publish_enabled(dcc: str) -> bool:
    """Return True when the engine should handle a publish for this DCC.

    ``dcc`` is a lowercase key: "local", "maya" or "houdini". The engine is the
    default; the env var names the DCCs that must fall back to legacy. It is read
    every call so the switch can flip without restarting the backend.
    """
    raw = os.environ.get(_ENV_VAR, "")
    legacy = {t.strip().lower() for t in raw.split(",") if t.strip()}
    if not legacy:
        return True
    if "all" in legacy:
        return False
    return dcc.strip().lower() not in legacy
