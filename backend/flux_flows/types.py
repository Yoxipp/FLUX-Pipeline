# types.py — port types of the Flows and whether a link between two of them holds
# (01_ARCHITECTURE §3, ADR 0058, 5).
#
# can_connect never refuses: it says ok, implicit (a conversion happens, marked on
# the link) or incompatible (the link is kept, the validation reports it with the
# reason and, when one exists, a one-click fix). The editor mirrors this in TS.

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

SCALARS = ("exec", "any", "bool", "int", "float", "str", "path", "dir", "dict", "publish", "dcc_node", "pattern")
_LIST_RE = re.compile(r"^list\[(.+)\]$")
_SESSION_RE = re.compile(r"^session\[([a-z*][a-z0-9_]*|\*)\]$")

# Direct implicit conversions; the closure (dir -> path -> str) is transitive.
_IMPLICIT: Dict[str, Tuple[str, ...]] = {
    "int": ("float",),
    "str": ("any",),
    "path": ("str",),
    "dir": ("path", "str"),
    "dict": ("any",),
    "publish": ("any",),
    "dcc_node": ("str",),
    "pattern": ("str",),
}

# (source, target) -> (fr, en, fix). Bases: "list" for any list[T], "session" for session[x].
_ADVICE: Dict[Tuple[str, str], Tuple[str, str, Optional[str]]] = {
    ("any", "*"): ("le type any est inconnu a la sortie : precise le type du node source (parametre as) ou ajoute un node de conversion",
                   "the any type is unknown at the output: set the source node type (as parameter) or add a conversion node", None),
    ("int", "bool"): ("un nombre n'est pas un booleen : utilise Compare", "a number is not a boolean: use Compare", None),
    ("float", "bool"): ("un nombre n'est pas un booleen : utilise Compare", "a number is not a boolean: use Compare", None),
    ("float", "int"): ("perte des decimales : utilise Math (round)", "decimals would be lost: use Math (round)", None),
    ("str", "path"): ("un texte n'est pas un chemin : passe par un node Path", "a text is not a path: go through a Path node", None),
    ("str", "dir"): ("un texte n'est pas un chemin : passe par un node Path", "a text is not a path: go through a Path node", None),
    ("int", "str"): ("utilise Template ou String (format)", "use Template or String (format)", None),
    ("float", "str"): ("utilise Template ou String (format)", "use Template or String (format)", None),
    ("path", "dir"): ("un chemin peut etre un fichier : utilise Path (parent)", "a path can be a file: use Path (parent)", None),
    ("dict", "*"): ("utilise JsonValue pour lire une cle", "use JsonValue to read a key", None),
    ("publish", "path"): ("un publish est un enregistrement : lis son chemin avec PublishFields",
                          "a publish is a record: read its path with PublishFields", None),
    ("str", "dcc_node"): ("un texte n'est pas un node : utilise houFindNode / mayFindNodes",
                          "a text is not a node: use houFindNode / mayFindNodes", None),
    ("str", "pattern"): ("un texte libre n'est pas verifie comme motif : saisis-le dans le champ du node",
                         "a free text is not checked as a pattern: type it in the node field", None),
}


@dataclass(frozen=True)
class Connection:
    status: str                     # ok | implicit | incompatible
    reason_fr: str = ""
    reason_en: str = ""
    fix: Optional[str] = None       # one-click fix id for the editor (e.g. insert_foreach)

    def to_dict(self) -> Dict[str, Optional[str]]:
        return asdict(self)


def is_valid_type(port_type: str) -> bool:
    if port_type in SCALARS or _SESSION_RE.match(port_type):
        return True
    inner = _LIST_RE.match(port_type)
    return bool(inner) and inner.group(1) != "exec" and is_valid_type(inner.group(1))


def _base(port_type: str) -> str:
    if _LIST_RE.match(port_type):
        return "list"
    if _SESSION_RE.match(port_type):
        return "session"
    return port_type


def _soft(port_type: str) -> str:
    match = _SESSION_RE.match(port_type)
    return match.group(1) if match else ""


def _label(port_type: str, lang: str) -> str:
    inner = _LIST_RE.match(port_type)
    if inner:
        return (f"une liste de {inner.group(1)}" if lang == "fr" else f"a list of {inner.group(1)}")
    return port_type


def _scalar_reaches(src: str, dst: str) -> bool:
    seen, todo = set(), [src]
    while todo:
        cur = todo.pop()
        for nxt in _IMPLICIT.get(cur, ()):
            if nxt == dst:
                return True
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return False


def _incompatible(src: str, dst: str, fr: str, en: str, fix: Optional[str] = None) -> Connection:
    return Connection("incompatible", f"{_label(src, 'fr')} ne va pas dans {_label(dst, 'fr')} : {fr}",
                      f"{_label(src, 'en')} does not go into {_label(dst, 'en')}: {en}", fix)


def can_connect(src: str, dst: str) -> Connection:
    """Can an output of type *src* feed an input of type *dst*?"""
    if not (is_valid_type(src) and is_valid_type(dst)):
        return _incompatible(src, dst, "type inconnu", "unknown type")
    if src == dst:
        return Connection("ok")
    if "exec" in (src, dst):
        return _incompatible(src, dst, "un lien d'execution relie seulement deux ports d'execution",
                             "an execution link only joins two execution ports")
    if dst == "any":
        return Connection("implicit")
    sb, db = _base(src), _base(dst)
    if sb == "session" and db == "session":
        if _soft(dst) == "*":
            return Connection("implicit")
        return _incompatible(src, dst, f"ajoute un node Instance {_soft(dst)}", f"add a {_soft(dst)} Instance node")
    if sb == "list" and db == "list":
        inner = can_connect(_LIST_RE.match(src).group(1), _LIST_RE.match(dst).group(1))
        if inner.status != "incompatible":
            return Connection("implicit")
        return _incompatible(src, dst, "les elements ne vont pas ensemble", "the items do not match")
    if sb == "list":
        if _LIST_RE.match(src).group(1) == dst:
            return _incompatible(src, dst, "mets un ForEach", "add a ForEach", "insert_foreach")
        return _incompatible(src, dst, "mets un ForEach", "add a ForEach")
    if db == "list" and _LIST_RE.match(dst).group(1) == src:
        return _incompatible(src, dst, "ajoute un node List (append)", "add a List (append) node")
    if _scalar_reaches(sb, db):
        return Connection("implicit")
    advice = _ADVICE.get((sb, db)) or _ADVICE.get((sb, "*"))
    if advice:
        return _incompatible(src, dst, *advice)
    return _incompatible(src, dst, "ajoute un node de conversion", "add a conversion node")


def catalog_types() -> List[Dict[str, object]]:
    """Port types for GET /flows/catalog: id and direct implicit targets."""
    out: List[Dict[str, object]] = [{"id": t, "implicit": list(_IMPLICIT.get(t, ()))} for t in SCALARS]
    out.append({"id": "list[T]", "implicit": ["list[U] si T -> U", "list[any]", "any"]})
    out.append({"id": "session[<soft>]", "implicit": ["session[*]"]})
    return out
