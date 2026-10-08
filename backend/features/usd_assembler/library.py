# library.py — what already exists in a project for the USD assembler default view
# (USD_ASSEMBLER_V2 step A2): auto components (ADR 0018) and assembled roots, with
# their versions, slots, instances, broken links and "used by". Reads layers with Sdf
# only (no stage composition), so a large project lists quickly.

from __future__ import annotations

import os
import re
from pathlib import Path

from core.logger import get_logger

from .component_auto import COMPONENT_EXT, component_dir

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


# Token categories that never classify an asset in the UI: the asset itself, its
# departments (relative sub-paths), instances, shots and free-form custom tokens.
_NOT_SORT_TOKENS = {"NAME", "TYPE", "TYPE_SHOT", "INSTANCE", "SEQ", "SHOT", "custom"}


def _tokens_of(tokens: dict, name: str) -> dict[str, str]:
    """{category: value} of every token whose folder contains the NAME folder (longest
    match per category), e.g. {"CLASS": "CHAR"}. UI sorting / filtering only (retake 03):
    never a prim name, a vNNN or a LAST pointer. Empty when NAME is unknown to tokens.json."""
    name_path = str(tokens.get("NAME", {}).get(name, "")).replace("\\", "/").strip("/")
    out: dict[str, str] = {}
    if not name_path:
        return out
    for category, values in tokens.items():
        if category in _NOT_SORT_TOKENS or not isinstance(values, dict):
            continue
        best, best_len = None, -1
        for value, value_path in values.items():
            vp = str(value_path).replace("\\", "/").strip("/")
            if vp and "{" not in vp and (name_path == vp or name_path.startswith(vp + "/")) \
                    and (len(vp) > best_len or (len(vp) == best_len and str(value) < str(best))):
                best, best_len = value, len(vp)
        if best is not None:
            out[str(category)] = str(best)
    return out


def token_keys(entries: list[dict]) -> list[str]:
    """Categories present on at least one entry, CLASS first then alphabetical."""
    keys = {k for e in entries for k in (e.get("tokens") or {})}
    return sorted(keys, key=lambda k: (k != "CLASS", k))


def _is_assembly_entry(entry: Path | None) -> bool:
    """True when this <NAME>/usd entry is a decor (kind=assembly), not a component."""
    if entry is None or not entry.is_file():
        return False
    from pxr import Sdf

    try:
        layer = Sdf.Layer.OpenAsAnonymous(str(entry))
    except Exception:                  # unreadable entry (half-written, OneDrive not synced)
        layer = None
    if layer is None or not layer.defaultPrim:
        return False
    spec = layer.GetPrimAtPath(Sdf.Path(f"/{layer.defaultPrim}"))
    return bool(spec is not None and spec.kind == "assembly")


