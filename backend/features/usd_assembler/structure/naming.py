# naming.py — turn pipeline identities into valid USD names / SdfPaths.
# Pure python, zero pxr: an SdfPath token is [A-Za-z_][A-Za-z0-9_]*.

from __future__ import annotations

import re

_INVALID = re.compile(r"[^A-Za-z0-9_]")
_LEADING_DIGIT = re.compile(r"^[0-9]")


def sanitize_token(name: str) -> str:
    """Return *name* coerced into a legal SdfPath identifier token.

    Invalid characters become '_'; a leading digit is prefixed with '_'. The
    raw identity is preserved as-is when it is already legal (e.g. CHAR_hero).
    """
    if not name:
        raise ValueError("cannot build a token from an empty name")
    token = _INVALID.sub("_", name)
    if _LEADING_DIGIT.match(token):
        token = f"_{token}"
    return token


class PrimNamer:
    """Build prim paths and variant names from pipeline identities.

    Stateless and pure; identities are kept raw (only sanitised to legal tokens)
    so paths round-trip cleanly back to the asset they came from.
    """

    def prim_name(self, entity: str) -> str:
        """Return the leaf prim name for *entity* (a single path token)."""
        return sanitize_token(entity)

    def prim_path(self, entity: str, parent: str = "/") -> str:
        """Return the absolute SdfPath for *entity* under *parent*."""
        leaf = self.prim_name(entity)
        if parent in ("", "/"):
            return f"/{leaf}"
        return f"{parent.rstrip('/')}/{leaf}"

    def default_prim(self, entity: str) -> str:
        """Return the defaultPrim leaf name for a root layer of *entity*."""
        return self.prim_name(entity)

    def variant_name(self, selection: str) -> str:
        """Return a legal variant selection token."""
        return sanitize_token(selection)
