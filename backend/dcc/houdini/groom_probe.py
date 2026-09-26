"""
groom_probe.py - why a groom shows through an Asset Reference but not through FLUX Import
(2026-09-26, UTAH procedural grooms + Preview Procedurals).

Standalone, read only: the maintainer runs it in Houdini's Python Shell, it compares the stage of
two LOP nodes and writes the report to %TEMP%/flux_groom_probe.txt (and the console).

    exec(open("C:/<FLUX>/backend/dcc/houdini/groom_probe.py", encoding="utf-8").read())
    flux_groom_probe("/stage/assetreference1", "/stage/flux_import_UTAH")

For every groom-looking prim (Houdini procedural API, BasisCurves, "groom" in its path) of
each node: type, applied schemas, purpose / active / visibility, the layers that speak for
it (the FLUX proxy layer shows here), every relationship target and every string / token /
asset value that looks like a prim path, and whether it still exists in that stage (a
reference remaps relationships, never prim paths stored as text). Nothing is changed.
"""

import os
import tempfile

REPORT_PATH = os.path.join(tempfile.gettempdir(), "flux_groom_probe.txt")
_MAX_PRIMS = 60


def _out(fh, msg=""):
    fh.write(msg + "\n")
    print(msg)


def _is_groom(prim):
    schemas = " ".join(prim.GetAppliedSchemas()).lower()
    return ("procedural" in schemas or prim.GetTypeName() in ("BasisCurves", "HoudiniProceduralAPI")
            or "groom" in str(prim.GetPath()).lower() or "procedural" in prim.GetTypeName().lower())


def _path_like(value):
    """Prim paths hidden in a value (string, token, asset path, arrays of them)."""
    vals = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for v in vals:
        text = getattr(v, "path", None) or str(v)
        if text.startswith("/") and " " not in text and len(text) < 300:
            out.append(text)
    return out


def _describe(fh, stage, prim):
    from pxr import Sdf, UsdGeom

    img = UsdGeom.Imageable(prim)
    purpose = img.GetPurposeAttr().Get() if img else None
    vis = img.GetVisibilityAttr().Get() if img else None
    _out(fh, "  %s  type=%s  schemas=%s  purpose=%s  active=%s  visibility=%s  children=%d" % (
        prim.GetPath(), prim.GetTypeName() or "-", list(prim.GetAppliedSchemas()) or "-", purpose,
        prim.IsActive(), vis, len(prim.GetChildren())))
    layers = []
    for spec in prim.GetPrimStack():
        name = os.path.basename(spec.layer.identifier) if spec.layer else "?"
        if name not in layers:
            layers.append(name)
    _out(fh, "    layers: %s" % ", ".join(layers[:8]))
    for rel in prim.GetRelationships():
        for target in rel.GetTargets():
            ok = stage.GetPrimAtPath(target.GetPrimPath()).IsValid()
            _out(fh, "    rel %s -> %s %s" % (rel.GetName(), target, "OK" if ok else "INTROUVABLE"))
    for attr in prim.GetAttributes():
        tname = str(attr.GetTypeName())
        if not any(k in tname for k in ("string", "token", "asset")):
            continue
        try:
            value = attr.Get()
        except Exception:  # noqa: BLE001
            continue
        if value is None:
            continue
        for text in _path_like(value):
            try:
                ok = stage.GetPrimAtPath(Sdf.Path(text.split(".")[0])).IsValid()
            except Exception:  # noqa: BLE001 - not a prim path after all
                continue
            _out(fh, "    attr %s = %s %s" % (attr.GetName(), text, "OK" if ok else "INTROUVABLE (chemin en texte)"))


def _probe_node(fh, node_path):
    import hou

    node = hou.node(node_path)
    if node is None:
        _out(fh, "node introuvable : %s" % node_path)
        return
    stage = node.stage()
    if stage is None:
        _out(fh, "%s : pas de stage (erreur du node ?) %s" % (node_path, node.errors()))
        return
    _out(fh, "=" * 70)
    _out(fh, "%s  (%s)" % (node_path, node.type().name()))
    if node.errors() or node.warnings():
        _out(fh, "  erreurs=%s warnings=%s" % (node.errors(), node.warnings()))
    grooms = [p for p in stage.TraverseAll() if _is_groom(p)]
    _out(fh, "%d prim(s) groom" % len(grooms))
    for prim in grooms[:_MAX_PRIMS]:
        _describe(fh, stage, prim)
    if len(grooms) > _MAX_PRIMS:
        _out(fh, "  ... %d de plus" % (len(grooms) - _MAX_PRIMS))


def flux_groom_probe(reference_node="/stage/assetreference1", flux_node="/stage/flux_import_UTAH"):
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        for path in (reference_node, flux_node):
            try:
                _probe_node(fh, path)
            except Exception as exc:  # noqa: BLE001
                _out(fh, "%s : erreur %r" % (path, exc))
        _out(fh, "rapport : %s" % REPORT_PATH)