def _component_info(project: Path, tokens: dict, name: str, parent: Path, versions: list[str]) -> dict:
    """One created component (ADR 0023): recipe, what each file resolves to now, proposals."""
    from features.publisher.publish_layout import last_version_label

    from . import component_auto as ca
    from . import component_recipe as cr

    last_file = parent / f"{name}_LAST{COMPONENT_EXT}"
    last = last_version_label(parent, name, COMPONENT_EXT) if last_file.is_file() else None
    current = last or versions[-1]
    entry = parent / f"{name}_{current}" / f"{name}{COMPONENT_EXT}"
    broken = ca.unreadable_versions(parent, name)
    if current in broken:
        # LAST points at an unreadable version: show the last one that reads.
        fallback = ca._latest_entry(parent, name)
        if fallback is not None:
            entry, current = fallback, fallback.parent.name[len(name) + 1:]
    notes: list[str] = []
    if broken:
        notes.append(f"version(s) illisible(s) ignoree(s) : {', '.join(broken)} (ecriture "
                     f"interrompue ou fichier OneDrive pas encore synchronise), {current} utilisee")
    composed = ca.entry_signature(entry)
    warnings: list[str] = []
    try:
        recipe = ca.current_recipe(project, name) or cr.empty_recipe([])
        resolved, warnings = ca.resolve_files(project, name, recipe)
        # A new link may come from any task of the project (ADR 0024).
        proposed = ca.proposed_files(project, name, recipe, ca.available_departments(project))
    except Exception as exc:          # unreadable publish tree: list the component anyway
        log.info("Library: component %s unreadable: %s", name, exc)
        recipe, resolved, proposed = cr.empty_recipe([]), {}, []
        warnings = [f"component illisible : {exc}"]
    files = []
    for f in recipe["files"]:
        res = resolved.get(f["id"])
        files.append({**f, "resolved_version": res["version"] if res else None,
                      "composed_version": (composed.get(f["id"]) or {}).get("version"),
                      "found": res is not None,
                      # the prim it resolves to changed since (e.g. a wrong defaultPrim fixed)
                      "prim_changed": bool(res and f["id"] in composed
                                           and (composed[f["id"]].get("prim") or "") != res["prim"])})
    legacy = not ca._entry_flux(entry).get("recipe")
    stale = legacy or any(f["found"] and (f["resolved_version"] != f["composed_version"] or f["prim_changed"])
                          for f in files)         or set(composed) - set(resolved)
    return {
        "name": name, "class": _class_of(tokens, name), "tokens": _tokens_of(tokens, name),
        "state": "stale" if stale else ("ok" if files else "empty"),
        "legacy": legacy, "version": current, "versions": versions,
        "blocks": recipe.get("blocks") or [],
        "departments": recipe["departments"], "files": files, "proposed": proposed,
        "variant_sets": ca.entry_variant_sets(entry),
        "warnings": notes + warnings + cr.warnings(recipe),
        "dir": str(parent), "last": str(last_file) if last_file.is_file() else None,
        "used_by": [],
    }


def list_components(project_path: str | Path) -> list[dict]:
    """Components created in the project (ADR 0023: never proposed automatically).

    A decor (ADR 0019: an asset whose USD is an assembly) is listed by
    list_assemblies, not here."""
    from features.folder_manager.tokens import load_tokens

    from .assembly_v2 import current_entry as _assembly_entry

    project = Path(project_path)
    tokens = load_tokens(project)
    out: list[dict] = []
    for name in sorted(tokens.get("NAME", {})):
        parent = component_dir(project, name)
        if parent is None:
            continue
        versions = _component_versions(parent, name)
        if not versions or _is_assembly_entry(_assembly_entry(project, name)):
            continue
        out.append(_component_info(project, tokens, name, parent, versions))
    return out


def creatable_components(project_path: str | Path, components: list[dict],
                         assemblies: list[dict]) -> list[str]:
    """Asset NAMEs a component can be created for: no component, not a decor."""
    from features.folder_manager.tokens import load_tokens

    taken = {c["name"] for c in components} | {a["name"] for a in assemblies}
    return [n for n in sorted(load_tokens(Path(project_path)).get("NAME", {})) if n not in taken]


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

    from features.folder_manager.tokens import load_tokens

    from .assembly_v2 import assembly_dir

    project = Path(project_path)
    folder = project / subdir
    comp_dirs = {Path(str(Path(c["dir"]).resolve())): c["name"] for c in (components or [])}
    out: list[dict] = []
    seen: set[str] = set()
    # Decors that are assets (ADR 0019) plus the legacy usd/assembly/<ASM>/ folders.
    tokens = load_tokens(project)
    names = sorted(tokens.get("NAME", {}))
    names += sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []
    for name in dict.fromkeys(names):
        entry = current_entry(project, name)
        if entry is None or name in seen or not _is_assembly_entry(entry):
            continue
        parent = entry.parent.parent
        contents = entry.parent / f"{name}_contents{ASSEMBLY_EXT}"
        layer = Sdf.Layer.OpenAsAnonymous(str(contents))
        instances = _instances(layer, contents, comp_dirs) if layer is not None else []
        last = parent / f"{name}_LAST{ASSEMBLY_EXT}"
        layout = layout_file(project, name)
        seen.add(name)
        out.append({"name": name, "class": _class_of(tokens, name) or "",
                    "tokens": _tokens_of(tokens, name),
                    "file": str(last if last.is_file() else entry),
                    "version": entry.parent.name.rsplit("_", 1)[-1],
                    "versions": assembly_versions(parent, name), "legacy": False,
                    "dir": str(assembly_dir(project, name)),
                    "layout": str(layout) if layout else None, "layout_version": _pinned_layout_version(entry),
                    "instances": instances,
                    "broken": sum(1 for i in instances if i["broken"])})
    if not folder.is_dir():
        return out
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
        out.append({"name": layer.defaultPrim, "tokens": {}, "file": str(file), "version": None, "versions": [],
                    "legacy": True, "dir": str(file.parent),
                    "layout": None, "layout_version": None, "instances": instances,
                    "broken": sum(1 for i in instances if i["broken"])})
    return out


