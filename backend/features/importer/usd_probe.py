# usd_probe.py — read-only look at a USD file to pick how a DCC should import it.
#
# Houdini "Open in" is context driven (2026-09-17): /stage gets a Reference LOP,
# a SOP network gets a KineFX character import when the asset has a skeleton (mesh +
# joints + anim), else a plain USD import. The backend has pxr, the DCC call does not
# need it: this probe runs backend-side and only reports facts.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

USD_EXTS: frozenset[str] = frozenset({".usd", ".usda", ".usdc", ".usdz"})


def probe_usd(path: str | Path) -> dict:
    """Return {"ok", "default_prim", "kind", "has_skel", "has_mesh", "has_anim"}.

    Composes the stage (payloads loaded) so a component entry that only references
    its department layers still reports the skeleton it brings. Never raises.
    """
    info = {"ok": False, "default_prim": "", "kind": "", "has_skel": False,
            "has_mesh": False, "has_anim": False}
    try:
        from pxr import Usd, UsdGeom, UsdSkel
    except ImportError:
        return info
    try:
        stage = Usd.Stage.Open(str(path))
    except Exception as exc:
        log.warning("probe_usd: cannot open %s: %s", Path(path).name, exc)
        return info
    if stage is None:
        return info

    prim = stage.GetDefaultPrim()
    if not prim:
        roots = [p for p in stage.GetPseudoRoot().GetChildren() if p.IsDefined()]
        prim = roots[0] if roots else None
    if prim:
        info["default_prim"] = prim.GetName()
        info["kind"] = Usd.ModelAPI(prim).GetKind() or ""

    for p in stage.Traverse():
        if p.IsA(UsdSkel.Skeleton):
            # KineFX character import needs the Skeleton inside a SkelRoot; a stray one
            # (skel layer alone, old hand-built component sublayering department roots)
            # would make it fail, so it imports as plain geometry instead.
            if UsdSkel.Root.Find(p):
                info["has_skel"] = True
            else:
                info["skel_outside_root"] = True
        elif p.IsA(UsdSkel.Animation):
            info["has_anim"] = True
        elif p.IsA(UsdGeom.Mesh):
            info["has_mesh"] = True
    info["ok"] = True
    return info


def reference_prim_path(info: dict) -> str:
    """Where a Reference LOP puts the asset: /assets/<X> (component or character),
    /sets/<X> (assembly), else /<X>."""
    name = info.get("default_prim") or "asset"
    kind = info.get("kind") or ""
    if kind == "assembly":
        return f"/sets/{name}"
    if kind in ("component", "subcomponent") or info.get("has_skel"):
        return f"/assets/{name}"
    return f"/{name}"
