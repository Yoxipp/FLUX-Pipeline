"""Find an image sequence on disk from a path the artist pastes (denoise of an already rendered sequence).

Accepted: one frame (.../SH010.1001.exr), a pattern (.../SH010.####.exr, .../SH010.$F4.exr) or a folder
holding a single sequence. Result: folder, husk-style pattern (SH010.$F4.exr), first / last frame, gaps.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

_FRAME = re.compile(r"^(?P<head>.*?)(?P<num>\d+)(?P<tail>\.exr)$", re.IGNORECASE)
_PATTERN = re.compile(r"^(?P<head>.*?)(?:(?P<hashes>#+)|\$F(?P<pad>\d))(?P<tail>\.exr)$", re.IGNORECASE)


class SequenceError(ValueError):
    """Readable French message."""


def _frames(folder: Path, head: str, tail: str, pad: int) -> List[int]:
    rx = re.compile(re.escape(head) + r"(\d{%d})" % pad + re.escape(tail) + "$", re.IGNORECASE)
    out = []
    for p in folder.iterdir():
        m = rx.match(p.name)
        if m and p.is_file():
            out.append(int(m.group(1)))
    return sorted(out)


def find(path: str) -> Dict:
    """{"folder", "pattern", "first", "last", "count", "missing"}. Raises SequenceError."""
    p = Path(str(path or "").strip().strip('"'))
    if not str(p) or str(p) == ".":
        raise SequenceError("Chemin de la sequence vide")
    if p.is_dir():
        heads = {}
        for f in p.iterdir():
            m = _FRAME.match(f.name)
            if m and f.is_file():
                heads.setdefault((m["head"], m["tail"], len(m["num"])), 0)
                heads[(m["head"], m["tail"], len(m["num"]))] += 1
        if not heads:
            raise SequenceError(f"Aucune image .exr numerotee dans {p}")
        if len(heads) > 1:
            names = ", ".join(sorted(f"{h}{'#' * n}{t}" for h, t, n in heads))
            raise SequenceError(f"Plusieurs sequences dans {p} ({names}) : donner le chemin d'une image")
        (head, tail, pad), = heads
        folder = p
    else:
        folder = p.parent
        m = _PATTERN.match(p.name)
        if m:
            head, tail = m["head"], m["tail"]
            pad = len(m["hashes"]) if m["hashes"] else int(m["pad"])
        else:
            m = _FRAME.match(p.name)
            if not m:
                raise SequenceError(f"Pas une image .exr numerotee : {p.name}")
            head, tail, pad = m["head"], m["tail"], len(m["num"])
        if not folder.is_dir():
            raise SequenceError(f"Dossier introuvable : {folder}")
    if not 1 <= pad <= 9:
        raise SequenceError("Numero d'image de 1 a 9 chiffres attendu")
    frames = _frames(folder, head, tail, pad)
    if not frames:
        raise SequenceError(f"Aucune image {head}{'#' * pad}{tail} dans {folder}")
    present = set(frames)
    missing = [f for f in range(frames[0], frames[-1] + 1) if f not in present]
    return {"folder": folder, "pattern": f"{head}$F{pad}{tail}", "first": frames[0], "last": frames[-1],
            "count": len(frames), "missing": missing}
