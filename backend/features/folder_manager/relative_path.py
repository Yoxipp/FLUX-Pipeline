"""
FLUX - "Copy Path Relative" of the Folder Manager.

Turns a project path into a Houdini path built on the scene variables set by the
FLUX Work HDA: ``$FLUX/DOSSIER_PROJETS/$PROD/shot/$SEQ/$SHOT/fx/...``.

* $PROD  = the project folder.
* $SEQ   = the first segment that is a SEQ token, $SHOT = the next one when it is a
  shot of that sequence (shot/, render/, any layout that nests <SEQ>/<SHOT>).
* $ASSET = the folder of a character (CHAR class), the only kind of asset a Work
  points at.

A whole segment becomes ``$VAR``; the same value inside a later segment (a file name
like ``SEQ010_SHOT020_fx.bgeo``) becomes ``${VAR}``, only on ``_ . -`` boundaries.
"""

from __future__ import annotations

import re
from pathlib import Path

from features.folder_manager.tokens import load_tokens

ROOT = "$FLUX/DOSSIER_PROJETS"


def _split(path: str) -> list[str]:
    return [p for p in path.replace("\\", "/").split("/") if p]


def _seq_shot(tokens: dict, parts: list[str]) -> tuple[int, int]:
    """Index of the sequence segment and of its shot segment (-1 when absent)."""
    seqs = {str(k).upper() for k in (tokens.get("SEQ") or {})}
    shots = {str(k).upper() for k in (tokens.get("SHOT") or {})}
    for i, part in enumerate(parts):
        if part.upper() in seqs:
            nxt = parts[i + 1].upper() if i + 1 < len(parts) else ""
            return i, (i + 1 if nxt and f"{part.upper()}/{nxt}" in shots else -1)
    return -1, -1


def _asset(tokens: dict, parts: list[str]) -> int:
    """Index of the character folder segment (-1 when the path is not under one)."""
    char_root = _split((tokens.get("CLASS") or {}).get("CHAR", ""))
    if not char_root or "{" in "/".join(char_root):
        return -1
    n = len(char_root)
    if len(parts) > n and [p.lower() for p in parts[:n]] == [p.lower() for p in char_root]:
        return n
    return -1


def relative_path(project_path: Path, project: str, rel_path: str) -> str:
    """Houdini path of *rel_path* (relative to the project root) with $PROD/$SEQ/$SHOT/$ASSET."""
    parts = _split(rel_path)
    tokens = load_tokens(project_path) or {}
    seq_i, shot_i = _seq_shot(tokens, parts)
    asset_i = _asset(tokens, parts)

    found: list[tuple[str, str]] = [("PROD", project)]       # (variable, value) seen so far
    out: list[str] = []
    for i, part in enumerate(parts):
        var = {seq_i: "SEQ", shot_i: "SHOT", asset_i: "ASSET"}.get(i)
        if var:
            out.append("$" + var)
            found.append((var, part))
            continue
        for name, value in found:
            # Boundaries keep "SEQ01" from matching inside "SEQ010".
            part = re.sub(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(value),
                          "${%s}" % name, part, flags=re.IGNORECASE)
        out.append(part)
    return "/".join([ROOT, "$PROD", *out])
