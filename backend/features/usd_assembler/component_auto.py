# component_auto.py — the USD asset (component) of an asset NAME (ADR 0018 location,
# ADR 0019 department layers, ADR 0023 manual creation + files with targets).
#
# A component is created by hand (create_component) from the departments the artist
# picks; its recipe (component_recipe.py) lists any number of files per department.
# A publish never creates a component: it only re-composes one that exists.
# Output, beside the asset's department folders:
#   <NAME_path>/usd/<NAME>_vNNN/<NAME>.usda          entry: defaultPrim, kind=component,
#                                                    assetInfo, payload, recipe in customLayerData
#   <NAME_path>/usd/<NAME>_vNNN/<NAME>_payload.usda  def /<NAME>, sublayers the department
#                                                    layers strong -> weak (anim > rig > look > model)
#   <NAME_path>/usd/<NAME>_vNNN/<NAME>_<dept>.usda   over /<NAME>, one variantSet per FILE
#                                                    ("on" = its contribution, "off" = nothing),
#                                                    so several files of a department are active
#                                                    at once and each toggles on its own
#   <NAME_path>/usd/<NAME>_LAST.usda                 pointer layer (ADR 0017)
# Paths are relative (ADR 0010). The importer only changes variant selections on its own
# stage: its choices never modify the component.

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from core.logger import get_logger

from . import component_recipe as cr
from .resolve.base import ResolveError
from .resolve.flux_resolver import FluxResolver
from .structure.naming import sanitize_token

log = get_logger("usd_assembler.component_auto")

COMPONENT_EXT = ".usda"
COMPONENT_SUBDIR = "usd"
USD_EXTS = (".usd", ".usda", ".usdc")
ON, OFF = "on", "off"
# Department layer strength (ADR 0019 AYON order) for TYPEs outside ASSET_DEPARTMENTS.
_UNKNOWN_STRENGTH = 150
_ANIM_DEPARTMENT, _ANIM_STRENGTH = "anim", 400   # preview clips bind over the rig


def _rel(path: Path, start: Path) -> str:
    """*path* relative to *start* (forward slashes); absolute posix across drives."""
    try:
        return os.path.relpath(str(path), str(start)).replace(os.sep, "/")
    except ValueError:
        return Path(path).as_posix()


def _plain(value):
    """USD dictionaries (VtDictionary) -> plain nested dicts, for comparisons."""
    if hasattr(value, "keys"):
        return {str(k): _plain(value[k]) for k in value.keys()}
    return value


def component_dir(project_path: str | Path, name: str) -> Path | None:
    """``<project>/<NAME_path>/usd`` or None when *name* has no NAME token."""
    from features.folder_manager.tokens import get_path_for_token, load_tokens

    project = Path(project_path)
    name_rel = get_path_for_token(load_tokens(project), "NAME", name)
    return project / name_rel / COMPONENT_SUBDIR if name_rel is not None else None


def department_layer(task: str) -> tuple[str, int]:
    """(layer name, strength) of a department TYPE token."""
    from features.usd_export.departments import ASSET_DEPARTMENTS, DEPARTMENT_ORDER

    task = task.upper()
    if task == "ANIM":
        return _ANIM_DEPARTMENT, _ANIM_STRENGTH
    dept = ASSET_DEPARTMENTS.get(task) or sanitize_token(task.lower()) or "dept"
    return dept, DEPARTMENT_ORDER.get(dept, _UNKNOWN_STRENGTH)


def available_departments(project_path: str | Path) -> list[str]:
    from features.folder_manager.tokens import load_tokens

    return cr.asset_departments(load_tokens(Path(project_path)))


# ── current version / recipe ─────────────────────────────────────────────────

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


def _json_field(flux: dict, key: str) -> dict:
    raw = flux.get(key)
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return {}


def entry_signature(entry: Path | None) -> dict:
    """Files as composed in a component version: {id: {"path", "prim", "version"}}."""
    return _json_field(_entry_flux(entry), "signature").get("files", {})


def entry_variant_sets(entry: Path | None) -> dict[str, list[str]]:
    """{variant set: [variants]} a component version offers (ADR 0019 + 0023)."""
    flux = _entry_flux(entry)
    sets = _json_field(flux, "variant_sets")
    if sets:
        return {k: list(v) for k, v in sets.items()}
    # Before ADR 0023: one variantSet per department, one variant per instance.
    return {dept: sorted((s.get("variants") or {}).keys())
            for dept, s in (flux.get("slots") or {}).items() if isinstance(s, dict)}


