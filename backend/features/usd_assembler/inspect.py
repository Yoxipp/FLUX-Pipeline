# inspect.py — read-only composition of a published USD entry, for the FLUX USD page
# (Solaris Stage Manager / AYON scene inventory feel): what prims the file really
# gives, their type, kind, variants, references, and which layers are used.
#
# Never edits anything. Bounded (depth + children) so a 300 asset set stays instant:
# instanced prims are not traversed (their content is the component's own tree).

from __future__ import annotations

import os
from pathlib import Path

from core.logger import get_logger

log = get_logger("usd_assembler.inspect")

MAX_DEPTH = 6
MAX_CHILDREN = 60


def _rel(path: str, start: Path) -> str:
    try:
        return os.path.relpath(path, str(start)).replace(os.sep, "/")
    except (ValueError, TypeError):
        return str(path)


def _under(identifier: str, folder: Path) -> bool:
    try:
        return Path(identifier).resolve().is_relative_to(folder.resolve())
    except (OSError, ValueError):
        return False


def _arcs(prim, local_layers: set[str]) -> list[dict]:
    """References and payloads authored on *prim* BY THE FILE BEING INSPECTED
    (*local_layers* = its own layer stack), not by the assets it pulls in."""
    out: list[dict] = []
    for spec in prim.GetPrimStack():
        if spec.layer.identifier not in local_layers:
            continue
        for item in list(spec.referenceList.GetAddedOrExplicitItems()):
            out.append({"arc": "reference", "asset": item.assetPath,
                        "prim": item.primPath.pathString})
        for item in list(spec.payloadList.GetAddedOrExplicitItems()):
            out.append({"arc": "payload", "asset": item.assetPath,
                        "prim": item.primPath.pathString})
    seen, unique = set(), []
    for arc in out:
        key = (arc["arc"], arc["asset"], arc["prim"])
        if key not in seen:
            seen.add(key)
            unique.append(arc)
    return unique[:4]


def _node(prim, depth: int, local_layers: set[str]) -> dict:
    from pxr import Usd

    vsets = {}
    for name in prim.GetVariantSets().GetNames():
        vset = prim.GetVariantSet(name)
        vsets[name] = {"selection": vset.GetVariantSelection(),
                       "variants": sorted(vset.GetVariantNames())}
    node = {
        "path": prim.GetPath().pathString,
        "name": prim.GetName(),
        "type": prim.GetTypeName() or "",
        "kind": Usd.ModelAPI(prim).GetKind() or "",
        "purpose": "",
        "instanceable": bool(prim.IsInstanceable()),
        "variant_sets": vsets,
        "arcs": _arcs(prim, local_layers),
        "children": [],
        "truncated": False,
    }
    try:
        from pxr import UsdGeom

        if prim.IsA(UsdGeom.Imageable):
            node["purpose"] = str(UsdGeom.Imageable(prim).GetPurposeAttr().Get() or "")
    except Exception:       # pragma: no cover - schema guard
        pass
    if prim.IsInstance() or depth >= MAX_DEPTH:
        # An instance hides its content (it lives in the referenced component) and a
        # depth cut hides children: both are shown as "..." by the UI.
        node["truncated"] = prim.IsInstance() or bool(prim.GetChildren())
        return node
    children = list(prim.GetChildren())
    for child in children[:MAX_CHILDREN]:
        node["children"].append(_node(child, depth + 1, local_layers))
    node["truncated"] = len(children) > MAX_CHILDREN
    return node


def composition(file: str | Path) -> dict:
    """{"file", "default_prim", "layers": [{"path", "root"}], "tree": node | None}.

    *file* is a published USD entry (component, assembly, department layer...).
    """
    from pxr import Usd

    path = Path(str(file))
    if not path.is_file():
        raise ValueError(f"fichier USD introuvable : {path}")
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise ValueError(f"USD illisible : {path.name}")

    root = stage.GetDefaultPrim()
    if not root:
        children = [p for p in stage.GetPseudoRoot().GetChildren() if p.IsDefined()]
        root = children[0] if children else None

    root_id = stage.GetRootLayer().identifier
    # "Local" = the entity's own files (entry, payload, department / contents layers,
    # layout), which live in its folder; everything else is an asset it pulls in.
    own = path.parent.parent if path.parent.parent.is_dir() else path.parent
    local_layers = {layer.identifier for layer in stage.GetUsedLayers(includeClipLayers=False)
                    if not layer.anonymous and _under(layer.identifier, own)}
    layers = [{"path": _rel(layer.identifier, path.parent), "root": layer.identifier == root_id}
              for layer in stage.GetUsedLayers(includeClipLayers=False)
              if not layer.anonymous]
    layers.sort(key=lambda entry: (not entry["root"], entry["path"]))
    return {"file": str(path), "default_prim": root.GetName() if root else "",
            "layers": layers, "tree": _node(root, 0, local_layers) if root else None}
