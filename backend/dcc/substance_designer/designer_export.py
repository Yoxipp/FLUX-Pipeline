# designer_export.py — publish Substance 3D Designer outputs into FLUX.
#
# Same flow as Painter (substance_painter/substance_export.py): FLUX tells the in-app
# bridge to export into a temp dir, then ingests what was written under FLUX naming:
#   - the maps of each graph -> <CLASS>_<TASK>_<NAME>_<MAP>[_<VARIANTE>], one publish
#     per map (texture_publish.publish_maps, canonical tokens BCOL / NORM / ROUGH...),
#     optionally conformed to .tx;
#   - the cooked .sbsar      -> <CLASS>_<TASK>_<NAME>_SBSAR[_<VARIANTE>];
#   - the source .sbs        -> <CLASS>_<TASK>_<NAME>_SBS[_<VARIANTE>].
# Several graphs (or packages) in one publish: each gets its own name as variante so
# two materials never land on the same map.
#
# build_export_config / variant_for are pure and unit-tested; the bridge call and the
# publishers are the existing, already-tested pieces.

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)


def build_export_config(
    export_path: str | Path,
    graphs: list[dict] | None,
    file_format: str = "png",
    size: int | None = None,
    bit_depth: str | None = None,
    maps: bool = True,
    sbsar: bool = False,
    sbs: bool = False,
) -> dict:
    """Return the bridge export config (pure, testable structure).

    *graphs*: [{"package": .sbs path, "graph": identifier, "outputs": [ids] | None}]
    (outputs None = all of them, [] = none: only its .sbsar / .sbs), None / [] = the
    graph open in Designer. *size*: output width in pixels (the
    graph's $outputsize), None = the graph's own size. *bit_depth*: 8 / 16 / 16f /
    32f (the graph's $format), None = the graph's own format."""
    return {
        "exportPath": str(export_path).replace("\\", "/"),
        "graphs": [
            {"package": str(g.get("package") or ""), "graph": str(g["graph"]),
             "outputs": list(g["outputs"]) if g.get("outputs") is not None else None}
            for g in (graphs or []) if g.get("graph")
        ],
        "fileFormat": file_format.lstrip("."),
        "size": int(size) if size else None,
        "bitDepth": bit_depth or None,
        "maps": bool(maps),
        "sbsar": bool(sbsar),
        "sbs": bool(sbs),
    }


def _token(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(text)).upper()


def variant_for(instance: str, item: str, several: bool) -> str:
    """Variante of one graph / package: the artist's instance, plus the item's own
    name when the publish holds several of them (two materials, two BCOL)."""
    parts = []
    inst = instance.strip()
    if inst and inst.lower() != "null":
        parts.append(_token(inst))
    if several and _token(item):
        parts.append(_token(item))
    return "".join(parts)


def publish_designer(
    project: str,
    class_tok: str,
    task_tok: str,
    name_tok: str,
    instance: str = "null",
    graphs: list[dict] | None = None,
    file_format: str = "png",
    size: int | None = None,
    bit_depth: str | None = None,
    maps: bool = True,
    sbsar: bool = False,
    sbs: bool = False,
    conform_tx: bool = False,
    description: str = "",
    user: str = "unknown",
    tx_only: bool = False,
) -> dict:
    """Export Designer maps / .sbsar / .sbs and ingest them into FLUX.

    Returns {ok, published:[paths], tx:[paths], warnings} or {ok: False, error}."""
    from core.paths import get_project_path
    from dcc.substance_designer.client import designer_client

    if not (maps or sbsar or sbs):
        return {"ok": False, "error": "Rien a publier : coche les maps, le .sbsar ou le .sbs"}
    project_path = get_project_path(project)
    if not project_path.exists():
        return {"ok": False, "error": f"Projet introuvable : {project}"}

    log.info("Designer publish: project=%s %s_%s_%s -> asking the bridge to export", project, class_tok, task_tok, name_tok)
    export_dir = Path(tempfile.mkdtemp(prefix="flux_designer_"))
    config = build_export_config(export_dir, graphs, file_format, size, bit_depth, maps, sbsar, sbs)
    result = designer_client.export(config)
    if not result.get("ok"):
        log.warning("Designer export failed: %s", result.get("error"))
        return {"ok": False, "error": result.get("error", "Designer export failed")}

    from dcc.texture_publish import convert_to_tx, publish_maps
    from features.publisher.publish_core import publish_file

    prefix = [class_tok, task_tok, name_tok]
    warnings: list[str] = list(result.get("warnings") or [])
    published: list[str] = []
    tx_paths: list[str] = []

    # Maps: one sub folder per graph (<export>/<graph>/<graph>_<output>.<ext>).
    graph_dirs = sorted(d for d in export_dir.iterdir() if d.is_dir())
    for gdir in graph_dirs:
        files = sorted(p for p in gdir.iterdir() if p.is_file())
        if not files:
            continue
        if tx_only:
            files, tx_warns = convert_to_tx(files, "Designer")
            warnings.extend(f"{gdir.name} : {w}" for w in tx_warns)
        variante = variant_for(instance, gdir.name, len(graph_dirs) > 1)
        done, warns = publish_maps(files, project_path, project, prefix, variante, description, user, soft="designer")
        published.extend(done)
        warnings.extend(f"{gdir.name} : {w}" for w in warns)
        if tx_only:
            tx_paths.extend(done)
        elif conform_tx and done:
            from dcc.substance_painter.substance_export import _conform_published
            tx_paths.extend(_conform_published(done, "Designer"))

    # .sbsar / .sbs: one publish per package file.
    pkg_files = sorted(p for p in export_dir.iterdir() if p.is_file() and p.suffix.lower() in (".sbsar", ".sbs"))
    for kind in (".sbsar", ".sbs"):
        of_kind = [p for p in pkg_files if p.suffix.lower() == kind]
        for f in of_kind:
            variante = variant_for(instance, f.stem, len(of_kind) > 1)
            target = "_".join([*prefix, kind[1:].upper(), *([variante] if variante else [])]).upper()
            dest = publish_file(f, project_path, description, user, project, target, soft="designer")
            if dest is None:
                warnings.append(f"{f.name} non publie (nom FLUX invalide ?)")
                continue
            published.append(str(dest))

    for w in warnings:
        log.warning("Designer publish: %s", w)
    if not published:
        return {"ok": False, "error": "Aucune sortie Designer n'a pu etre publiee"
                + (f" : {'; '.join(warnings)}" if warnings else "")}
    return {"ok": True, "published": published, "tx": tx_paths or None, "warnings": warnings}
