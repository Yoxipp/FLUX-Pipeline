# common.py — small helpers shared by the node families (P3).
#
# as_path: a path value as received by a node (link or resolved literal). A
# portable "$FLUX/..." value (publish dest_folder, interface default) is resolved
# here because it is a stored path, not a token typed in a field; a relative path
# is relative to the project of the run (like v1 ``_path``).

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

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


# -- project archive (action.delete mode archive, flux.archive) ----------------------

def archive_rel(ctx, path: Path) -> Tuple[Path, str]:
    """(project root, project-relative path) of *path*; outside the run's project = NodeError."""
    project = (ctx.context or {}).get("project_path")
    if not project or not in_project(ctx, path):
        raise NodeError(f"Refus : `{path}` est hors projet (archive : seulement dans le projet du flow)",
                        code="E_PATH_OUTSIDE")
    root = Path(project)
    return root, path.resolve().relative_to(root.resolve()).as_posix()


def archive_preview(ctx, path: Path) -> Path:
    """Where *path* would land in ARCHIVE/<date>_<ARTIST>/ (dry run: moves nothing)."""
    from features.production.archive import ARCHIVE_ROOT, _safe_entity_dir, archive_label

    root, rel = archive_rel(ctx, path)
    if _safe_entity_dir(root, rel) is None:
        raise NodeError(f"Refus d'archiver `{rel}` (racine du projet ou dossier ARCHIVE)", code="E_PATH_OUTSIDE")
    return root / ARCHIVE_ROOT / archive_label((ctx.context or {}).get("user") or None) / rel


def archive_into_project(ctx, path: Path) -> Path:
    """Move *path* into the project ARCHIVE (features.production.archive:archive_folder).
    Returns the archived path. Never erases."""
    from features.production.archive import archive_folder

    root, rel = archive_rel(ctx, path)
    if not path.exists():
        raise NodeError(f"Chemin introuvable : {path}")
    try:
        archived = archive_folder(root, rel, (ctx.context or {}).get("user") or None)
    except ValueError:
        raise NodeError(f"Refus d'archiver `{rel}` (racine du projet ou dossier ARCHIVE)",
                        code="E_PATH_OUTSIDE") from None
    except FileNotFoundError:
        raise NodeError(f"Chemin introuvable : {path}") from None
    except OSError as exc:
        raise NodeError(f"Archivage : {exc}") from None
    return root / archived
