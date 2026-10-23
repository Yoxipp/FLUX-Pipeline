"""Farm Shares from the engine's limits.config (read; written only by the locked environment screen).

The school sets the teams and their share of the farm once a year in limits.config (Tractor Limits,
"Shares" per limit tag: nominal = fair share, cap = max part of the farm). Tractor balances the
teams itself at each dispatch, nothing killed. A job whose Tractor project is not one of the
Shares falls in "default" (cap 0.1 at school on 2026-10-23): FLUX only warns about that.

The engine serves its config files over HTTP (as it does for the blades):
http://<engine>/Tractor/config?file=limits.config (read at school on 2026-10-23).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

# FLUX runs husk on the blades: its commands count in the "husk" limit (implicit tag = application name).
RENDER_TAG = "husk"
DEFAULT_SHARE = "default"
_TTL_S = 600.0        # set once a year: one read per 10 min is plenty
_FAIL_TTL_S = 60.0    # engine down: do not retry on every call
_TIMEOUT_S = 3.0
_cache: Dict[str, dict] = {}
_lock = threading.Lock()


def config_url(engine: str) -> Optional[str]:
    """http://host[:port]/Tractor/config?file=limits.config, None without an engine."""
    engine = (engine or "").strip()
    if not engine:
        return None
    if not re.match(r"^[A-Za-z0-9_.-]+(:\d{1,5})?$", engine):
        return None
    return f"http://{engine}/Tractor/config?file=limits.config"


def _strip_comments(text: str) -> str:
    # Tractor's config is JSON with '#' and '//' comment lines and the odd trailing comma.
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", "//"))]
    return re.sub(r",(\s*[}\]])", r"\1", "\n".join(lines))


def parse_shares(text: str) -> Dict[str, Dict[str, dict]]:
    """{limit tag: {team: {"nominal": float, "cap": float}}} for every limit that has Shares."""
    try:
        data = json.loads(_strip_comments(text))
    except ValueError:
        return {}
    limits = data.get("Limits") if isinstance(data, dict) else None
    out: Dict[str, Dict[str, dict]] = {}
    for tag, spec in (limits or {}).items():
        shares = spec.get("Shares") if isinstance(spec, dict) else None
        if not isinstance(shares, dict):
            continue
        out[tag] = {team: {"nominal": _num(v.get("nominal")), "cap": _num(v.get("cap"))}
                    for team, v in shares.items() if isinstance(v, dict)}
    return out


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_shares(engine: str) -> Optional[Dict[str, Dict[str, dict]]]:
    """Shares of the engine, cached. None = unknown (no engine, unreachable, unreadable)."""
    url = config_url(engine)
    if url is None:
        return None
    with _lock:
        hit = _cache.get(url)
        if hit and time.time() - hit["at"] < (_TTL_S if hit["shares"] is not None else _FAIL_TTL_S):
            return hit["shares"]
    shares = None
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as resp:  # read only GET on the school engine
            shares = parse_shares(resp.read().decode("utf-8", errors="replace")) or None
    except (OSError, ValueError):
        shares = None
    with _lock:
        _cache[url] = {"at": time.time(), "shares": shares}
    return shares


def teams(shares: Optional[Dict[str, Dict[str, dict]]], tag: str = RENDER_TAG) -> list:
    """Team names of the render tag (the Shares of FLUX's commands), 'default' excluded."""
    return sorted(t for t in ((shares or {}).get(tag) or {}) if t != DEFAULT_SHARE)


# ── environment screen: edit the Shares (2026-10-23, locked by "Understand" + password) ──
# The password is in this open source code: a guard against mistakes, not a security.

ENV_PHRASE = "Understand"
ENV_PASSWORD = "root"
LIMITS_FILE = "limits.config"
_TEAM = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class LimitsError(ValueError):
    """Readable French message: nothing was written."""


def check_unlock(phrase: str, password: str) -> None:
    if phrase != ENV_PHRASE or password != ENV_PASSWORD:
        raise LimitsError("Reglages de l'environnement verrouilles : phrase ou mot de passe incorrect")


def check_teams(teams: Dict[str, dict]) -> Dict[str, dict]:
    """{team: {"nominal": 0..1, "cap": 0..1}} with 'default' kept. Raises LimitsError."""
    if not isinstance(teams, dict) or not teams:
        raise LimitsError("Aucune equipe")
    out: Dict[str, dict] = {}
    for name, v in teams.items():
        if not _TEAM.match(str(name)):
            raise LimitsError(f"Nom d'equipe invalide : '{name}' (lettres, chiffres, _ . -)")
        nominal, cap = _num((v or {}).get("nominal")), _num((v or {}).get("cap"))
        if nominal is None or not 0 <= nominal <= 1:
            raise LimitsError(f"{name} : part nominale entre 0 et 100 %")
        if cap is None or not 0 < cap <= 1:
            raise LimitsError(f"{name} : plafond entre 1 et 100 %")
        out[str(name)] = {"nominal": nominal, "cap": cap}
    if DEFAULT_SHARE not in out:
        raise LimitsError(f"La part '{DEFAULT_SHARE}' est obligatoire (jobs des equipes inconnues)")
    return out


def _commented_lines(text: str) -> set:
    return {i for i, ln in enumerate(text.splitlines()) if ln.lstrip().startswith(("#", "//"))}


