# component_auto.py — automatic USD component, regenerated after a layer publish
# (USD_ASSEMBLER_V2 step A1). Each department publish (GEO, RIG, SHADING) is its own
# layered publish with its own base token (CLASS_TYPE_NAME_INSTANCE), so the slots
# cannot simply be sublayered: each one is referenced with an explicit prim path and
# remapped onto /<NAME>. Output, beside the asset's department folders:
#   <NAME_path>/usd/<NAME>_vNNN/<NAME>.usda          entry: defaultPrim, kind=component,
#                                                    assetInfo, payload -> ./<NAME>_payload.usda
#   <NAME_path>/usd/<NAME>_vNNN/<NAME>_payload.usda  /<NAME> references look > skel > model
#   <NAME_path>/usd/<NAME>_LAST.usda                 pointer layer (ADR 0017)
# Paths are relative (ADR 0010). anim / cam / light are shot layers, never in a component.

from __future__ import annotations

import os
from pathlib import Path

from core.logger import get_logger

from .resolve.base import ResolveError
from .resolve.flux_resolver import FluxResolver
from .structure.naming import sanitize_token

log = get_logger("usd_assembler.component_auto")

COMPONENT_EXT = ".usda"
COMPONENT_SUBDIR = "usd"

# slot -> ordered (TYPE task, layer kind) sources; first published source wins.
# Strong -> weak order of the payload references is the dict order.
SLOT_SOURCES: dict[str, tuple[tuple[str, str], ...]] = {
    "look": (("SHADING", "look"),),
    "skel": (("RIG", "skel"), ("GEO", "skel")),
    "model": (("GEO", "model"), ("RIG", "model")),
}
COMPONENT_TASKS = frozenset(task for sources in SLOT_SOURCES.values() for task, _ in sources)
_DEFAULT_INSTANCE = "null"


def _rel(path: Path, start: Path) -> str:
    """*path* relative to *start* (forward slashes); absolute posix across drives."""
    try:
        return os.path.relpath(str(path), str(start)).replace(os.sep, "/")
    except ValueError:
        return Path(path).as_posix()


def _resolve_slot(resolver: FluxResolver, name: str, sources, instance: str):
    for task, layer in sources:
        for inst in dict.fromkeys((instance, "")):
            try:
                return task, resolver.resolve_layer(name, task, layer, "latest", instance=inst)
            except ResolveError:
                continue
    return None


def component_dir(project_path: str | Path, name: str) -> Path | None:
    """``<project>/<NAME_path>/usd`` or None when *name* has no NAME token."""
    from features.folder_manager.tokens import get_path_for_token, load_tokens

    project = Path(project_path)
    name_rel = get_path_for_token(load_tokens(project), "NAME", name)
    return project / name_rel / COMPONENT_SUBDIR if name_rel is not None else None


def collect_slots(project_path: str | Path, name: str,
                  instance: str = _DEFAULT_INSTANCE,
                  pins: dict[str, dict] | None = None) -> dict[str, dict]:
    """Return {slot: {"task", "path": Path, "prim", "version"[, "pin"]}} for published slots.

    *pins* fixes a slot by hand: ``{"task", "instance", "version"}`` (version ``latest``
    keeps following that task's LAST) or ``{"exclude": True}`` to leave the slot out.
    A pin that no longer resolves raises ResolveError (never silently replaced).
    """
    resolver = FluxResolver(project_path)
    slots: dict[str, dict] = {}
    for slot, sources in SLOT_SOURCES.items():
        pin = (pins or {}).get(slot)
        if pin and pin.get("exclude"):
            continue
        if pin:
            resolved = resolver.resolve_layer(name, pin["task"], slot, pin.get("version") or "latest",
                                              instance=pin.get("instance") or "")
            task = pin["task"]
        else:
            hit = _resolve_slot(resolver, name, sources, instance)
            if hit is None:
                continue
            task, resolved = hit
        slots[slot] = {"task": task, "path": Path(resolved.path),
                       "prim": resolved.default_prim, "version": resolved.version}
        if pin:
            slots[slot]["pin"] = _clean_pin(pin)
    return slots


def _clean_pin(pin: dict) -> dict:
    if pin.get("exclude"):
        return {"exclude": True}
    return {"task": str(pin["task"]), "instance": str(pin.get("instance") or ""),
            "version": str(pin.get("version") or "latest")}


def _slot_signature(slots: dict[str, dict], folder_depth_ref: Path) -> dict[str, dict]:
    """Relative, comparable description of *slots* (stored in customLayerData)."""
    out = {}
    for slot, s in slots.items():
        out[slot] = {"task": s["task"], "path": _rel(s["path"], folder_depth_ref),
                     "prim": s["prim"], "version": s["version"]}
        if s.get("pin"):
            out[slot]["pin"] = dict(s["pin"])
    return out


