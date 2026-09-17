# assembly_v2.py — versioned USD assemblies edited from the Library (USD_ASSEMBLER_V2
# step A3, decisions section 10). FLUX decides WHAT (instances, component versions);
# the DCC decides WHERE (layout layer, read only here). Output:
#   usd/assembly/<ASM>/<ASM>_vNNN/<ASM>.usda           entry: kind=assembly, assetInfo,
#                                                      payload -> ./<ASM>_payload.usda,
#                                                      customLayerData.flux.instances_json
#   usd/assembly/<ASM>/<ASM>_vNNN/<ASM>_payload.usda   sublayers: layout (if any) > contents
#   usd/assembly/<ASM>/<ASM>_vNNN/<ASM>_contents.usda  /<ASM>/<CLASS>/<INSTANCE> kind=component,
#                                                      instanceable, reference -> component
#   usd/assembly/<ASM>/<ASM>_LAST.usda                 pointer layer (ADR 0017)
#   usd/assembly/<ASM>/<ASM>_layout_LAST.usd*          placement from the DCC (later unit)
# Every edit writes a new version so a shot can freeze one. Paths are relative (ADR 0010).
# Legacy flat assemblies (usd/assembly/<ASM>.usda) are read and converted on first edit.

from __future__ import annotations

import json
import re
from pathlib import Path

from core.logger import get_logger

from .component_auto import COMPONENT_EXT, _rel, component_dir
from .structure.naming import sanitize_token

log = get_logger("usd_assembler.assembly_v2")

ASSEMBLY_SUBDIR = "usd/assembly"
ASSEMBLY_EXT = ".usda"
DEFAULT_CLASS = "MISC"
_VERSION_RE = re.compile(r"v\d+")
_PRIM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LAYOUT_EXTS = (".usd", ".usda", ".usdc")


# ── locations ────────────────────────────────────────────────────────────────

def assembly_root(project_path: str | Path) -> Path:
    return Path(project_path) / ASSEMBLY_SUBDIR


def assembly_dir(project_path: str | Path, name: str) -> Path:
    return assembly_root(project_path) / name


def _check_name(name: str) -> str:
    token = sanitize_token(name or "")
    if not token or token != name or not _PRIM_RE.match(name):
        raise ValueError(f"nom d'assembly invalide : {name!r} (lettres, chiffres, _)")
    return name


def _last_file(parent: Path, name: str) -> Path:
    return parent / f"{name}_LAST{ASSEMBLY_EXT}"


def _version_entry(parent: Path, name: str, version: str) -> Path:
    return parent / f"{name}_{version}" / f"{name}{ASSEMBLY_EXT}"


def assembly_versions(parent: Path, name: str) -> list[str]:
    rx = re.compile(rf"^{re.escape(name)}_(v\d+)$")
    out = [m.group(1) for p in (parent.iterdir() if parent.is_dir() else [])
           if (m := rx.match(p.name)) and p.is_dir() and (p / f"{name}{ASSEMBLY_EXT}").is_file()]
    return sorted(out, key=lambda v: int(v[1:]))


def current_entry(project_path: str | Path, name: str) -> Path | None:
    """Entry layer of the version LAST points at (else the highest vNNN)."""
    from features.publisher.publish_layout import last_version_label

    parent = assembly_dir(project_path, name)
    label = last_version_label(parent, name, ASSEMBLY_EXT) if _last_file(parent, name).is_file() else None
    versions = assembly_versions(parent, name)
    version = label if label in versions else (versions[-1] if versions else None)
    return _version_entry(parent, name, version) if version else None


def layout_file(project_path: str | Path, name: str) -> Path | None:
    parent = assembly_dir(project_path, name)
    for ext in _LAYOUT_EXTS:
        cand = parent / f"{name}_layout_LAST{ext}"
        if cand.is_file():
            return cand
    return None


# ── reading instances ────────────────────────────────────────────────────────

def _require_component(project_path: Path, component: str, version: str) -> Path:
    target = _component_target(project_path, component, version)
    if not target.is_file():
        raise ValueError(f"component {component} {version or 'LAST'} introuvable (generer le component d'abord)")
    return target


def _component_target(project_path: Path, component: str, version: str) -> Path:
    parent = component_dir(project_path, component)
    if parent is None:
        raise ValueError(f"asset inconnu : {component!r}")
    if version in ("", "LAST", "latest"):
        return parent / f"{component}_LAST{COMPONENT_EXT}"
    if not _VERSION_RE.fullmatch(version):
        raise ValueError(f"version invalide : {version!r}")
    return parent / f"{component}_{version}" / f"{component}{COMPONENT_EXT}"


