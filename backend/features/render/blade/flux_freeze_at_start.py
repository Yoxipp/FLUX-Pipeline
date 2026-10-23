"""Freeze a FLUX stage when the farm job starts (first task of a scheduled job).

Started on the blade by Tractor's python (2.7, on every blade), which finds Houdini's own
python and runs this script again with it (no hython, so no Houdini license):
    rmanpy.exe flux_freeze_at_start.py --houdini <HFS> <source.usd> <output.usda>
    -> <HFS>/python3xx/python.exe -I flux_freeze_at_start.py <source.usd> <output.usda>
Any Houdini 20.5 to 22: the python3xx folder is looked up, not assumed. A blade without the
team's Houdini uses its newest Houdini (only paths are rewritten, the version does not matter).

Standalone on purpose: no FLUX import, only pxr (Houdini's, found from sys.executable;
the backend's usd-core when the tests import it). Python 2.7 and 3.

  * <source> may be a LAST pointer: its current vNNN is used.
  * Every layer of the source folder (shot stage: entry, casting, animation) is copied
    next to <output> as <name>_frozen.usda, with each _LAST path replaced by the vNNN it
    points to right now (customLayerData.flux.target, else its first sublayer) and every
    other path made absolute (UNC), so the copies read the same files from anywhere.
  * Same limit as the freeze at submit (features/render/freeze.py): a LAST read deeper
    (department vNNN -> asset LAST) is reported, not frozen.

Exit code 1 when the source cannot be read: Tractor then stops the job before rendering.
"""
from __future__ import print_function

import os
import re
import subprocess
import sys

USD_LAYER_EXTS = (".usd", ".usda", ".usdc")


def _numbers(name):
    return tuple(int(n) for n in re.findall(r"\d+", name))


def houdini_python(hfs):
    """<hfs>/python3xx/python.exe (newest), else the newest Houdini beside hfs. (python, hfs) or (None, None)."""
    def own(folder):
        if not os.path.isdir(folder):
            return None
        pys = [d for d in os.listdir(folder)
               if re.match(r"^python3\d+$", d) and os.path.isfile(os.path.join(folder, d, "python.exe"))]
        return norm(os.path.join(folder, max(pys, key=_numbers), "python.exe")) if pys else None

    found = own(hfs)
    if found:
        return found, norm(hfs)
    parent = os.path.dirname(norm(hfs).rstrip("/"))
    others = [d for d in os.listdir(parent) if d.startswith("Houdini ") and own(os.path.join(parent, d))] \
        if os.path.isdir(parent) else []
    if not others:
        return None, None
    best = os.path.join(parent, max(others, key=_numbers))
    return own(best), norm(best)