def exists(project_path: str | Path, name: str) -> bool:
    parent = component_dir(project_path, name)
    return parent is not None and _latest_entry(parent, name) is not None


def _legacy_recipe(project_path: str | Path, name: str, flux: dict, available: list[str]) -> dict:
    """Recipe of a component written before ADR 0023 (slots, one variant per instance):
    every published variant becomes a file, the default one active."""
    resolver = FluxResolver(project_path)
    departments: list[str] = []
    files: list[dict] = []
    taken: set[str] = set()
    for slot in (flux.get("slots") or {}).values():
        if not isinstance(slot, dict) or "variants" not in slot:
            continue
        task = str(slot.get("task") or "").upper()
        if task not in available or task in departments:
            continue
        departments.append(task)
        pin = slot.get("pin") or {}
        wanted = {(str(v.get("instance") or ""), str(v.get("variante") or "")): label
                  for label, v in (slot.get("variants") or {}).items()}
        for pub in resolver.list_publish_bases(name, task):
            label = wanted.get((pub["instance"], pub["variante"]))
            if label is None:
                continue
            fid = cr.make_id(f"{task}_{label}", taken)
            taken.add(fid)
            frozen = pin.get("version") if pin.get("instance") == pub["instance"] else None
            files.append({"id": fid, "label": pub["base"], "department": task,
                          "kind": cr.default_kind(task), "source": "publish",
                          "base": pub["base"], "instance": pub["instance"],
                          "variante": pub["variante"], "version": frozen or "latest",
                          "active": label == slot.get("default")})
    return cr.normalize({"departments": departments, "files": files}, available)


def current_recipe(project_path: str | Path, name: str) -> dict | None:
    """Recipe of the latest component version (None when the component does not exist)."""
    parent = component_dir(project_path, name)
    entry = _latest_entry(parent, name) if parent is not None else None
    if entry is None:
        return None
    flux = _entry_flux(entry)
    available = available_departments(project_path)
    recipe = _json_field(flux, "recipe")
    if recipe:
        # Departments removed from the project tokens are dropped, never invented.
        recipe = {"departments": [d for d in recipe.get("departments", []) if d in available],
                  "files": [f for f in recipe.get("files", []) if f.get("department") in available]}
        return cr.normalize(_drop_dangling(recipe), available)
    return _legacy_recipe(project_path, name, flux, available)


def _drop_dangling(recipe: dict) -> dict:
    ids = {f["id"] for f in recipe["files"]}
    for f in recipe["files"]:
        for field in ("targets", "proxy_of", "depends"):
            f[field] = [t for t in f.get(field) or [] if t in ids]
    return recipe


# ── resolution ───────────────────────────────────────────────────────────────

