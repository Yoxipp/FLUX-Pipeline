# component_auto.py — automatic USD asset (component), regenerated after a department
# publish (USD_ASSEMBLER_V2 A1, ADR 0018 location, ADR 0019 structure: AYON contribution
# workflow + SideFX Component Builder). Output, beside the asset's department folders:
#   <NAME_path>/usd/<NAME>_vNNN/<NAME>.usda          entry: defaultPrim, kind=component,
#                                                    assetInfo, payload -> ./<NAME>_payload.usda
#   <NAME_path>/usd/<NAME>_vNNN/<NAME>_payload.usda  def /<NAME>, sublayers the department
#                                                    layers strong -> weak (rig > look > model)
#   <NAME_path>/usd/<NAME>_vNNN/<NAME>_<dept>.usda   over /<NAME> + variantSet "<dept>":
#                                                    one variant per INSTANCE, referencing that
#                                                    instance's published root (concrete vNNN)
#   <NAME_path>/usd/<NAME>_LAST.usda                 pointer layer (ADR 0017)
# Paths are relative (ADR 0010). anim / cam / light are shot layers, never in a component.

from __future__ import annotations

import os
import re
from pathlib import Path

from core.logger import get_logger

from .resolve.base import ResolveError
from .resolve.flux_resolver import FluxResolver
from .structure.naming import sanitize_token

log = get_logger("usd_assembler.component_auto")

COMPONENT_EXT = ".usda"
COMPONENT_SUBDIR = "usd"
_DEFAULT_INSTANCE = "null"
_VERSION_RE = re.compile(r"v\d+")


def _departments() -> dict[str, str]:
    """{department: TYPE task}, strong -> weak (ADR 0019 order)."""
    from features.usd_export.departments import ASSET_DEPARTMENTS, DEPARTMENT_ORDER

    by_dept = {dept: task for task, dept in ASSET_DEPARTMENTS.items()}
    return {d: by_dept[d] for d in sorted(by_dept, key=lambda d: -DEPARTMENT_ORDER[d])}


DEPARTMENTS: dict[str, str] = _departments()
COMPONENT_TASKS = frozenset(DEPARTMENTS.values())


def _rel(path: Path, start: Path) -> str:
    """*path* relative to *start* (forward slashes); absolute posix across drives."""
    try:
        return os.path.relpath(str(path), str(start)).replace(os.sep, "/")
    except ValueError:
        return Path(path).as_posix()


def component_dir(project_path: str | Path, name: str) -> Path | None:
    """``<project>/<NAME_path>/usd`` or None when *name* has no NAME token."""
    from features.folder_manager.tokens import get_path_for_token, load_tokens

    project = Path(project_path)
    name_rel = get_path_for_token(load_tokens(project), "NAME", name)
    return project / name_rel / COMPONENT_SUBDIR if name_rel is not None else None


def _variant_name(instance: str) -> str:
    return sanitize_token(instance) or _DEFAULT_INSTANCE


def collect_slots(project_path: str | Path, name: str,
                  instance: str = _DEFAULT_INSTANCE,
                  pins: dict[str, dict] | None = None) -> dict[str, dict]:
    """Published departments of asset *name*.

    Returns {dept: {"task", "default", "variants": {variant: {"instance", "path": Path,
    "prim", "version"}}, "version" (default variant's)[, "pin"]}}.
    *pins* per department: ``{"instance", "version"}`` picks the default variant and
    freezes it on a vNNN (``latest`` follows its LAST), ``{"exclude": True}`` drops the
    department. A frozen version that no longer resolves raises ResolveError.
    *instance* is the preferred default variant when no pin says otherwise.
    """
    resolver = FluxResolver(project_path)
    slots: dict[str, dict] = {}
    for dept, task in DEPARTMENTS.items():
        pin = (pins or {}).get(dept) or {}
        if pin.get("exclude"):
            continue
        variants: dict[str, dict] = {}
        for inst in resolver.list_instances(name, task):
            frozen = pin.get("version") if pin.get("instance") == inst else None
            try:
                hit = resolver.resolve_root(name, task, frozen or "latest", instance=inst)
            except ResolveError:
                if frozen and frozen != "latest":
                    raise
                continue
            variants[_variant_name(inst)] = {"instance": inst, "path": Path(hit.path),
                                             "prim": hit.default_prim, "version": hit.version}
        if pin.get("instance") and _variant_name(pin["instance"]) not in variants:
            raise ResolveError(f"{dept}: instance epinglee introuvable : {pin['instance']}")
        if not variants:
            continue
        wanted = [_variant_name(v) for v in (pin.get("instance"), instance, _DEFAULT_INSTANCE) if v]
        default = next((v for v in wanted if v in variants), sorted(variants)[0])
        slots[dept] = {"task": task, "default": default, "variants": variants,
                       "version": variants[default]["version"]}
        if pin:
            slots[dept]["pin"] = _clean_pin(pin)
    return slots