def build_library(project_path: str | Path, assembly_subdir: str = DEFAULT_ASSEMBLY_SUBDIR) -> dict:
    """{"components", "assemblies", "creatable", "departments"} with components' ``used_by``."""
    from .component_auto import available_departments

    components = list_components(project_path)
    assemblies = list_assemblies(project_path, assembly_subdir, components)
    by_name = {c["name"]: c for c in components}
    for asm in assemblies:
        for inst in asm["instances"]:
            comp = by_name.get(inst["component"] or "")
            if comp is not None and asm["name"] not in comp["used_by"]:
                comp["used_by"].append(asm["name"])
    from . import component_recipe as cr

    return {"components": components, "assemblies": assemblies,
            "creatable": creatable_components(project_path, components, assemblies),
            "departments": available_departments(project_path),
            # Token categories the UI can sort / filter by (retake 03).
            "token_keys": token_keys(components + assemblies),
            # The UI offers only what the backend accepts (one source of truth).
            "rules": {"kinds": list(cr.KINDS),
                      "default_kind": dict(cr.DEFAULT_KIND),
                      "targets": {k: sorted(v) for k, v in cr.TARGET_KINDS.items()},
                      "proxy": {k: sorted(v) for k, v in cr.PROXY_KINDS.items()},
                      "preview": sorted(cr.PREVIEW_KINDS),
                      # Block a task's links go in (GEO -> model): "New link" and
                      # "New block" follow it (2026-09-26).
                      "block_of_task": dict(cr.BLOCK_OF_TASK)}}


def asset_usd(project_path: str | Path, name: str,
              assembly_subdir: str = DEFAULT_ASSEMBLY_SUBDIR) -> dict:
    """The assembled USD of ONE asset, for its "USD" task in the Production tab
    (2026-09-26): its component (departments, versions, state), or its assembly
    when it is a decor, and the assemblies it is used in."""
    from features.folder_manager.tokens import load_tokens

    from .assembly_v2 import current_entry as _assembly_entry

    project = Path(project_path)
    tokens = load_tokens(project)
    component = None
    parent = component_dir(project, name)
    if parent is not None:
        versions = _component_versions(parent, name)
        if versions and not _is_assembly_entry(_assembly_entry(project, name)):
            component = _component_info(project, tokens, name, parent, versions)
    assemblies = list_assemblies(project, assembly_subdir, [component] if component else [])
    own = next((a for a in assemblies if a["name"] == name), None)
    used_by = [a["name"] for a in assemblies
               if a["name"] != name and any(i.get("component") == name for i in a["instances"])]
    return {"name": name, "class": _class_of(tokens, name), "component": component,
            "assembly": own, "used_by": used_by}


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