def _current_signature(parent: Path, name: str) -> dict | None:
    from features.publisher.publish_layout import highest_sequence_version, sequence_folder

    ver = highest_sequence_version(parent, name, COMPONENT_EXT)
    if ver <= 0:
        return None
    entry = sequence_folder(parent, name, ver) / f"{name}{COMPONENT_EXT}"
    if not entry.is_file():
        return None
    from pxr import Sdf

    layer = Sdf.Layer.OpenAsAnonymous(str(entry))
    if layer is None:
        return None
    flux = dict(layer.customLayerData).get("flux", {})
    slots = flux.get("slots") if isinstance(flux, dict) else None
    return {k: {kk: (dict(vv) if hasattr(vv, "keys") else vv) for kk, vv in dict(v).items()}
            for k, v in slots.items()} if slots else None


def _current_pins(parent: Path, name: str) -> dict[str, dict]:
    """Pins of the latest component version, excluded slots included."""
    current = _current_signature(parent, name) or {}
    pins = {slot: dict(s["pin"]) for slot, s in current.items() if s.get("pin")}
    from pxr import Sdf
    from features.publisher.publish_layout import highest_sequence_version, sequence_folder

    ver = highest_sequence_version(parent, name, COMPONENT_EXT)
    entry = sequence_folder(parent, name, ver) / f"{name}{COMPONENT_EXT}" if ver > 0 else None
    if entry is not None and entry.is_file():
        layer = Sdf.Layer.OpenAsAnonymous(str(entry))
        flux = dict(layer.customLayerData).get("flux", {}) if layer is not None else {}
        for slot in filter(None, str(flux.get("excluded") or "").split(",")):
            pins[str(slot)] = {"exclude": True}
    return pins


def _stage_metadata(model_path: Path) -> dict:
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(str(model_path))
    if layer is None:
        return {}
    meta = {}
    for key in ("metersPerUnit", "upAxis"):
        if layer.pseudoRoot.HasInfo(key):
            meta[key] = layer.pseudoRoot.GetInfo(key)
    return meta


def _author(folder: Path, name: str, token: str, version: str,
            slots: dict[str, dict], signature: dict[str, dict],
            excluded: list[str] | None = None) -> Path:
    """Write entry + payload layers into the (reserved, empty) version *folder*."""
    from pxr import Sdf

    folder.mkdir(parents=True, exist_ok=True)
    meta = _stage_metadata(slots["model"]["path"]) if "model" in slots else {}

    payload_path = folder / f"{name}_payload{COMPONENT_EXT}"
    payload = Sdf.Layer.CreateNew(str(payload_path))
    prim = Sdf.PrimSpec(payload, token, Sdf.SpecifierDef)
    prim.referenceList.prependedItems = [
        Sdf.Reference(_rel(slots[s]["path"], folder), Sdf.Path(f"/{slots[s]['prim']}"))
        for s in SLOT_SOURCES if s in slots
    ]
    payload.defaultPrim = token
    for key, value in meta.items():
        payload.pseudoRoot.SetInfo(key, value)
    payload.Save()

    entry_path = folder / f"{name}{COMPONENT_EXT}"
    entry = Sdf.Layer.CreateNew(str(entry_path))
    root = Sdf.PrimSpec(entry, token, Sdf.SpecifierDef)   # typeless: slot types come through
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
    """(Re)generate the component of asset *name* from its latest published slots.

    Pins of the previous version are kept (a publish never undoes a manual choice).
    *pins* edits them: ``{slot: {"task", "instance", "version"}}`` pins a slot,
    ``{slot: {"exclude": True}}`` removes it, ``{slot: None}`` goes back to automatic.
    Returns {"version", "folder", "entry", "last", "slots"} for a new version, or
    None when nothing is published or the slots did not change (no new version).
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
    for slot, pin in (pins or {}).items():
        if slot not in SLOT_SOURCES:
            raise ValueError(f"unknown component slot '{slot}'")
        if pin is None:
            merged.pop(slot, None)
        elif pin.get("exclude") and slot == "model":
            raise ValueError("the model slot cannot be removed")
        else:
            merged[slot] = _clean_pin(pin)
    slots = collect_slots(project_path, name, instance, merged)
    if "model" not in slots:
        log.info("Component %s skipped: no GEO/RIG model published", name)
        return None
    excluded = sorted(s for s, p in merged.items() if p.get("exclude"))

    # The version folder is always one level under parent: same relative strings.
    signature = _slot_signature(slots, parent / f"{name}_v000")
    if _current_signature(parent, name) == signature and sorted(
            s for s, p in _current_pins(parent, name).items() if p.get("exclude")) == excluded:
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

    Only GEO / RIG / SHADING feed a component. Never raises: a component failure must
    not fail the publish that triggered it.
    """
    from features.folder_manager.naming_validator import parse_filename

    try:
        parsed = parse_filename(f"{base}{COMPONENT_EXT}")
        if not parsed or parsed.get("is_shot"):
            return None
        if str(parsed.get("TYPE", "")).upper() not in COMPONENT_TASKS:
            return None
        return refresh_component(project_path, parsed["NAME"], user=user,
                                 instance=parsed.get("INSTANCE") or _DEFAULT_INSTANCE)
    except Exception as exc:
        log.warning("Component refresh failed for %s: %s", base, exc)
        return None
