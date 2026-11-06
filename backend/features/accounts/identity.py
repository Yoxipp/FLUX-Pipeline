# identity.py - artist identifier from first + last name, and the display profile.
#
# A new artist gets FIRSTNAME_<initials of the last name>, upper case, without accents
# (ADR 0079, 2026-10-30): one letter per word of the last name (Fresne-Roux -> FR,
# Colin -> C). Taken = the shortest free prefix of the last name (ADAM_CO,
# ADAM_COM... ADR 0065), then the full last name with _1, _2... Existing artists
# keep their identifier. First / last name live in User.json for display only.

from __future__ import annotations

import re
import unicodedata

from utils import user_utils

FIRST_NAME_KEY = "first_name"
LAST_NAME_KEY = "last_name"
MAX_NAME_LENGTH = 60

# Letters NFKD does not decompose into a base letter + accent.
_SPECIAL_LETTERS = str.maketrans({
    "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ø": "o", "Ø": "O",
    "ß": "ss", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L",
})
_NOT_ID_CHAR = re.compile(r"[^A-Z0-9]")
_WORD_SEPARATORS = re.compile(r"[\s\-'’_.]+")


def ascii_upper(text: str) -> str:
    """Upper case without accents, A-Z and 0-9 only ("Élodie-Anne" -> "ELODIEANNE")."""
    decomposed = unicodedata.normalize("NFKD", (text or "").translate(_SPECIAL_LETTERS))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NOT_ID_CHAR.sub("", plain.upper())


def make_user_id(first_name: str, last_name: str, taken: set[str] | list[str]) -> str:
    """Return the first free identifier for *first_name* *last_name*.

    *taken* holds every name already used: current artists and retired names
    (aliases), so a new artist never inherits someone else's history.
    Raises ValueError when a part has no usable letter or digit.
    """
    first = ascii_upper(first_name)
    last = ascii_upper(last_name)
    if not first or not last:
        raise ValueError("Prénom et nom requis (lettres ou chiffres).")
    used = {str(t).strip().upper() for t in taken}
    words = [w for w in (ascii_upper(part) for part in _WORD_SEPARATORS.split(last_name or "")) if w]
    initials = "".join(w[0] for w in words)
    for suffix in [initials] + [last[:length] for length in range(1, len(last) + 1)]:
        candidate = f"{first}_{suffix}"
        if candidate not in used:
            return candidate
    base = f"{first}_{last}"
    index = 1
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"


def id_for_rename(first_name: str, last_name: str, current: str, taken: set[str] | list[str]) -> str:
    """Identifier artist *current* gets when renamed to *first_name* *last_name*.

    *current* and the old names that point to it do not block (the same person keeps
    ADAM_FR, or takes an old name of their own back). No last name = the first name
    alone (artists who never gave one, 2026-10-30), _1, _2... when taken.
    """
    from features.accounts import aliases

    cur = str(current or "").strip().upper()
    table = aliases.load_aliases()
    used = {str(t).strip().upper() for t in taken}
    used -= {cur} | {old for old, new in table.items() if new == cur}
    if (last_name or "").strip():
        return make_user_id(first_name, last_name, used)
    first = ascii_upper(first_name)
    if not first:
        raise ValueError("Prénom requis (lettres ou chiffres).")
    if first not in used:
        return first
    index = 1
    while f"{first}_{index}" in used:
        index += 1
    return f"{first}_{index}"


def clean_display_name(text: object) -> str:
    """Trimmed display name (accents kept), bounded length."""
    return " ".join(str(text or "").split())[:MAX_NAME_LENGTH]


def read_profile(user: str) -> dict:
    """Display profile of *user*: identifier, first / last name, password set or not."""
    from features.accounts import passwords

    data = user_utils.read_user_data(user)
    return {
        "id": user,
        FIRST_NAME_KEY: str(data.get(FIRST_NAME_KEY) or ""),
        LAST_NAME_KEY: str(data.get(LAST_NAME_KEY) or ""),
        "has_password": passwords.record_in(data) is not None,
    }


def write_profile(user: str, first_name: object, last_name: object) -> dict:
    """Store the display first / last name of *user* (empty strings clear them)."""
    data = user_utils.read_user_data(user)
    data[FIRST_NAME_KEY] = clean_display_name(first_name)
    data[LAST_NAME_KEY] = clean_display_name(last_name)
    if not user_utils.write_user_data(user, data):
        raise OSError(f"cannot write user settings for '{user}'")
    return read_profile(user)
