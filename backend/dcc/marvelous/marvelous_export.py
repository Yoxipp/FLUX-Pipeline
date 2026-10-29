# marvelous_export.py — publish Marvelous Designer exports into FLUX.
#
# Same flow as Painter / Designer: FLUX tells the bridge to export the open project
# into a temp dir (Alembic, OBJ, FBX, USD, GLB, and optionally the .zprj source), then
# ingests each written file under the name the Publisher composed (asset
# <CLASS>_<TASK>_<NAME>_<INSTANCE>[_<VARIANTE>] or shot <SEQ>_<SHOT>_<TASK>_<VARIANTE>),
# through the tested publish_file. Side files an OBJ drags along (.mtl, textures) are
# left out: FLUX publishes one file per format.
#
# build_export_config / pick_published are pure and unit-tested.

from __future__ import annotations

import tempfile
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

FORMATS = ("abc", "obj", "fbx", "usd", "glb", "zprj")


def build_export_config(
    export_path: str | Path,
    name: str,
    file_format: str = "abc",
    options: dict | None = None,
    with_zprj: bool = False,
) -> dict:
    """Return the bridge export config (pure, testable structure)."""
    fmt = file_format.lstrip(".").lower()
    if fmt == "usdc" or fmt == "usda":
        fmt = "usd"
    return {
        "exportPath": str(export_path).replace("\\", "/"),
        "name": name,
        "format": fmt,
        "options": {k: v for k, v in (options or {}).items() if v is not None},
        "zprj": bool(with_zprj) and fmt != "zprj",
    }


def pick_published(files: list[Path], stem: str, formats: list[str]) -> tuple[list[Path], list[str]]:
    """One file per asked format: the one named <stem>.<fmt>, else the first of that
    extension. Returns (files to publish, warnings about the rest)."""
    chosen: list[Path] = []
    warnings: list[str] = []
    for fmt in formats:
        of_fmt = [f for f in files if f.suffix.lower() == f".{fmt}"]
        if not of_fmt:
            warnings.append(f"Marvelous n'a ecrit aucun .{fmt}")
            continue
        exact = [f for f in of_fmt if f.stem == stem]
        pick = exact[0] if exact else of_fmt[0]
        chosen.append(pick)
        if len(of_fmt) > 1:
            warnings.append(f".{fmt} : {len(of_fmt)} fichiers ecrits, seul {pick.name} est publie")
    return chosen, warnings


def publish_marvelous(
    project: str,
    target_name: str,
    file_format: str = "abc",
    options: dict | None = None,
    with_zprj: bool = False,
    description: str = "",
    user: str = "unknown",
) -> dict:
    """Export the open Marvelous project and publish it under *target_name*.

    Returns {ok, published:[paths], warnings} or {ok: False, error}."""
    from core.paths import get_project_path
    from dcc.marvelous.client import marvelous_client
    from features.publisher.publish_core import publish_file

    project_path = get_project_path(project)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {project}"}
    if not target_name.strip():
        return {"ok": False, "error": "Nom FLUX vide"}

    log.info("Marvelous publish: project=%s %s (%s) -> asking the bridge to export", project, target_name, file_format)
    export_dir = Path(tempfile.mkdtemp(prefix="flux_marvelous_"))
    config = build_export_config(export_dir, target_name, file_format, options, with_zprj)
    result = marvelous_client.export(config)
    if not result.get("ok"):
        log.warning("Marvelous export failed: %s", result.get("error"))
        return {"ok": False, "error": result.get("error", "Marvelous export failed")}

    written = sorted(p for p in export_dir.rglob("*") if p.is_file())
    if not written:
        written = [Path(f) for f in result.get("files", []) if Path(f).is_file()]
    formats = [config["format"]] + (["zprj"] if config["zprj"] else [])
    chosen, warnings = pick_published(written, target_name, formats)
    warnings = list(result.get("warnings") or []) + warnings
    published: list[str] = []
    for f in chosen:
        dest = publish_file(f, project_path, description, user, project, target_name, soft="marvelous")
        if dest is None:
            warnings.append(f"{f.name} non publie (nom FLUX invalide ?)")
            continue
        published.append(str(dest))
    for w in warnings:
        log.warning("Marvelous publish: %s", w)
    if not published:
        return {"ok": False, "error": "Rien n'a pu etre publie depuis Marvelous"
                + (f" : {'; '.join(warnings)}" if warnings else "")}
    return {"ok": True, "published": published, "warnings": warnings}
