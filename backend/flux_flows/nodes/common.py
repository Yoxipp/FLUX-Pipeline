# common.py — small helpers shared by the node families (P3).
#
# as_path: a path value as received by a node (link or resolved literal). A
# portable "$FLUX/..." value (publish dest_folder, interface default) is resolved
# here because it is a stored path, not a token typed in a field; a relative path
# is relative to the project of the run (like v1 ``_path``).

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from flux_flows.nodes.contract import NodeError

_FLUX_HEADS = ("$FLUX/", "$FLUX\\", "${FLUX}/", "${FLUX}\\")


def as_path(ctx, value: Any, what: str = "chemin") -> Path:
    if isinstance(value, dict) and value.get("path"):   # a publish record given as a path
        value = value["path"]
    text = "" if value is None else str(value).strip()
    if not text:
        raise NodeError(f"{what} vide")
    if text in ("$FLUX", "${FLUX}") or text.startswith(_FLUX_HEADS):
        from core.paths import from_flux_token

        try:
            return Path(from_flux_token(text))
        except Exception as exc:
            raise NodeError(f"`$FLUX` ne peut pas etre resolu sur ce poste : {exc}") from None
    path = Path(text)
    if not path.is_absolute():
        base = (ctx.context or {}).get("project_path")
        if not base:
            raise NodeError(f"{what} relatif `{text}` sans projet : donne un chemin absolu ou `$FLUX/...`")
        path = Path(base) / path
    return path


def as_list(value: Any, what: str = "liste") -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    raise NodeError(f"{what} : liste attendue, recu {type(value).__name__}")


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "oui", "on"):
        return True
    if text in ("0", "false", "no", "non", "off"):
        return False
    raise NodeError(f"booleen attendu, recu {value!r}")


def _flux_root() -> Path:
    from core.paths import get_flux_root

    root = get_flux_root()
    if root is None:
        raise NodeError("FLUX_ROOT n'est pas defini sur ce poste")
    return Path(root)


def check_destructive_target(path: Path) -> Path:
    """Containment of erase / overwrite (P3): the target is strictly inside FLUX_ROOT
    and is not the root, a top folder of the pipe or a project folder. Returns the
    resolved path, else NodeError."""
    root = _flux_root().resolve()
    target = Path(path).resolve()
    try:
        rel = target.relative_to(root)
    except ValueError:
        raise NodeError(f"Refus : `{path}` est hors du pipe FLUX ({root})", code="E_PATH_OUTSIDE") from None
    parts = rel.parts
    if len(parts) < 2 or (parts[0].upper() == "DOSSIER_PROJETS" and len(parts) < 3):
        raise NodeError(f"Refus : `{path}` est un dossier racine du pipe ou d'un projet", code="E_PATH_OUTSIDE")
    return target


def in_project(ctx, path: Path) -> bool:
    """True when *path* is inside the run's project folder."""
    base = (ctx.context or {}).get("project_path")
    if not base:
        return False
    try:
        path.resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False
