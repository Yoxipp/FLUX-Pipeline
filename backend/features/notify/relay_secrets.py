# relay_secrets.py - the relay secret (Discord webhook URL).
#
# They sit in the shared folder (2026-10-30, readable by the team that has access),
# so they are masked in every API answer and log line, and regenerable. Not named
# secrets.py so it never shadows the stdlib module.

from __future__ import annotations

MASK = "****"


def mask(value: str | None) -> str:
    """'****' + the last 4 characters, '' when unset."""
    value = str(value or "")
    if not value:
        return ""
    return MASK + value[-4:] if len(value) > 8 else MASK


def is_masked(value: str | None) -> bool:
    """True when the front sent back the masked value (= keep the stored secret)."""
    return str(value or "").startswith(MASK)


def redact(text: str, *values: str | None) -> str:
    """*text* with every secret in *values* replaced by its mask (for log lines)."""
    out = str(text)
    for value in values:
        if value:
            out = out.replace(str(value), mask(value))
    return out
