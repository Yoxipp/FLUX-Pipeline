# resolver.py — the one text resolver of the Flows (01_ARCHITECTURE §11).
#
#   {key}, {date:%Y%m%d}   context value; strftime format for date and time only
#   ${name}                flow variable, else interface value (lower case names)
#   $FLUX, ${FLUX}         pipe root (core.paths.from_flux_token), at the head of a
#                          path or dir field only; elsewhere left as typed
#   {{ }}                  literal braces; any other $NAME ($HIP, $SHOT) left as is
#
# Called by the engine when a node runs, on its params and unlinked literals. A
# value that came through a link is never resolved again (a file name holding
# "{x}" stays literal). Unknown key = E_UNKNOWN_TOKEN with the closest available
# key (Levenshtein <= 2); a known key without value (``{shot}`` outside a shot
# event) says when it is available.

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from flux_flows.nodes.contract import NodeError

UNKNOWN_TOKEN = "E_UNKNOWN_TOKEN"
PARAM_INVALID = "E_PARAM_INVALID"
MAX_DISTANCE = 2

ALWAYS_KEYS = ("user", "host", "flow", "run_id", "date", "time")
PROJECT_KEYS = ("project", "project_path")
# Naming tokens (core.constants TOKEN_TYPES, TOKEN_TYPES_SHOT) in lower case, plus asset.
NAME_KEYS = ("class", "type", "name", "instance", "variante", "iter", "seq", "shot", "asset")
CONTEXT_KEYS = ALWAYS_KEYS + PROJECT_KEYS + NAME_KEYS
FORMAT_KEYS = ("date", "time")

_TOKEN_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([^{}]*))?\}")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_FLUX_HEAD_RE = re.compile(r"^(\$FLUX|\$\{FLUX\})(?=$|[/\\])")


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def suggest_token(name: str, available: Iterable[str]) -> Optional[str]:
    """Closest key of *available* within MAX_DISTANCE edits, ties by order given."""
    best: Optional[Tuple[int, str]] = None
    low = name.lower()
    for key in available:
        d = levenshtein(low, key.lower())
        if d <= MAX_DISTANCE and (best is None or d < best[0]):
            best = (d, key)
    return best[1] if best else None


def _unknown(kind: str, name: str, available: Iterable[str]) -> NodeError:
    wrap = (lambda k: "{" + k + "}") if kind == "token" else (lambda k: "${" + k + "}")
    hint = suggest_token(name, available)
    label = "Token inconnu" if kind == "token" else "Variable inconnue"
    msg = f"{label} `{wrap(name)}`"
    details: Dict[str, Any] = {"token": name}
    if hint:
        msg += f" : tu voulais `{wrap(hint)}` ?"
        details.update({"suggestion": hint, "fix": "replace_token"})
    return NodeError(msg, code=UNKNOWN_TOKEN, details=details)


def context_from_name(filename: str) -> Dict[str, str]:
    """Naming keys (lower case) of a parsable FLUX file name, {} otherwise."""
    from features.folder_manager.naming_validator import parse_filename

    try:
        parsed = parse_filename(str(filename).replace("\\", "/").rsplit("/", 1)[-1])
    except Exception:
        return {}
    if not parsed:
        return {}
    out = {k.lower(): str(v) for k, v in parsed.items()
           if k.lower() in NAME_KEYS and isinstance(v, str) and v}
    stem = "_".join(str(parsed.get(k, "")) for k in ("CLASS", "TYPE", "NAME") if parsed.get(k))
    if stem and not parsed.get("is_shot"):
        out.setdefault("asset", stem)
    return out


def _run_datetime(context: Mapping[str, Any]) -> datetime:
    try:
        return datetime.strptime(f"{context.get('date')} {context.get('time')}", "%Y-%m-%d %H-%M-%S")
    except (TypeError, ValueError):
        return datetime.now()