def _relaunch(argv):
    """rmanpy ... --houdini <HFS> <source> <output>: run this script with that Houdini's python."""
    hfs, source, output = argv[2], argv[3], argv[4]
    python, used = houdini_python(hfs)
    if python is None:
        print("GEL ECHOUE : aucun Houdini (python3xx) trouve dans %s ni a cote" % hfs)
        return 1
    if norm(used) != norm(hfs):
        print("Houdini %s absent de cette blade : %s utilise" % (hfs, used))
    env = dict((k, v) for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE"))
    sys.stdout.flush()
    return subprocess.call([python, "-I", os.path.abspath(__file__), source, output], env=env)


def _pxr():
    try:
        from pxr import Sdf, UsdUtils
    except ImportError:
        hfs = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
        bin_dir = os.path.join(hfs, "bin")
        if hasattr(os, "add_dll_directory") and os.path.isdir(bin_dir):
            os.add_dll_directory(bin_dir)
        sys.path.insert(0, os.path.join(hfs, "houdini", "python%d.%dlibs" % sys.version_info[:2]))
        from pxr import Sdf, UsdUtils
    return Sdf, UsdUtils


def norm(path):
    return os.path.normpath(path).replace("\\", "/")


def is_last(path):
    return "_LAST" in os.path.splitext(os.path.basename(path))[0]


def last_target(path, Sdf):
    """The vNNN a LAST pointer layer targets, or None."""
    layer = Sdf.Layer.FindOrOpen(path)
    if layer is None:
        return None
    flux = dict(layer.customLayerData).get("flux") or {}
    candidates = [flux.get("target")] + list(layer.subLayerPaths[:1])
    for rel in candidates:
        if rel:
            cand = norm(os.path.join(os.path.dirname(path), rel))
            if os.path.isfile(cand):
                return cand
    return None


def freeze(source, output):
    """Write the frozen copy of *source* at *output*. Returns {"source", "output", "copies", "frozen", "warnings"}."""
    Sdf, UsdUtils = _pxr()
    source, output = norm(source), norm(output)
    if is_last(source):
        target = last_target(source, Sdf)
        if target is None:
            raise RuntimeError("LAST sans cible lisible : %s" % source)
        source = target
    # Case-insensitive keys: Houdini's pxr 0.24 answers "c:/..." for "C:/..." (Windows).
    home = os.path.normcase(os.path.dirname(source))
    out_dir = os.path.dirname(output)
    copies = {}   # normcase(source layer) -> frozen copy
    frozen = {}   # LAST -> vNNN
    warnings = []

    def copy_layer(src, dst):
        copies[os.path.normcase(src)] = dst
        layer = Sdf.Layer.FindOrOpen(src)
        if layer is None:
            raise RuntimeError("couche illisible : %s" % src)

        def remap(asset):
            if not asset:
                return asset
            path = norm(layer.ComputeAbsolutePath(asset))
            if is_last(path):
                target = last_target(path, Sdf)
                if target is None:
                    warnings.append("LAST sans cible, garde tel quel : %s" % path)
                    return path
                frozen[path] = target
                return target
            key = os.path.normcase(path)
            if (os.path.dirname(key) == home and os.path.splitext(key)[1] in USD_LAYER_EXTS
                    and os.path.isfile(path)):
                if key not in copies:
                    stem = os.path.splitext(os.path.basename(path))[0]
                    copy_layer(path, norm(os.path.join(out_dir, stem + "_frozen.usda")))
                return copies[key]
            return path

        copy = Sdf.Layer.CreateAnonymous(".usda")
        copy.TransferContent(layer)
        UsdUtils.ModifyAssetPaths(copy, remap)
        data = dict(copy.customLayerData)
        flux = dict(data.get("flux") or {})
        flux.update({"frozen": True, "frozen_when": "start", "frozen_from": src})
        data["flux"] = flux
        copy.customLayerData = data
        if not copy.Export(dst):
            raise RuntimeError("ecriture impossible : %s" % dst)

    copy_layer(source, output)
    layers, _assets, unresolved = UsdUtils.ComputeAllDependencies(output)
    for layer in layers:
        path = layer.realPath or layer.identifier
        if is_last(path):
            warnings.append("LAST encore lu par le rendu (non fige) : %s" % path)
    warnings += ["Fichier introuvable : %s" % p for p in unresolved]
    return {"source": source, "output": output, "copies": sorted(copies.values()),
            "frozen": frozen, "warnings": warnings}


def main(argv):
    if len(argv) == 5 and argv[1] == "--houdini":
        return _relaunch(argv)
    if len(argv) != 3:
        print("usage: flux_freeze_at_start.py [--houdini <HFS>] <source.usd> <output.usda>")
        return 2
    try:
        result = freeze(argv[1], argv[2])
    except Exception as exc:  # readable line in the Tractor task log
        print("GEL ECHOUE : %s: %s" % (type(exc).__name__, exc))
        return 1
    print("source :", result["source"])
    for last, target in sorted(result["frozen"].items()):
        print("fige :", last, "->", target)
    for warning in result["warnings"]:
        print("avertissement :", warning)
    print("rendu lit :", result["output"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
