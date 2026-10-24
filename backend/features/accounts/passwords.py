# passwords.py - optional artist password (a safeguard, not a security boundary).
#
# Anyone with write access to the shared USER/ folder can delete the hash, so this
# only stops an artist from picking someone else in the Login list. Stored in
# User.json "password" as salted scrypt (stdlib), never the password itself.
# Nothing in this module logs a password or a hash.

from __future__ import annotations

import hashlib
import hmac
import os

from utils import user_utils

PASSWORD_KEY = "password"
MIN_LENGTH = 4
MAX_LENGTH = 256

_ALGO = "scrypt"
_N, _R, _P = 2 ** 14, 8, 1          # ~16 MB, a few tens of ms per check
_MAX_N, _MAX_R, _MAX_P = 2 ** 15, 16, 4   # bound a hand-edited record
_MAXMEM = 64 * 1024 * 1024
_SALT_BYTES = 16
_KEY_BYTES = 32


def hash_password(password: str) -> dict:
    """Return the salted scrypt record of *password*."""
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P,
                            maxmem=_MAXMEM, dklen=_KEY_BYTES)
    return {"algo": _ALGO, "n": _N, "r": _R, "p": _P, "salt": salt.hex(), "hash": digest.hex()}


def verify_password(password: str, record: object) -> bool:
    """True if *password* matches *record*; False for any malformed record."""
    if not isinstance(record, dict) or record.get("algo") != _ALGO or not isinstance(password, str):
        return False
    try:
        salt = bytes.fromhex(str(record["salt"]))
        expected = bytes.fromhex(str(record["hash"]))
        n, r, p = int(record["n"]), int(record["r"]), int(record["p"])
    except (KeyError, TypeError, ValueError):
        return False
    if not expected or not (1 < n <= _MAX_N and 0 < r <= _MAX_R and 0 < p <= _MAX_P):
        return False
    try:
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                                maxmem=_MAXMEM, dklen=len(expected))
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(digest, expected)


def validate_new_password(password: str) -> None:
    """Raise ValueError when *password* is too short or too long."""
    if len(password) < MIN_LENGTH:
        raise ValueError(f"Mot de passe trop court ({MIN_LENGTH} caractères minimum).")
    if len(password) > MAX_LENGTH:
        raise ValueError("Mot de passe trop long.")


def record_in(user_data: dict) -> dict | None:
    """The password record stored in a User.json blob, or None when there is none."""
    record = user_data.get(PASSWORD_KEY)
    return record if isinstance(record, dict) and record.get("hash") else None


def has_password(user: str) -> bool:
    return record_in(user_utils.read_user_data(user)) is not None


def check_password(user: str, password: str | None) -> bool:
    """True when *user* has no password, or *password* matches it."""
    record = record_in(user_utils.read_user_data(user))
    if record is None:
        return True
    return verify_password(password or "", record)


# ── "Se souvenir sur ce PC" ───────────────────────────────────────────────────
# The per-machine prefs (config, never on the shared drive) keep, per artist, a
# fingerprint of the password record. A new or reset password has a new salt, so
# the fingerprint no longer matches and the password is asked again.
_REMEMBER_KEY = "remembered_users"


def _fingerprint(record: dict) -> str:
    return hashlib.sha256(f"{record.get('salt')}:{record.get('hash')}".encode()).hexdigest()[:32]


def remember_on_this_pc(user: str) -> None:
    from core import config

    record = record_in(user_utils.read_user_data(user))
    remembered = dict(config.get(_REMEMBER_KEY, {}) or {})
    if record is None:
        remembered.pop(user, None)
    else:
        remembered[user] = _fingerprint(record)
    config.set(_REMEMBER_KEY, remembered)


def forget_on_this_pc(user: str) -> None:
    from core import config

    remembered = dict(config.get(_REMEMBER_KEY, {}) or {})
    if remembered.pop(user, None) is not None:
        config.set(_REMEMBER_KEY, remembered)


def is_remembered(user: str) -> bool:
    from core import config

    record = record_in(user_utils.read_user_data(user))
    remembered = config.get(_REMEMBER_KEY, {}) or {}
    return (record is not None and isinstance(remembered, dict)
            and hmac.compare_digest(str(remembered.get(user, "")), _fingerprint(record)))


def can_enter(user: str, password: str | None) -> bool:
    """True when *user* has no password, is remembered on this PC, or *password* matches."""
    return not has_password(user) or is_remembered(user) or check_password(user, password)


def set_password(user: str, password: str | None) -> bool:
    """Set (or remove, when empty / None) the password of *user*. Returns has_password."""
    data = user_utils.read_user_data(user)
    if password:
        validate_new_password(password)
        data[PASSWORD_KEY] = hash_password(password)
    else:
        data.pop(PASSWORD_KEY, None)
    if not user_utils.write_user_data(user, data):
        raise OSError(f"cannot write user settings for '{user}'")
    return bool(password)
