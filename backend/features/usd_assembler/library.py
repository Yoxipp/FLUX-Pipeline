# library.py — what already exists in a project for the USD assembler default view
# (USD_ASSEMBLER_V2 step A2): auto components (ADR 0018) and assembled roots, with
# their versions, slots, instances, broken links and "used by". Reads layers with Sdf
# only (no stage composition), so a large project lists quickly.

from __future__ import annotations

import os
import re
from pathlib import Path

from core.logger import get_logger

from .component_auto import COMPONENT_EXT, DEPARTMENTS, _plain, collect_slots, component_dir

log = get_logger("usd_assembler.library")

DEFAULT_ASSEMBLY_SUBDIR = "usd/assembly"
_USD_EXTS = (".usd", ".usda", ".usdc")
_MAX_DEPTH = 3   # /<ASSEMBLY>/<CLASS>/<INSTANCE>


def _component_versions(parent: Path, name: str) -> list[str]:
    rx = re.compile(rf"^{re.escape(name)}_(v\d+)$")
    out = []
    if parent.is_dir():
        for p in parent.iterdir():
            m = rx.match(p.name)
            if m and p.is_dir() and (p / f"{name}{COMPONENT_EXT}").is_file():
                out.append(m.group(1))
    return sorted(out, key=lambda v: int(v[1:]))


def _entry_slots(entry: Path) -> dict:
    """Departments recorded in a component entry (ADR 0019). A pre-0019 entry (slots
    model / skel / look without variants) reads as out of date."""
    from pxr import Sdf

    layer = Sdf.Layer.OpenAsAnonymous(str(entry))
    if layer is None:
        return {}
    flux = _plain(dict(layer.customLayerData).get("flux", {}))
    slots = flux.get("slots") if isinstance(flux, dict) else None
    out = {k: dict(v) for k, v in (slots or {}).items() if k in DEPARTMENTS and "variants" in v}
    excluded = str(flux.get("excluded") or "") if isinstance(flux, dict) else ""
    for dept in filter(None, excluded.split(",")):
        out[str(dept)] = {"pin": {"exclude": True}}
    return out


def _variant_versions(slot: dict) -> dict[str, str]:
    return {v: str(d.get("version")) for v, d in (slot.get("variants") or {}).items()}


def _class_of(tokens: dict, name: str) -> str | None:
    """CLASS token whose folder contains the NAME folder (longest match), for deep links."""
    name_path = str(tokens.get("NAME", {}).get(name, "")).replace("\\", "/").strip("/")
    best = None
    for cls, cls_path in tokens.get("CLASS", {}).items():
        cp = str(cls_path).replace("\\", "/").strip("/")
        if cp and "{" not in cp and (name_path == cp or name_path.startswith(cp + "/")):
            if best is None or len(cp) > len(str(tokens["CLASS"][best])):
                best = cls
    return best


def list_components(project_path: str | Path) -> list[dict]:
    """Every asset with a component or with publishes that could feed one."""
    from features.folder_manager.tokens import load_tokens
    from features.publisher.publish_layout import last_version_label

    project = Path(project_path)
    tokens = load_tokens(project)
    out: list[dict] = []
    for name in sorted(tokens.get("NAME", {})):
        parent = component_dir(project, name)
        if parent is None:
            continue
        try:
            published = {d: {"task": v["task"], "version": v["version"], "default": v["default"],
                             "variants": _variant_versions(v)}
                         for d, v in collect_slots(project, name).items()}
        except Exception as exc:          # unreadable publish tree: list the asset anyway
            log.info("Library: slots of %s unreadable: %s", name, exc)
            published = {}
        versions = _component_versions(parent, name)
        if not versions and not published:
            continue
        last_file = parent / f"{name}_LAST{COMPONENT_EXT}"
        last = last_version_label(parent, name, COMPONENT_EXT) if last_file.is_file() else None
        current = last or (versions[-1] if versions else None)
        slots = _entry_slots(parent / f"{name}_{current}" / f"{name}{COMPONENT_EXT}") if current else {}

        if not current:
            state = "missing" if "model" in published else "incomplete"
        elif any(not (slots.get(d) or {}).get("pin")
                 and _variant_versions(slots.get(d) or {}) != v["variants"]
                 for d, v in published.items()):
            state = "stale"
        else:
            state = "ok"
        out.append({
            "name": name, "class": _class_of(tokens, name),
            "state": state, "version": current, "versions": versions,
            "slots": {d: {"task": v.get("task"), "version": v.get("version"), "default": v.get("default"),
                          "variants": _variant_versions(v),
                          "pin": dict(v["pin"]) if v.get("pin") else None} for d, v in slots.items()},
            "published": published,
            "dir": str(parent), "last": str(last_file) if last_file.is_file() else None,
            "used_by": [],
        })
    return out