def _flux_root(path_text: str) -> str:
    from core.paths import from_flux_token

    try:
        return str(from_flux_token(path_text))
    except Exception as exc:  # FLUX_ROOT not set
        raise NodeError(f"`$FLUX` ne peut pas etre resolu sur ce poste : {exc}", code=PARAM_INVALID) from None


def _context_token(match: "re.Match[str]", context: Mapping[str, Any]) -> str:
    key, fmt = match.group(1), match.group(2)
    if key not in context and key.lower() in context:
        key = key.lower()
    if key not in context:
        available = [k for k in CONTEXT_KEYS if context.get(k) not in (None, "")]
        available += [k for k in context if k not in CONTEXT_KEYS and context.get(k) not in (None, "")]
        available += [k for k in CONTEXT_KEYS if k not in available]   # filled keys win the ties
        if key.lower() in CONTEXT_KEYS:
            raise _unavailable(key.lower())
        raise _unknown("token", key, available)
    value = context.get(key)
    if value in (None, ""):
        raise _unavailable(key)
    if fmt is not None:
        if key not in FORMAT_KEYS:
            raise NodeError(f"`{{{key}:{fmt}}}` : le format n'existe que pour date et time", code=PARAM_INVALID)
        try:
            return _run_datetime(context).strftime(fmt)
        except ValueError as exc:
            raise NodeError(f"Format de date invalide `{fmt}` : {exc}", code=PARAM_INVALID) from None
    return str(value)


def _unavailable(key: str) -> NodeError:
    if key in PROJECT_KEYS:
        why = "disponible seulement pour un flow de projet ou un evenement qui donne le projet"
    elif key in NAME_KEYS:
        why = f"disponible seulement si l'evenement fournit un {key} (nom de fichier FLUX)"
    else:
        why = "pas de valeur dans ce run"
    return NodeError(f"Token `{{{key}}}` : {why}", code=UNKNOWN_TOKEN, details={"token": key})


def resolve(text: Any, context: Mapping[str, Any],
            variable: Optional[Callable[[str], Any]] = None,
            variable_names: Iterable[str] = (), *, path_field: bool = False) -> Any:
    """Resolve *text* (non strings are returned as is). ``variable(name)`` gives a
    ``${name}`` value or raises KeyError; ``variable_names`` feeds the suggestion."""
    if not isinstance(text, str) or not any(c in text for c in "{}$"):
        return text
    s = text
    head = ""
    if path_field:
        m = _FLUX_HEAD_RE.match(s)
        if m:
            head, s = m.group(1), s[m.end():]
    out: List[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in "{}" and s.startswith(c * 2, i):
            out.append(c)
            i += 2
            continue
        if c == "{":
            m = _TOKEN_RE.match(s, i)
            if not m:
                raise NodeError(f"Accolade `{{` sans token valide dans `{text}` : ecris `{{{{` pour une accolade",
                                code=PARAM_INVALID)
            out.append(_context_token(m, context))
            i = m.end()
            continue
        if c == "}":
            raise NodeError(f"Accolade `}}` seule dans `{text}` : ecris `}}}}` pour une accolade",
                            code=PARAM_INVALID)
        if c == "$":
            m = _VAR_RE.match(s, i)
            if m and m.group(1) != "FLUX":
                name = m.group(1)
                if variable is None:
                    raise _unknown("variable", name, variable_names)
                try:
                    out.append(str(variable(name)))
                except KeyError:
                    raise _unknown("variable", name, variable_names) from None
                i = m.end()
                continue
        out.append(c)
        i += 1
    body = "".join(out)
    return _flux_root(head + body) if head else body


def tokens_in(text: Any) -> List[str]:
    """Context keys and ${variables} a text uses (validator, P4): ["shot", "$dest"]."""
    if not isinstance(text, str):
        return []
    cleaned = text.replace("{{", "").replace("}}", "")
    variables = ["$" + m.group(1) for m in _VAR_RE.finditer(cleaned) if m.group(1) != "FLUX"]
    found = [m.group(1) for m in _TOKEN_RE.finditer(_VAR_RE.sub("", cleaned))] + variables
    return found
