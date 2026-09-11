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

# Texture conform (.tx) at publish time. OPT-IN: off by default, exactly like the
# publish engine was before it became the default. It stays off until the maintainer has
# validated the gain (and the colorspace choice) with a Karma control render.
_CONFORM_ENV = "FLUX_CONFORM_TX"
# When conform is on, whether to bake the colorspace of color maps (sRGB->linear)
# into the .tx. This is the point to validate with Karma: some pipelines prefer
# to keep the source space + tag and let the render OCIO convert. Set this env to
# a falsey value ("0"/"off"/"no"/"false") to keep source pixels; default converts.
_CONFORM_COLORCONVERT_ENV = "FLUX_CONFORM_TX_COLORCONVERT"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def conform_tx_enabled() -> bool:
    """Return True when a texture publish should also generate a mipped .tx.

    Opt-in and read fresh each call, so the switch flips without a restart.
    """
    return os.environ.get(_CONFORM_ENV, "").strip().lower() in _TRUE


def conform_tx_colorconvert() -> bool:
    """Return True when color maps should be colorspace-converted in the .tx.

    Defaults to True (the maketx-style workflow); set FLUX_CONFORM_TX_COLORCONVERT
    to a falsey value to keep the source space instead. Only meaningful when
    conform_tx_enabled() is True.
    """
    return os.environ.get(_CONFORM_COLORCONVERT_ENV, "1").strip().lower() not in _FALSE


# USD proxy generation at publish time. OPT-IN, same posture as texture conform:
# off until the maintainer has validated the proxy quality on real assets.
_PROXY_ENV = "FLUX_PROXY_USD"
_PROXY_REDUCTION_ENV = "FLUX_PROXY_REDUCTION"
_DEFAULT_PROXY_REDUCTION = 0.9


def proxy_usd_enabled() -> bool:
    """Return True when a USD asset publish should also author proxy geometry.

    Opt-in and read fresh each call, so the switch flips without a restart.
    """
    return os.environ.get(_PROXY_ENV, "").strip().lower() in _TRUE


def proxy_usd_reduction() -> float:
    """Fraction of triangles removed for publish-time proxies (default 0.9).

    Set FLUX_PROXY_REDUCTION to override; a bad value falls back to the default.
    """
    raw = os.environ.get(_PROXY_REDUCTION_ENV, "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_PROXY_REDUCTION
    return value if 0.0 < value < 1.0 else _DEFAULT_PROXY_REDUCTION


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