def _instances(layer, file: Path, components: dict[Path, str]) -> list[dict]:
    from pxr import Sdf

    out: list[dict] = []

    def _walk(spec, depth: int) -> None:
        for child in spec.nameChildren:
            items = list(child.referenceList.GetAddedOrExplicitItems())
            items += list(child.payloadList.GetAddedOrExplicitItems())
            for item in items:
                raw = item.assetPath
                target = Path(raw) if Path(raw).is_absolute() else (file.parent / raw)
                target = Path(str(target.resolve()))
                comp = components.get(target.parent) or components.get(target.parent.parent)
                out.append({
                    "prim": child.path.pathString, "asset_path": raw,
                    "component": comp, "broken": not target.exists(),
                    "follows_last": "_LAST." in target.name,
                    # ADR 0019: department variants this instance picked (empty = component default)
                    "variants": {str(k): str(v) for k, v in dict(child.variantSelections).items()},
                })
            if not items and depth < _MAX_DEPTH:
                _walk(child, depth + 1)

    root = layer.GetPrimAtPath(Sdf.Path(f"/{layer.defaultPrim}")) if layer.defaultPrim else None
    if root is not None:
        _walk(root, 1)
    return out


def _pinned_layout_version(entry: Path) -> str | None:
    """vNNN of the layout sublayered by an assembly version payload (None if none)."""
    from pxr import Sdf

    payload = Sdf.Layer.OpenAsAnonymous(str(entry.with_name(entry.stem + "_payload" + entry.suffix)))
    for sub in (payload.subLayerPaths if payload is not None else []):
        m = re.search(r"_layout_(v\d+)\.usd[ac]?$", sub)
        if m:
            return m.group(1)
    return None


def list_assemblies(project_path: str | Path, subdir: str = DEFAULT_ASSEMBLY_SUBDIR,
                    components: list[dict] | None = None) -> list[dict]:
    """Assemblies under *subdir*: versioned ones (A3, ``<ASM>/<ASM>_vNNN``) first, then
    legacy flat roots (kind=assembly) written by the old builder."""
    from pxr import Sdf

    from .assembly_v2 import ASSEMBLY_EXT, assembly_versions, current_entry, layout_file

    folder = Path(project_path) / subdir
    if not folder.is_dir():
        return []
    comp_dirs = {Path(str(Path(c["dir"]).resolve())): c["name"] for c in (components or [])}
    out: list[dict] = []
    seen: set[str] = set()
    for d in sorted(p for p in folder.iterdir() if p.is_dir()):
        entry = current_entry(project_path, d.name)
        if entry is None:
            continue
        contents = entry.parent / f"{d.name}_contents{ASSEMBLY_EXT}"
        layer = Sdf.Layer.OpenAsAnonymous(str(contents))
        instances = _instances(layer, contents, comp_dirs) if layer is not None else []
        last = d / f"{d.name}_LAST{ASSEMBLY_EXT}"
        layout = layout_file(project_path, d.name)
        seen.add(d.name)
        out.append({"name": d.name, "file": str(last if last.is_file() else entry),
                    "version": entry.parent.name.rsplit("_", 1)[-1],
                    "versions": assembly_versions(d, d.name), "legacy": False,
                    "layout": str(layout) if layout else None, "layout_version": _pinned_layout_version(entry),
                    "instances": instances,
                    "broken": sum(1 for i in instances if i["broken"])})
    for file in sorted(p for p in folder.iterdir() if p.suffix.lower() in _USD_EXTS and p.is_file()):
        layer = Sdf.Layer.OpenAsAnonymous(str(file))
        if layer is None or not layer.defaultPrim:
            continue
        spec = layer.GetPrimAtPath(Sdf.Path(f"/{layer.defaultPrim}"))
        if spec is None or spec.kind != "assembly":
            continue
        if layer.defaultPrim in seen:
            continue
        instances = _instances(layer, file, comp_dirs)
        out.append({"name": layer.defaultPrim, "file": str(file), "version": None, "versions": [],
                    "legacy": True, "layout": None, "layout_version": None, "instances": instances,
                    "broken": sum(1 for i in instances if i["broken"])})
    return out


