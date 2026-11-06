# shot_render.py — the render layer of a shot stage (ADR 0060).
#
#   <SEQ>_<SHOT>_vNNN/<SEQ>_<SHOT>_render.usda
#       /Render/karma, /Render/renderman      UsdRenderSettings (camera, resolution, purposes)
#       /Render/Products/<renderer>           RenderProduct raster <SEQ>_<SHOT>.$F4.exr
#       /Render/Vars/<renderer>_<aov>         beauty only (the AOVs stay in the sequence .hip, ADR 0036)
#
# Written by FLUX, no DCC: Tractor renders the published shot with husk --settings /Render/<renderer>.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger("usd_assembler.shot_render")

RENDER_ROOT = "/Render"
CAMERAS_ROOT = "/cameras"
DEFAULT_RESOLUTION = (1920, 1080)
DEFAULT_SETTINGS = "karma"           # renderSettingsPrimPath of the entry (usdview / Solaris)
# Beauty render vars per renderer: (name, sourceName, dataType). Delegate names, see ADR 0060.
RENDERERS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "karma": (("C", "C", "color4f"),),
    "renderman": (("Ci", "Ci", "color3f"), ("a", "a", "float")),
}


def settings_path(renderer: str) -> str:
    return f"{RENDER_ROOT}/{renderer}"


def _resolution(project: Path) -> list[int]:
    from features.folder_manager.project_config import read_project_config

    res = (read_project_config(project) or {}).get("resolution")
    if isinstance(res, (list, tuple)) and len(res) == 2 and all(isinstance(v, int) and v > 0 for v in res):
        return list(res)
    return list(DEFAULT_RESOLUTION)


def layout_cameras(files: list[Path]) -> list[str]:
    """Paths of the Camera prims under /cameras in the layout layers, sorted."""
    from pxr import Usd, UsdGeom

    found: set[str] = set()
    for f in files:
        try:
            stage = Usd.Stage.Open(str(f), Usd.Stage.LoadNone)
        except Exception as exc:     # unreadable layer: the stage still gets its other layers
            log.warning("Cameras unreadable in %s: %s", f, exc)
            continue
        root = stage.GetPrimAtPath(CAMERAS_ROOT)
        if not root:
            continue
        found.update(str(p.GetPath()) for p in Usd.PrimRange(root) if p.IsA(UsdGeom.Camera))
    return sorted(found)


def pick_camera(cameras: list[str], shot: str) -> str:
    """The shot's camera: name with the shot (SHOT010 / shot010), else shotCam, else the first."""
    if not cameras:
        return ""
    key = shot.lower()
    named = [c for c in cameras if key in c.rsplit("/", 1)[-1].lower()]
    if named:
        return named[0]
    return next((c for c in cameras if c.rsplit("/", 1)[-1] == "shotCam"), cameras[0])


def plan(project: Path, seq: str, shot: str, layout_files: list[Path], warnings: list[str]) -> dict:
    """{"camera", "cameras", "resolution", "renderers"}; adds readable warnings."""
    cameras = layout_cameras(layout_files)
    camera = pick_camera(cameras, shot)
    if not camera and layout_files:         # no layout at all: shot_stage already says so
        warnings.append("render : aucune camera publiee dans le layout, rendu sans camera choisie")
    elif len(cameras) > 1:
        warnings.append(f"render : {len(cameras)} cameras dans le layout, {camera} choisie")
    return {"camera": camera, "cameras": cameras, "resolution": _resolution(project),
            "renderers": sorted(RENDERERS)}


def write_layer(path: Path, entity: str, render: dict) -> None:
    """Author the render layer (Sdf: no composition needed, the camera is a path)."""
    from pxr import Gf, Sdf, Vt

    layer = Sdf.Layer.CreateNew(str(path))
    root = Sdf.CreatePrimInLayer(layer, RENDER_ROOT)
    root.specifier = Sdf.SpecifierDef
    root.typeName = "Scope"
    for sub in ("Products", "Vars"):
        spec = Sdf.CreatePrimInLayer(layer, f"{RENDER_ROOT}/{sub}")
        spec.specifier = Sdf.SpecifierDef
        spec.typeName = "Scope"

    def attr(prim: Sdf.PrimSpec, name: str, vtype, value, uniform: bool = True) -> None:
        a = Sdf.AttributeSpec(prim, name, vtype, Sdf.VariabilityUniform if uniform else Sdf.VariabilityVarying)
        a.default = value

    width, height = render["resolution"]
    for renderer in render["renderers"]:
        var_paths = []
        for aov, source, dtype in RENDERERS[renderer]:
            var = Sdf.CreatePrimInLayer(layer, f"{RENDER_ROOT}/Vars/{renderer}_{aov}")
            var.specifier = Sdf.SpecifierDef
            var.typeName = "RenderVar"
            attr(var, "dataType", Sdf.ValueTypeNames.Token, dtype)
            attr(var, "sourceName", Sdf.ValueTypeNames.String, source)
            attr(var, "sourceType", Sdf.ValueTypeNames.Token, "raw")
            var_paths.append(var.path)

        product = Sdf.CreatePrimInLayer(layer, f"{RENDER_ROOT}/Products/{renderer}")
        product.specifier = Sdf.SpecifierDef
        product.typeName = "RenderProduct"
        attr(product, "productType", Sdf.ValueTypeNames.Token, "raster")
        attr(product, "productName", Sdf.ValueTypeNames.Token, f"{entity}.$F4.exr", uniform=False)
        rel = Sdf.RelationshipSpec(product, "orderedVars", custom=False)
        rel.targetPathList.explicitItems = var_paths

        settings = Sdf.CreatePrimInLayer(layer, settings_path(renderer))
        settings.specifier = Sdf.SpecifierDef
        settings.typeName = "RenderSettings"
        attr(settings, "resolution", Sdf.ValueTypeNames.Int2, Gf.Vec2i(width, height))
        attr(settings, "pixelAspectRatio", Sdf.ValueTypeNames.Float, 1.0)
        attr(settings, "includedPurposes", Sdf.ValueTypeNames.TokenArray, Vt.TokenArray(["default", "render"]))
        products = Sdf.RelationshipSpec(settings, "products", custom=False)
        products.targetPathList.explicitItems = [product.path]
        if render["camera"]:
            cam = Sdf.RelationshipSpec(settings, "camera", custom=False)
            cam.targetPathList.explicitItems = [Sdf.Path(render["camera"])]
    layer.Save()


def stage_settings(usd_path: Path, renderer: str) -> str:
    """``/Render/<renderer>`` when the shot stage at *usd_path* (entry or LAST) has the render layer, else ""."""
    from pxr import Sdf

    from .shot_stage import _frozen

    entry = _frozen(Path(usd_path))
    layer = Sdf.Layer.FindOrOpen(str(entry))
    if layer is None:
        return ""
    if Path(entry).name.endswith("_LAST.usda"):       # pointer without readable target
        return ""
    render = Path(entry).with_name(f"{Path(entry).stem}_render.usda")
    if not render.is_file() or not any(Path(p).name == render.name for p in layer.subLayerPaths):
        return ""
    return settings_path(renderer) if renderer in RENDERERS else ""