def read_instances(project_path: str | Path, name: str) -> list[dict]:
    """Current instances ``[{"name", "class", "component", "version"}]``.

    Versioned assembly: ``customLayerData.flux.instances_json`` of the current entry.
    Legacy flat file: derived from its references (class from the prim path).
    """
    from pxr import Sdf

    entry = current_entry(project_path, name)
    if entry is not None:
        layer = Sdf.Layer.OpenAsAnonymous(str(entry))
        flux = dict(layer.customLayerData).get("flux", {}) if layer else {}
        raw = flux.get("instances_json") if isinstance(flux, dict) else None
        return [dict(i) for i in json.loads(raw)] if raw else []

    legacy = assembly_root(project_path) / f"{name}{ASSEMBLY_EXT}"
    if not legacy.is_file():
        raise ValueError(f"assembly introuvable : {name}")
    from .library import _instances, list_components

    comps = {Path(str(Path(c["dir"]).resolve())): c["name"] for c in list_components(project_path)}
    layer = Sdf.Layer.OpenAsAnonymous(str(legacy))
    out: list[dict] = []
    for inst in _instances(layer, legacy, comps):
        parts = [p for p in inst["prim"].split("/") if p]
        m = re.search(r"_(v\d+)[\\/]", inst["asset_path"])
        out.append({
            "name": parts[-1],
            "class": parts[1] if len(parts) >= 3 else DEFAULT_CLASS,
            "component": inst["component"] or "",
            "version": "LAST" if inst["follows_last"] or not m else m.group(1),
        })
    return out


# ── editing ──────────────────────────────────────────────────────────────────

def _class_for(project_path: Path, component: str) -> str:
    from features.folder_manager.tokens import load_tokens

    from .library import _class_of

    return _class_of(load_tokens(project_path), component) or DEFAULT_CLASS


def _next_name(instances: list[dict], base: str) -> str:
    taken = {i["name"] for i in instances}
    n = 1
    while f"{base}_{n:02d}" in taken:
        n += 1
    return f"{base}_{n:02d}"


def _find(instances: list[dict], name: str) -> dict:
    for inst in instances:
        if inst["name"] == name:
            return inst
    raise ValueError(f"instance introuvable : {name}")


def apply_ops(project_path: str | Path, instances: list[dict], ops: list[dict]) -> tuple[list[dict], list[str]]:
    """Apply edit *ops* to a copy of *instances*. Returns (instances, warnings).

    ops: {"op": "add", "component", "count"=1, "version"="LAST"} |
         {"op": "remove", "name"} | {"op": "duplicate", "name"} |
         {"op": "rename", "name", "new_name"} |
         {"op": "relink", "name", "component", "version"="LAST"} |
         {"op": "set_version", "name" | "all": true, "version"}
    """
    project = Path(project_path)
    out = [dict(i) for i in instances]
    warnings: list[str] = []
    for op in ops:
        kind = op.get("op")
        if kind == "add":
            comp = str(op.get("component") or "")
            version = str(op.get("version") or "LAST")
            _require_component(project, comp, version)
            cls = _class_for(project, comp)
            for _ in range(max(1, min(int(op.get("count") or 1), 500))):
                out.append({"name": _next_name(out, sanitize_token(comp)), "class": cls,
                            "component": comp, "version": version})
        elif kind == "remove":
            out.remove(_find(out, str(op.get("name"))))
        elif kind == "duplicate":
            src = _find(out, str(op.get("name")))
            out.append({**src, "name": _next_name(out, sanitize_token(src["component"]))})
        elif kind == "rename":
            inst = _find(out, str(op.get("name")))
            new = str(op.get("new_name") or "")
            if not _PRIM_RE.match(new):
                raise ValueError(f"nom d'instance invalide : {new!r}")
            if any(i["name"] == new for i in out if i is not inst):
                raise ValueError(f"instance deja existante : {new}")
            warnings.append(f"{inst['name']} renomme en {new} : un placement publie vise l'ancien chemin")
            inst["name"] = new
        elif kind == "relink":
            inst = _find(out, str(op.get("name")))
            comp = str(op.get("component") or "")
            version = str(op.get("version") or "LAST")
            _require_component(project, comp, version)
            inst.update(component=comp, version=version)
        elif kind == "set_version":
            version = str(op.get("version") or "LAST")
            targets = out if op.get("all") else [_find(out, str(op.get("name")))]
            for inst in targets:
                _require_component(project, inst["component"], version)
                inst["version"] = version
        else:
            raise ValueError(f"operation inconnue : {kind!r}")
    return out, warnings


def _layout_warnings(project_path: Path, name: str, instances: list[dict]) -> list[str]:
    """Layout overs on prims that no longer exist (renamed / removed instance)."""
    from pxr import Sdf

    layout = layout_file(project_path, name)
    if layout is None:
        return []
    layer = Sdf.Layer.FindOrOpen(str(layout))
    if layer is None:
        return []
    live = {f"/{name}/{i['class']}/{i['name']}" for i in instances}
    out: list[str] = []

    def _walk(spec, depth):
        for child in spec.nameChildren:
            if depth == 2 and child.path.pathString not in live:
                out.append(f"placement orphelin dans le layout : {child.path.pathString}")
            elif depth < 2:
                _walk(child, depth + 1)

    root = layer.GetPrimAtPath(Sdf.Path(f"/{name}"))
    if root is not None:
        _walk(root, 1)
    return out