def _clean_pin(pin: dict) -> dict:
    if pin.get("exclude"):
        return {"exclude": True}
    version = str(pin.get("version") or "latest")
    if version != "latest" and not _VERSION_RE.fullmatch(version):
        raise ValueError(f"version invalide : {version!r}")
    return {"instance": str(pin.get("instance") or ""), "version": version}


def _slot_signature(slots: dict[str, dict], folder_depth_ref: Path) -> dict[str, dict]:
    """Relative, comparable description of *slots* (stored in customLayerData)."""
    out = {}
    for dept, s in slots.items():
        out[dept] = {
            "task": s["task"], "default": s["default"], "version": s["version"],
            "variants": {v: {"instance": d["instance"], "path": _rel(d["path"], folder_depth_ref),
                             "prim": d["prim"], "version": d["version"]}
                         for v, d in sorted(s["variants"].items())},
        }
        if s.get("pin"):
            out[dept]["pin"] = dict(s["pin"])
    return out


def _plain(value):
    """USD dictionaries (VtDictionary) -> plain nested dicts, for comparisons."""
    if hasattr(value, "keys"):
        return {str(k): _plain(value[k]) for k in value.keys()}
    return value


def _latest_entry(parent: Path, name: str) -> Path | None:
    from features.publisher.publish_layout import highest_sequence_version, sequence_folder

    ver = highest_sequence_version(parent, name, COMPONENT_EXT)
    if ver <= 0:
        return None
    entry = sequence_folder(parent, name, ver) / f"{name}{COMPONENT_EXT}"
    return entry if entry.is_file() else None


def _entry_flux(entry: Path | None) -> dict:
    if entry is None:
        return {}
    from pxr import Sdf

    layer = Sdf.Layer.OpenAsAnonymous(str(entry))
    flux = dict(layer.customLayerData).get("flux", {}) if layer is not None else {}
    return _plain(flux) if flux else {}


def _current_signature(parent: Path, name: str) -> dict | None:
    return _entry_flux(_latest_entry(parent, name)).get("slots") or None


def _current_pins(parent: Path, name: str) -> dict[str, dict]:
    """Pins of the latest component version, excluded departments included.
    Pins of the pre-0019 layout (slot "skel", pin "task") are dropped."""
    flux = _entry_flux(_latest_entry(parent, name))
    pins = {dept: dict(s["pin"]) for dept, s in (flux.get("slots") or {}).items()
            if dept in DEPARTMENTS and s.get("pin") and "task" not in s["pin"]}
    for dept in filter(None, str(flux.get("excluded") or "").split(",")):
        if dept in DEPARTMENTS:
            pins[dept] = {"exclude": True}
    return pins


def _stage_metadata(root_path: Path) -> dict:
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(str(root_path))
    if layer is None:
        return {}
    meta = {}
    for key in ("metersPerUnit", "upAxis"):
        if layer.pseudoRoot.HasInfo(key):
            meta[key] = layer.pseudoRoot.GetInfo(key)
        else:
            for sub in layer.subLayerPaths:          # a publish root sublayers its layers
                sub_layer = Sdf.Layer.FindOrOpenRelativeToLayer(layer, sub)
                if sub_layer is not None and sub_layer.pseudoRoot.HasInfo(key):
                    meta[key] = sub_layer.pseudoRoot.GetInfo(key)
                    break
    return meta


def _author_department(folder: Path, name: str, token: str, dept: str, slot: dict) -> Path:
    from pxr import Sdf

    path = folder / f"{name}_{dept}{COMPONENT_EXT}"
    layer = Sdf.Layer.CreateNew(str(path))
    prim = Sdf.PrimSpec(layer, token, Sdf.SpecifierOver)
    vset = Sdf.VariantSetSpec(prim, dept)
    for variant, data in sorted(slot["variants"].items()):
        spec = Sdf.VariantSpec(vset, variant)
        # Explicit prim: the published root (/<NAME> since ADR 0019, /<base> before)
        # is remapped onto /<NAME>.
        spec.primSpec.referenceList.prependedItems = [
            Sdf.Reference(_rel(data["path"], folder), Sdf.Path(f"/{data['prim']}"))]
    prim.variantSetNameList.prependedItems = [dept]
    prim.variantSelections[dept] = slot["default"]
    layer.defaultPrim = token
    layer.Save()
    return path