def _project_file(project: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else project / p


def _skeleton_path(path: Path, root: str) -> str:
    """Path of the first Skeleton under /<root> in *path*, relative to it ("" if none)."""
    try:
        from pxr import Usd, UsdSkel

        stage = Usd.Stage.Open(str(path), Usd.Stage.LoadNone)
        for prim in stage.TraverseAll() if stage is not None else []:
            if prim.IsA(UsdSkel.Skeleton):
                parts = prim.GetPath().pathString.strip("/").split("/")
                if parts and (not root or parts[0] == root):
                    return "/".join(parts[1:])
    except Exception as exc:        # noqa: BLE001 - no skeleton = bind on the asset root
        log.info("skeleton of %s unreadable: %s", path, exc)
    return ""


def _has_prim(path: Path, prim: str) -> bool:
    try:
        from pxr import Usd

        stage = Usd.Stage.Open(str(path), Usd.Stage.LoadNone)
        return bool(stage is not None and stage.GetPrimAtPath(prim))
    except Exception:           # noqa: BLE001
        return False


def resolve_files(project_path: str | Path, name: str, recipe: dict) -> tuple[dict[str, dict], list[str]]:
    """{id: {"path": Path, "prim", "version", "skeleton"}} for every file found on disk.

    A publish following its latest version that is missing is skipped with a warning;
    a frozen vNNN that no longer resolves raises ResolveError."""
    from features.publisher.usd_publish_hooks import usable_proxy

    project = Path(project_path)
    resolver = FluxResolver(project)
    proxied = {t for f in recipe["files"] for t in f["proxy_of"]}
    out: dict[str, dict] = {}
    warnings: list[str] = []
    for f in recipe["files"]:
        if f["source"] == "publish":
            try:
                hit = resolver.resolve_root(name, f["department"], f["version"], instance=f["instance"],
                                            base_name=f["base"])
            except ResolveError:
                if f["version"] != "latest":
                    raise
                warnings.append(f"{f['label']} : aucun publish trouve, ignore")
                continue
            path = Path(hit.path)
            # A proxy layer (purpose=proxy) sublayers its source: it wins, unless a file
            # of the component is declared as this one's proxy (ADR 0023 point 5).
            if f["id"] not in proxied:
                path = usable_proxy(path) or path
            out[f["id"]] = {"path": path, "prim": (f["prim"] or hit.default_prim).strip("/"),
                            "version": hit.version}
        else:
            path = _project_file(project, f["path"])
            if not path.is_file():
                warnings.append(f"{f['label']} : fichier introuvable ({f['path']})")
                continue
            prim = f["prim"]
            if not prim and f["format"] in cr.USD_FORMATS:
                from .resolve.flux_resolver import _default_prim

                prim = _default_prim(path)
            out[f["id"]] = {"path": path, "prim": prim.strip("/"), "version": ""}
        if f["kind"] == "rig" and f["format"] in cr.USD_FORMATS:
            out[f["id"]]["skeleton"] = _skeleton_path(out[f["id"]]["path"], out[f["id"]]["prim"])
    return out, warnings


def proposed_files(project_path: str | Path, name: str, recipe: dict) -> list[dict]:
    """Published bases of the component's departments not yet in its recipe."""
    resolver = FluxResolver(project_path)
    used = {(f["department"], f.get("base")) for f in recipe["files"] if f["source"] == "publish"}
    out = []
    for dept in recipe["departments"]:
        for pub in resolver.list_publish_bases(name, dept):
            if (dept, pub["base"]) in used:
                continue
            try:
                hit = resolver.resolve_root(name, dept, "latest", instance=pub["instance"], base_name=pub["base"])
            except ResolveError:
                continue
            out.append({"department": dept, "base": pub["base"], "instance": pub["instance"],
                        "variante": pub["variante"], "version": hit.version,
                        "format": cr.format_of(str(hit.path)), "kind": cr.default_kind(dept)})
    return out


# ── authoring ────────────────────────────────────────────────────────────────

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


def _def(parent, name: str):
    """Existing child spec or a new typeless ``def`` (a def keeps the branch traversable
    even when the file that defines its parents is off)."""
    from pxr import Sdf

    return parent.nameChildren.get(name) or Sdf.PrimSpec(parent, name, Sdf.SpecifierDef)


def _over_path(root, rel: str):
    from pxr import Sdf

    spec = root
    for part in [p for p in rel.split("/") if p]:
        spec = spec.nameChildren.get(part) or Sdf.PrimSpec(spec, part, Sdf.SpecifierOver)
    return spec


def _reference(rel: str, prim: str):
    from pxr import Sdf

    return Sdf.Reference(rel, Sdf.Path(prim)) if prim else Sdf.Reference(rel)


def _author_on(on, token: str, f: dict, res: dict, folder: Path, resolved: dict, by_id: dict) -> None:
    """What the "on" variant of file *f* contributes to /<token>."""
    from pxr import Sdf

    rel = _rel(res["path"], folder)
    root_prim = f"/{res['prim']}" if res["prim"] else ""
    if f["proxy_of"]:
        # A linked proxy lives in /<NAME>/geo/proxy/<id> (where the importers hide proxies
        # in "Geo complete"), purpose=proxy. A FLUX publish brings its render meshes.
        item = _def(_def(_def(on, "geo"), "proxy"), f["id"])
        render = f"{root_prim}/geo/render" if root_prim else ""
        use = render if render and f["format"] in cr.USD_FORMATS and _has_prim(res["path"], render) else root_prim
        item.referenceList.prependedItems = [_reference(rel, use)]
        purpose = Sdf.AttributeSpec(item, "purpose", Sdf.ValueTypeNames.Token, Sdf.VariabilityUniform)
        purpose.default = "proxy"
        return
    if f["kind"] == "animation":
        anim_rel = f"{root_prim}/skel/Anim" if root_prim else ""
        use = anim_rel if anim_rel and f["format"] in cr.USD_FORMATS and _has_prim(res["path"], anim_rel) else root_prim
        item = _def(_def(on, "anims"), f["id"])
        item.referenceList.prependedItems = [_reference(rel, use)]
        # Bound on the skeleton of each TARGET rig only: never on the other rigs.
        for rig in f["targets"]:
            skel = (resolved.get(rig) or {}).get("skeleton", "")
            spec = _over_path(on, skel) if skel else on
            spec.SetInfo("apiSchemas", Sdf.TokenListOp.Create(prependedItems=["SkelBindingAPI"]))
            rel_spec = spec.relationships.get("skel:animationSource") or \
                Sdf.RelationshipSpec(spec, "skel:animationSource", False)
            rel_spec.targetPathList.explicitItems = [Sdf.Path(f"/{token}/anims/{f['id']}")]
        return
    if res["prim"] and res["prim"] != token:
        # A file whose root is not the asset (a manual file): it lands in its own child,
        # never over /<NAME> (that would retype the asset root).
        where = _CHILD_OF_KIND.get(f["kind"], ())
        spec = on
        for part in where:
            spec = _def(spec, part)
        spec = _def(spec, f["id"])
        spec.referenceList.prependedItems = [_reference(rel, root_prim)]
        return
    on.referenceList.prependedItems = [_reference(rel, root_prim)]


# Where a file with its own root prim lands under /<NAME> (Solaris component layout).
_CHILD_OF_KIND: dict[str, tuple[str, ...]] = {
    "geometry": ("geo", "render"), "groom": ("groom",), "shader": ("mtl",),
}


def _author_department(folder: Path, name: str, token: str, dept: str, files: list[dict],
                       resolved: dict, effective: dict[str, bool], by_id: dict) -> Path:
    from pxr import Sdf

    path = folder / f"{name}_{dept}{COMPONENT_EXT}"
    layer = Sdf.Layer.CreateNew(str(path))
    root = Sdf.PrimSpec(layer, token, Sdf.SpecifierOver)
    names = []
    for f in files:
        res = resolved.get(f["id"])
        if res is None:
            continue
        vset = Sdf.VariantSetSpec(root, f["id"])
        Sdf.VariantSpec(vset, OFF)
        _author_on(Sdf.VariantSpec(vset, ON).primSpec, token, f, res, folder, resolved, by_id)
        root.variantSelections[f["id"]] = ON if effective.get(f["id"]) else OFF
        names.append(f["id"])
    root.variantSetNameList.prependedItems = names
    layer.defaultPrim = token
    layer.Save()
    return path


def _signature(recipe: dict, resolved: dict, ref_folder: Path) -> dict:
    return {"recipe": recipe,
            "files": {fid: {"path": _rel(r["path"], ref_folder), "prim": r["prim"], "version": r["version"]}
                      for fid, r in sorted(resolved.items())}}


def _author(folder: Path, name: str, token: str, version: str, recipe: dict,
            resolved: dict, signature: dict) -> tuple[Path, dict[str, list[str]]]:
    """Write entry + payload + department layers into the (reserved, empty) version *folder*."""
    from pxr import Sdf

    folder.mkdir(parents=True, exist_ok=True)
    by_id = {f["id"]: f for f in recipe["files"]}
    effective = cr.effective(recipe)
    meta: dict = {}
    for f in recipe["files"]:
        res = resolved.get(f["id"])
        if res and f["kind"] == "geometry" and f["format"] in cr.USD_FORMATS:
            meta = _stage_metadata(res["path"])
            break

    by_dept: dict[str, list[dict]] = {}
    for f in recipe["files"]:
        by_dept.setdefault(f["department"], []).append(f)
    layers = []
    for task in recipe["departments"]:
        dept, strength = department_layer(task)
        files = [f for f in by_dept.get(task, []) if f["id"] in resolved]
        if files:
            layers.append((strength, _author_department(folder, name, token, dept, files, resolved,
                                                        effective, by_id)))
    layers.sort(key=lambda sl: -sl[0])

    payload_path = folder / f"{name}_payload{COMPONENT_EXT}"
    payload = Sdf.Layer.CreateNew(str(payload_path))
    Sdf.PrimSpec(payload, token, Sdf.SpecifierDef)       # typeless: department types come through
    payload.subLayerPaths[:] = [f"./{p.name}" for _, p in layers]
    payload.defaultPrim = token
    for key, value in meta.items():
        payload.pseudoRoot.SetInfo(key, value)
    payload.Save()

    variant_sets = {fid: [OFF, ON] for fid in resolved}
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
    # JSON strings: USD dictionaries reject untyped / empty lists.
    entry.customLayerData = {"flux": {
        "component": name, "version": version, "manual": True,
        "recipe": json.dumps(recipe, sort_keys=True),
        "signature": json.dumps(signature, sort_keys=True),
        "variant_sets": json.dumps(variant_sets, sort_keys=True),
    }}
    entry.Save()
    return entry_path, variant_sets


def _compose(project_path: str | Path, name: str, recipe: dict, *, user: str = "",
             force: bool = False, note: str = "") -> dict | None:
    """Write a new component version from *recipe* (normalized). None when nothing changed."""
    from features.folder_manager.naming_validator import format_version
    from features.publisher import last_pointer as lp
    from features.publisher.publish_layout import (
        discard_rendered_version, reserve_version, sequence_folder,
    )

    parent = component_dir(project_path, name)
    if parent is None:
        raise ValueError(f"asset inconnu : {name}")
    resolved, warnings = resolve_files(project_path, name, recipe)
    # The version folder is always one level under parent: same relative strings.
    signature = _signature(recipe, resolved, parent / f"{name}_v000")
    previous = _json_field(_entry_flux(_latest_entry(parent, name)), "signature")
    if not force and previous == json.loads(json.dumps(signature, sort_keys=True)):
        return None

    ver = reserve_version(parent, name, COMPONENT_EXT)
    folder = sequence_folder(parent, name, ver)
    version = format_version(ver)
    token = sanitize_token(name)
    try:
        entry, variant_sets = _author(folder, name, token, version, recipe, resolved, signature)
    except Exception:
        discard_rendered_version(parent, name, COMPONENT_EXT, ver, is_sequence=True)
        raise
    last = lp.write_last(parent, name, COMPONENT_EXT, folder, ver, lp.MODE_LAYER, user=user,
                         layer_target=f"{folder.name}/{entry.name}")
    # Same history as a publish (read by the Folder Manager note panel).
    from features.publisher.modif_log import append_log

    files = ", ".join(f"{fid} {r['version']}".strip() for fid, r in resolved.items()) or "aucun fichier"
    append_log(parent, name, version, f"{note or 'asset USD'} : {files}", user or "flux")
    log.info("Component %s %s -> %s (%d file(s))", name, version, folder, len(resolved))
    return {"version": version, "folder": folder, "entry": entry, "last": last,
            "files": signature["files"], "variant_sets": variant_sets,
            "warnings": warnings + cr.warnings(recipe)}


def _check_asset(project_path: str | Path, name: str) -> Path:
    parent = component_dir(project_path, name)
    if parent is None:
        raise ValueError(f"asset inconnu : {name} (pas de token NAME)")
    from .assembly_v2 import _entry_in, _kind_of

    if _kind_of(_entry_in(parent, name)) == "assembly":
        # Same folder, same numbering: a decor and a component cannot share a NAME.
        raise ValueError(f"{name} est un decor (assembly), pas un component")
    return parent


def create_component(project_path: str | Path, name: str, departments: list[str], *,
                     user: str = "") -> dict:
    """Create the component of asset *name* by hand (ADR 0023): its departments, no file yet."""
    _check_asset(project_path, name)
    if exists(project_path, name):
        raise ValueError(f"le component {name} existe deja")
    recipe = cr.normalize(cr.empty_recipe(departments), available_departments(project_path))
    return _compose(project_path, name, recipe, user=user, force=True, note="component cree")


def save_component(project_path: str | Path, name: str, recipe: dict, *, user: str = "") -> dict | None:
    """New version from an edited recipe. None when nothing changed."""
    _check_asset(project_path, name)
    if not exists(project_path, name):
        raise ValueError(f"le component {name} n'existe pas : le creer d'abord")
    recipe = cr.normalize(recipe, available_departments(project_path))
    return _compose(project_path, name, recipe, user=user, note="component modifie")


def add_proposed(project_path: str | Path, name: str, departments: list[str] | None = None, *,
                 user: str = "") -> dict | None:
    """"Tout ajouter": every proposed publish joins the component (active).

    *departments* creates the component first when it does not exist yet (the artist's
    explicit choice, ADR 0023). None when nothing changed."""
    if not exists(project_path, name):
        if not departments:
            raise ValueError(f"le component {name} n'existe pas : le creer d'abord")
        create_component(project_path, name, departments, user=user)
    recipe = current_recipe(project_path, name)
    taken = {f["id"] for f in recipe["files"]}
    added: set[str] = set()
    for p in proposed_files(project_path, name, recipe):
        label = p["base"]
        fid = cr.make_id(f"{p['department'].lower()}_{p['instance']}{'_' + p['variante'] if p['variante'] else ''}",
                         taken)
        taken.add(fid)
        added.add(fid)
        recipe["files"].append({"id": fid, "label": label, "department": p["department"],
                                "kind": p["kind"], "source": "publish", "base": p["base"],
                                "instance": p["instance"], "variante": p["variante"],
                                "format": p["format"], "version": "latest"})
    # A shader added this way targets the component's geometries (editable afterwards):
    # without a target it would stay greyed. Animations never get a target by themselves.
    surfaces = [f["id"] for f in recipe["files"] if f["kind"] in ("geometry", "groom")]
    for f in recipe["files"]:
        if f["id"] in added and f["kind"] == "shader" and not f.get("targets"):
            f["targets"] = surfaces
    return save_component(project_path, name, recipe, user=user)


def refresh_component(project_path: str | Path, name: str, *, user: str = "") -> dict | None:
    """Re-compose an EXISTING component from its recipe (latest publishes followed).

    Never creates a component (ADR 0023). None when there is none or nothing changed."""
    parent = component_dir(project_path, name)
    if parent is None or _latest_entry(parent, name) is None:
        log.info("Component %s: none created, publish left alone", name)
        return None
    from .assembly_v2 import _entry_in, _kind_of

    if _kind_of(_entry_in(parent, name)) == "assembly":
        return None
    recipe = current_recipe(project_path, name)
    if recipe is None:
        return None
    return _compose(project_path, name, recipe, user=user, note="asset USD mis a jour")


def refresh_from_publish_folder(dest_folder: str | Path, base: str, ext: str, *,
                                user: str = "") -> dict | None:
    """Hook for any publish writer: a USD publish of *base* in an asset task folder
    updates that asset's component when one was created. The project is the first
    parent holding tokens.json. Never raises."""
    if str(ext).lower() not in USD_EXTS:
        return None
    try:
        folder = Path(dest_folder).resolve()
        project = next((p for p in [folder, *folder.parents] if (p / "tokens.json").is_file()), None)
        if project is None:
            return None
        return refresh_from_publish(project, base, user=user)
    except Exception as exc:
        log.warning("Component refresh failed for %s: %s", base, exc)
        return None


def refresh_from_publish(project_path: str | Path, base: str, *, user: str = "") -> dict | None:
    """Hook for a publish of *base* (CLASS_TYPE_NAME_INSTANCE): re-compose the asset's
    component if it exists and uses that department. Never raises: a component failure
    must not fail the publish that triggered it."""
    from features.folder_manager.naming_validator import parse_filename

    try:
        parsed = parse_filename(f"{base}{COMPONENT_EXT}")
        if not parsed or parsed.get("is_shot"):
            return None
        recipe = current_recipe(project_path, parsed["NAME"])
        if recipe is None or str(parsed.get("TYPE", "")).upper() not in recipe["departments"]:
            return None
        return refresh_component(project_path, parsed["NAME"], user=user)
    except Exception as exc:
        log.warning("Component refresh failed for %s: %s", base, exc)
        return None


# ── what the UI / importer read ──────────────────────────────────────────────

def component_files(project_path: str | Path, name: str, version: str = "LAST",
                    active: dict[str, bool] | None = None) -> dict:
    """Files of a component version for the importer: recipe entries + variant set,
    greyed state and warnings for the *active* toggles (the importer's own state)."""
    parent = component_dir(project_path, name)
    if parent is None:
        raise ValueError(f"asset inconnu : {name}")
    if version in ("", "LAST", "latest"):
        entry = _latest_entry(parent, name)
    elif re.fullmatch(r"v\d+", version):
        entry = parent / f"{name}_{version}" / f"{name}{COMPONENT_EXT}"
        entry = entry if entry.is_file() else None
    else:
        raise ValueError(f"version invalide : {version!r}")
    if entry is None:
        raise ValueError(f"component {name} {version} introuvable")
    flux = _entry_flux(entry)
    recipe = _json_field(flux, "recipe")
    if recipe:
        recipe = cr.normalize(_drop_dangling(recipe), recipe.get("departments", []))
    else:
        recipe = _legacy_recipe(project_path, name, flux, available_departments(project_path))
    sets = entry_variant_sets(entry)
    grey = cr.greyed(recipe, active)
    return {
        "name": name, "version": entry.parent.name.rsplit("_", 1)[-1],
        "legacy": not flux.get("recipe"),
        "files": [{**f, "variant_set": f["id"] if f["id"] in sets else "",
                   "greyed": f["id"] in grey} for f in recipe["files"]],
        "warnings": cr.warnings(recipe, active),
    }