def build_library(project_path: str | Path, assembly_subdir: str = DEFAULT_ASSEMBLY_SUBDIR) -> dict:
    """{"components": [...], "assemblies": [...]} with components' ``used_by`` filled."""
    components = list_components(project_path)
    assemblies = list_assemblies(project_path, assembly_subdir, components)
    by_name = {c["name"]: c for c in components}
    for asm in assemblies:
        for inst in asm["instances"]:
            comp = by_name.get(inst["component"] or "")
            if comp is not None and asm["name"] not in comp["used_by"]:
                comp["used_by"].append(asm["name"])
    return {"components": components, "assemblies": assemblies}


def relink_instance(project_path: str | Path, file: str | Path, prim: str, component: str,
                    version: str = "LAST", assembly_subdir: str = DEFAULT_ASSEMBLY_SUBDIR) -> dict:
    """Point one assembly instance at *component* (its LAST or a frozen vNNN entry).

    Keeps the instance prim (so a DCC placement layer still applies) and rewrites only
    its references, relative to the assembly file (ADR 0010). Atomic write.
    """
    from pxr import Sdf

    from .io.writer import _export_atomic

    project = Path(project_path)
    file = Path(file)
    base = Path(str((project / assembly_subdir).resolve()))
    if Path(str(file.resolve())).parent != base or file.suffix.lower() not in _USD_EXTS:
        raise ValueError(f"not an assembly of this project: {file}")
    parent = component_dir(project, component)
    if parent is None:
        raise ValueError(f"unknown asset '{component}'")
    if version in ("", "LAST", "latest"):
        target = parent / f"{component}_LAST{COMPONENT_EXT}"
    else:
        if not re.fullmatch(r"v\d+", version):
            raise ValueError(f"bad version '{version}'")
        target = parent / f"{component}_{version}" / f"{component}{COMPONENT_EXT}"
    if not target.is_file():
        raise ValueError(f"component {component} {version or 'LAST'} not found")

    layer = Sdf.Layer.OpenAsAnonymous(str(file))
    spec = layer.GetPrimAtPath(Sdf.Path(prim)) if layer is not None else None
    if spec is None:
        raise ValueError(f"instance {prim} not found in {file.name}")
    try:
        rel = os.path.relpath(str(target), str(file.parent)).replace(os.sep, "/")
    except ValueError:
        rel = target.as_posix()
    spec.referenceList.ClearEdits()
    spec.payloadList.ClearEdits()
    spec.referenceList.prependedItems = [Sdf.Reference(rel)]
    _export_atomic(layer, file)
    log.info("Relinked %s %s -> %s", file.name, prim, rel)
    return {"prim": prim, "asset_path": rel}