def _author(folder: Path, name: str, token: str, version: str,
            slots: dict[str, dict], signature: dict[str, dict],
            excluded: list[str] | None = None) -> Path:
    """Write entry + payload + department layers into the (reserved, empty) version *folder*."""
    from pxr import Sdf

    folder.mkdir(parents=True, exist_ok=True)
    model = slots.get("model")
    meta = _stage_metadata(model["variants"][model["default"]]["path"]) if model else {}

    dept_layers = [_author_department(folder, name, token, dept, slots[dept])
                   for dept in DEPARTMENTS if dept in slots]

    payload_path = folder / f"{name}_payload{COMPONENT_EXT}"
    payload = Sdf.Layer.CreateNew(str(payload_path))
    Sdf.PrimSpec(payload, token, Sdf.SpecifierDef)       # typeless: department types come through
    payload.subLayerPaths[:] = [f"./{p.name}" for p in dept_layers]
    payload.defaultPrim = token
    for key, value in meta.items():
        payload.pseudoRoot.SetInfo(key, value)
    payload.Save()

    entry_path = folder / f"{name}{COMPONENT_EXT}"
    entry = Sdf.Layer.CreateNew(str(entry_path))
    root = Sdf.PrimSpec(entry, token, Sdf.SpecifierDef)
    root.kind = "component"
    root.assetInfo = {"name": name, "version": version,
                      "identifier": Sdf.AssetPath(f"./{entry_path.name}")}
    root.payloadList.prependedItems = [Sdf.Payload(f"./{payload_path.name}")]
    entry.defaultPrim = token
    for key, value in meta.items():
        entry.pseudoRoot.SetInfo(key, value)
    flux = {"component": name, "version": version, "slots": signature}
    if excluded:
        flux["excluded"] = ",".join(excluded)   # a string: USD dicts reject untyped lists
    entry.customLayerData = {"flux": flux}
    entry.Save()
    return entry_path


def refresh_component(project_path: str | Path, name: str, *, user: str = "",
                      instance: str = _DEFAULT_INSTANCE,
                      pins: dict[str, dict | None] | None = None) -> dict | None:
    """(Re)generate the component of asset *name* from its published departments.

    Pins of the previous version are kept (a publish never undoes a manual choice).
    *pins* edits them: ``{dept: {"instance", "version"}}`` pins a department,
    ``{dept: {"exclude": True}}`` removes it, ``{dept: None}`` goes back to automatic.
    Returns {"version", "folder", "entry", "last", "slots"} for a new version, or
    None when no model is published or nothing changed (no new version).
    """
    from features.folder_manager.naming_validator import format_version
    from features.publisher import last_pointer as lp
    from features.publisher.publish_layout import (
        discard_rendered_version, reserve_version, sequence_folder,
    )

    parent = component_dir(project_path, name)
    if parent is None:
        log.warning("Component %s skipped: no NAME token", name)
        return None
    merged = _current_pins(parent, name)
    for dept, pin in (pins or {}).items():
        if dept not in DEPARTMENTS:
            raise ValueError(f"departement inconnu : '{dept}'")
        if pin is None:
            merged.pop(dept, None)
        elif pin.get("exclude") and dept == "model":
            raise ValueError("le departement model ne peut pas etre retire")
        else:
            merged[dept] = _clean_pin(pin)
    slots = collect_slots(project_path, name, instance, merged)
    if "model" not in slots:
        log.info("Component %s skipped: no GEO (model) published", name)
        return None
    excluded = sorted(d for d, p in merged.items() if p.get("exclude"))

    # The version folder is always one level under parent: same relative strings.
    signature = _slot_signature(slots, parent / f"{name}_v000")
    current_excluded = sorted(d for d, p in _current_pins(parent, name).items() if p.get("exclude"))
    if _current_signature(parent, name) == signature and current_excluded == excluded:
        return None

    ver = reserve_version(parent, name, COMPONENT_EXT)
    folder = sequence_folder(parent, name, ver)
    version = format_version(ver)
    token = sanitize_token(name)
    try:
        entry = _author(folder, name, token, version, slots, signature, excluded)
    except Exception:
        discard_rendered_version(parent, name, COMPONENT_EXT, ver, is_sequence=True)
        raise
    last = lp.write_last(parent, name, COMPONENT_EXT, folder, ver, lp.MODE_LAYER, user=user,
                         layer_target=f"{folder.name}/{entry.name}")
    log.info("Component %s %s -> %s (%s)", name, version, folder, ", ".join(slots))
    return {"version": version, "folder": folder, "entry": entry, "last": last,
            "slots": signature}


def refresh_from_publish(project_path: str | Path, base: str, *, user: str = "") -> dict | None:
    """Hook for a layered publish of *base* (CLASS_TYPE_NAME_INSTANCE).

    Only asset department TYPEs (GEO, SHADING, GROOM, RIG) feed a component. Never
    raises: a component failure must not fail the publish that triggered it.
    """
    from features.folder_manager.naming_validator import parse_filename

    try:
        parsed = parse_filename(f"{base}{COMPONENT_EXT}")
        if not parsed or parsed.get("is_shot"):
            return None
        if str(parsed.get("TYPE", "")).upper() not in COMPONENT_TASKS:
            return None
        return refresh_component(project_path, parsed["NAME"], user=user)
    except Exception as exc:
        log.warning("Component refresh failed for %s: %s", base, exc)
        return None