def _share_blocks(text: str) -> List[tuple]:
    """(start, end) of the '{...}' of every active "Shares" entry (commented lines skipped)."""
    commented = _commented_lines(text)
    line_of = [0] * (len(text) + 1)
    n = 0
    for i, ch in enumerate(text):
        line_of[i] = n
        if ch == "\n":
            n += 1
    blocks = []
    for m in re.finditer(r'"Shares"\s*:\s*\{', text):
        if line_of[m.start()] in commented:
            continue
        depth, i = 0, m.end() - 1
        while i < len(text):
            if line_of[i] not in commented:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        blocks.append((m.end() - 1, i + 1))
                        break
            i += 1
        else:
            raise LimitsError("limits.config illisible : bloc Shares non ferme")
    return blocks


def _fmt(x: float) -> str:
    return format(x, "g")


def apply_shares(text: str, teams: Dict[str, dict]) -> str:
    """Same file with every active Shares block replaced by these teams. Comments and every other
    rule kept as they are; checked by parsing both versions before anything is written."""
    teams = check_teams(teams)
    nl = "\r\n" if "\r\n" in text else "\n"
    blocks = _share_blocks(text)
    if not blocks:
        raise LimitsError("Aucun bloc Shares dans limits.config : rien a modifier")
    out, last = [], 0
    for start, end in blocks:
        line_start = text.rfind("\n", 0, start) + 1
        indent = re.match(r"[ \t]*", text[line_start:start]).group(0)
        names = [t for t in teams if t != DEFAULT_SHARE] + [DEFAULT_SHARE]
        rows = [f'{indent}\t"{t}": {{"nominal": {_fmt(teams[t]["nominal"])}, "cap": {_fmt(teams[t]["cap"])}}}'
                for t in names]
        out.append(text[last:start])
        out.append("{" + nl + ("," + nl).join(rows) + nl + indent + "\t}")
        last = end
    out.append(text[last:])
    new = "".join(out)
    _check_same_rules(text, new, teams)
    return new


def _rules_without_shares(text: str) -> dict:
    data = json.loads(_strip_comments(text))
    for spec in (data.get("Limits") or {}).values():
        if isinstance(spec, dict):
            spec.pop("Shares", None)
    return data


def _check_same_rules(old: str, new: str, teams: Dict[str, dict]) -> None:
    try:
        same = _rules_without_shares(old) == _rules_without_shares(new)
    except ValueError:
        raise LimitsError("limits.config illisible apres modification : rien n'est ecrit") from None
    if not same:
        raise LimitsError("La modification toucherait d'autres regles que les Shares : rien n'est ecrit")
    for tag, by_team in parse_shares(new).items():
        if by_team != teams:
            raise LimitsError(f"Shares du tag '{tag}' differentes apres modification : rien n'est ecrit")


def same_text(a: str, b: str) -> bool:
    """Same config file, BOM and line endings aside."""
    def norm(text: str) -> str:
        return text.lstrip("﻿").replace("\r\n", "\n").strip()
    return norm(a) == norm(b)


def read_local(config_dir: str) -> tuple:
    """(path, text) of limits.config in the configured network folder. Raises LimitsError."""
    folder = Path(str(config_dir or "").strip())
    if not str(config_dir or "").strip():
        raise LimitsError("Dossier de config du moteur non renseigne")
    path = folder / LIMITS_FILE
    if not path.is_file():
        raise LimitsError(f"{LIMITS_FILE} introuvable dans {folder}")
    return path, path.read_bytes().decode("utf-8")


def engine_text(engine: str) -> Optional[str]:
    """limits.config as the engine serves it (read only), None if unreachable."""
    url = config_url(engine)
    if url is None:
        return None
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def write_shares(config_dir: str, engine: str, teams: Dict[str, dict], phrase: str, password: str) -> dict:
    """Write the new Shares into the engine's limits.config (backup first). Raises LimitsError.

    Refused unless the file in that folder is the one the engine serves (wrong folder = never written).
    """
    check_unlock(phrase, password)
    path, text = read_local(config_dir)
    served = engine_text(engine)
    if served is None:
        raise LimitsError("Moteur injoignable : impossible de verifier que ce dossier est le sien, rien n'est ecrit")
    if not same_text(served, text):
        raise LimitsError(f"{path} n'est pas le {LIMITS_FILE} que sert le moteur : mauvais dossier, rien n'est ecrit")
    new = apply_shares(text, teams)
    backup = path.with_name(f"{LIMITS_FILE}.flux_{time.strftime('%Y%m%d_%H%M%S')}.bak")
    shutil.copy2(path, backup)
    tmp = path.with_name(f".{LIMITS_FILE}.flux_tmp")
    tmp.write_bytes(new.encode("utf-8"))
    os.replace(tmp, path)
    with _lock:
        _cache.clear()
    return {"path": str(path), "backup": str(backup), "shares": parse_shares(new)}


def team_warning(team: str, shares: Optional[Dict[str, Dict[str, dict]]], tag: str = RENDER_TAG) -> Optional[str]:
    """Warning when the team is not one of the Shares of FLUX's commands. None = fine or unknown."""
    by_team = (shares or {}).get(tag)
    if not by_team or team in by_team:
        return None
    names = teams(shares, tag)
    close = next((n for n in names if n.lower() == (team or "").lower()), None)
    if close:
        return (f"Equipe sur la farm '{team}' : la farm attend '{close}' (majuscules comprises). "
                f"Sinon les rendus passent dans '{DEFAULT_SHARE}'.")
    cap = (by_team.get(DEFAULT_SHARE) or {}).get("cap")
    limit = f", plafonnee a {round(cap * 100)} % de la farm" if cap is not None else ""
    return (f"Equipe sur la farm '{team}' inconnue de la farm (limits.config : {', '.join(names)}). "
            f"Les rendus passent dans la part '{DEFAULT_SHARE}'{limit}.")
