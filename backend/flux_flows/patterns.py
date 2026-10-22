# patterns.py — Houdini style patterns of the Flows (01_ARCHITECTURE §11, 00_LOGIQUE n°12).
#
#   pattern := word { space word }      word := [ "^" | "!" ] glob   (^ or ! = exclusion)
#   glob    := ( char | "*" | "**" | "?" | "[" set "]" | "/" )+
#
# "*" = 0 or more chars except "/", "**" crosses "/", "?" = one char except "/",
# "[abc]" "[a-z]" "[!abc]". No escaping in V1 ("* ? [" are forbidden in Windows names).
# Case insensitive unless case_sensitive. A word without "/" matches the basename,
# with "/" the whole relative path (in "/", "\" is normalised).
# Words are evaluated left to right on a set S: inclusive = S += matches, exclusive
# = S -= matches; when the first word is exclusive, S starts from everything.
# An empty pattern keeps nothing. Bad syntax raises PatternError (E_PARAM_INVALID).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Pattern as RePattern

ERROR_CODE = "E_PARAM_INVALID"


class PatternError(ValueError):
    """The pattern text is malformed. ``message`` is shown to the artist (French)."""

    code = ERROR_CODE

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Word:
    text: str
    exclude: bool
    on_path: bool          # the glob holds a "/": match the whole path, else the basename
    regex: RePattern[str]

    def matches(self, name: str) -> bool:
        target = _normalise(name)
        if not self.on_path:
            target = target.rsplit("/", 1)[-1]
        return self.regex.fullmatch(target) is not None


def _normalise(name: str) -> str:
    return str(name).replace("\\", "/")


def _glob_to_regex(glob: str) -> str:
    out: List[str] = []
    i, n = 0, len(glob)
    while i < n:
        c = glob[i]
        if c == "*":
            if i + 1 < n and glob[i + 1] == "*":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            end = glob.find("]", i + 1)
            # No escaping in V1: "[]" and "[!]" are refused, not read as shell globs do.
            if end == -1:
                raise PatternError(f"Crochet non ferme dans `{glob}`.")
            body = glob[i + 1:end]
            negate = body.startswith("!")
            if negate:
                body = body[1:]
            if not body:
                raise PatternError(f"Ensemble vide `[]` dans `{glob}`.")
            if "/" in body:
                raise PatternError(f"Un ensemble `[...]` ne peut pas contenir `/` (`{glob}`).")
            chars = "".join("\\" + ch if ch in "\\^[]" else ch for ch in body)
            out.append("[" + ("^/" if negate else "") + chars + "]")
            i = end
        elif c == "]":
            raise PatternError(f"Crochet `]` sans `[` dans `{glob}`.")
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def compile_pattern(text: str, case_sensitive: bool = False) -> List[Word]:
    """Parse ``text`` into words. Raises PatternError on bad syntax."""
    flags = 0 if case_sensitive else re.IGNORECASE
    words: List[Word] = []
    for raw in str(text or "").split():
        exclude = raw[0] in "^!"
        glob = raw[1:] if exclude else raw
        if not glob:
            raise PatternError(f"`{raw}` seul ne designe rien : ecris par exemple `{raw}*_tmp*`.")
        if glob[0] in "^!":
            raise PatternError(f"Double exclusion `{raw}`.")
        try:
            regex = re.compile(_glob_to_regex(glob), flags)
        except re.error as exc:  # e.g. a reversed range "[z-a]"
            raise PatternError(f"Ensemble invalide dans `{raw}` : {exc.msg}.") from exc
        words.append(Word(raw, exclude, "/" in glob, regex))
    return words


def check_pattern(text: str) -> Optional[str]:
    """None when ``text`` is a valid pattern, else the French message (validator)."""
    try:
        compile_pattern(text)
    except PatternError as exc:
        return exc.message
    return None


def filter_names(text: str, names: Iterable[str], case_sensitive: bool = False) -> List[str]:
    """Names kept by the pattern, in input order (duplicates kept as given)."""
    words = compile_pattern(text, case_sensitive)
    items = list(names)
    if not words:
        return []
    kept = [words[0].exclude] * len(items)
    for word in words:
        for idx, name in enumerate(items):
            if kept[idx] == (not word.exclude):
                continue  # already in the state this word would put it in
            if word.matches(name):
                kept[idx] = not word.exclude
    return [name for name, keep in zip(items, kept) if keep]


def matches(text: str, name: str, case_sensitive: bool = False) -> bool:
    return bool(filter_names(text, [name], case_sensitive))
