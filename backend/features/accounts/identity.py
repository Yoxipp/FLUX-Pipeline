# identity.py - artist identifier from first + last name, and the display profile.
#
# A new artist gets FIRSTNAME_<start of the last name>, upper case, without accents
# (2026-10-24): the shortest free prefix of the last name (ADAM_C, then
# ADAM_CO, ADAM_COM...), then the full last name with _1, _2... Existing artists
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
    for length in range(1, len(last) + 1):
        candidate = f"{first}_{last[:length]}"
        if candidate not in used:
            return candidate
    base = f"{first}_{last}"
    index = 1
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"


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