# ── authoring ────────────────────────────────────────────────────────────────

def _author(folder: Path, project: Path, name: str, version: str, instances: list[dict]) -> Path:
    from pxr import Sdf

    folder.mkdir(parents=True, exist_ok=True)

    contents_path = folder / f"{name}_contents{ASSEMBLY_EXT}"
    contents = Sdf.Layer.CreateNew(str(contents_path))
    root = Sdf.PrimSpec(contents, name, Sdf.SpecifierDef, "Xform")
    root.kind = "assembly"
    groups: dict[str, Sdf.PrimSpec] = {}
    for inst in instances:
        cls = sanitize_token(inst["class"]) or DEFAULT_CLASS
        group = groups.get(cls)
        if group is None:
            group = groups[cls] = Sdf.PrimSpec(root, cls, Sdf.SpecifierDef, "Xform")
            group.kind = "group"
        target = _component_target(project, inst["component"], inst["version"])
        prim = Sdf.PrimSpec(group, inst["name"], Sdf.SpecifierDef, "Xform")
        prim.kind = "component"
        prim.instanceable = True
        prim.referenceList.prependedItems = [Sdf.Reference(_rel(target, folder))]
    contents.defaultPrim = name
    contents.Save()

    payload_path = folder / f"{name}_payload{ASSEMBLY_EXT}"
    payload = Sdf.Layer.CreateNew(str(payload_path))
    layout = layout_file(project, name)
    subs = ([_rel(layout, folder)] if layout is not None else []) + [f"./{contents_path.name}"]
    payload.subLayerPaths[:] = subs
    payload.defaultPrim = name
    payload.Save()

    entry_path = folder / f"{name}{ASSEMBLY_EXT}"
    entry = Sdf.Layer.CreateNew(str(entry_path))
    top = Sdf.PrimSpec(entry, name, Sdf.SpecifierDef, "Xform")
    top.kind = "assembly"
    top.assetInfo = {"name": name, "version": version,
                     "identifier": Sdf.AssetPath(f"./{entry_path.name}")}
    top.payloadList.prependedItems = [Sdf.Payload(f"./{payload_path.name}")]
    entry.defaultPrim = name
    entry.customLayerData = {"flux": {
        "assembly": name, "version": version,
        # A JSON string: USD dictionaries cannot hold a list of dictionaries.
        "instances_json": json.dumps([{k: str(inst[k]) for k in ("name", "class", "component", "version")}
                                      for inst in instances]),
    }}
    entry.Save()
    return entry_path


def write_version(project_path: str | Path, name: str, instances: list[dict], *,
                  user: str = "", force: bool = False) -> dict | None:
    """Author a new assembly version for *instances*; None if nothing changed."""
    from features.folder_manager.naming_validator import format_version
    from features.publisher import last_pointer as lp
    from features.publisher.publish_layout import (
        discard_rendered_version, reserve_version, sequence_folder,
    )

    project = Path(project_path)
    _check_name(name)
    parent = assembly_dir(project, name)
    if not force and current_entry(project, name) is not None and read_instances(project, name) == instances:
        return None
    parent.mkdir(parents=True, exist_ok=True)
    ver = reserve_version(parent, name, ASSEMBLY_EXT)
    folder = sequence_folder(parent, name, ver)
    version = format_version(ver)
    try:
        entry = _author(folder, project, name, version, instances)
    except Exception:
        discard_rendered_version(parent, name, ASSEMBLY_EXT, ver, is_sequence=True)
        raise
    last = lp.write_last(parent, name, ASSEMBLY_EXT, folder, ver, lp.MODE_LAYER, user=user,
                         layer_target=f"{folder.name}/{entry.name}")
    log.info("Assembly %s %s -> %s (%d instances)", name, version, folder, len(instances))
    return {"version": version, "folder": folder, "entry": entry, "last": last,
            "warnings": _layout_warnings(project, name, instances)}


def create_assembly(project_path: str | Path, name: str, *, source: str | None = None,
                    user: str = "") -> dict:
    """New assembly, empty or duplicated from *source* (its current instances)."""
    project = Path(project_path)
    _check_name(name)
    if current_entry(project, name) is not None or (assembly_root(project) / f"{name}{ASSEMBLY_EXT}").is_file():
        raise ValueError(f"l'assembly {name} existe deja")
    instances = read_instances(project, source) if source else []
    return write_version(project, name, instances, user=user, force=True)


def edit_assembly(project_path: str | Path, name: str, ops: list[dict], *, user: str = "") -> dict:
    """Apply *ops* and write a new version. A legacy flat assembly is converted."""
    project = Path(project_path)
    current = read_instances(project, name)
    legacy = current_entry(project, name) is None
    instances, warnings = apply_ops(project, current, ops)
    res = write_version(project, name, instances, user=user, force=legacy)
    if res is None:
        return {"version": None, "warnings": warnings, "unchanged": True}
    res["warnings"] = warnings + res["warnings"]
    return res
