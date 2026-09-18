# sequence_template.py — author a clean USD template for a sequence / shot.
#
# Creating a sequence must NOT drop an empty .usd file. It generates a small but
# real USD composition:
#
#   <SEQ>/usd/<SEQ>.usda                       ← sequence root layer (default prim /World)
#   <SEQ>/usd/lighting/<SEQ>_light.usda        ← sequence BASE light rig (weak sublayer)
#
# and, per shot:
#
#   <SEQ>/<SHOT>/usd/<SEQ>_<SHOT>_LAST.usda      ← shot stage, generated (shot_stage.py, ADR 0020)
#   <SEQ>/<SHOT>/usd/lighting/<SEQ>_<SHOT>_light.usda ← shot-specific light rig (strong)
#
# Composition (strong -> weak) for a shot root layer:
#   [ shot_light.usda ]  (strong override)
#   [ <SEQ>.usda      ]  (sequence: base light rig + shared structure, weak)
#
# So the sequence carries a base light rig every shot inherits, and each shot can
# refine or override it in its own strong light layer — the same strong->weak
# sublayer stack the USD assembler uses for departments.
#
# pxr is imported lazily inside the functions: folder creation must still succeed
# on a backend without usd-core, so callers wrap these in try/except and only log.

from __future__ import annotations

import os
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

# Sub-folder (inside a seq/shot dir) that holds the USD composition layers.
USD_SUBDIR = "usd"
LIGHTING_SUBDIR = "lighting"


# ── atomic export (local copy of the assembler's writer pattern) ────────────────

def _export_atomic(layer, dest: Path) -> Path:
    """Export *layer* to *dest* atomically (temp sibling + os.replace)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.stem}.tmp{dest.suffix}")
    try:
        if not layer.Export(str(tmp)):
            raise RuntimeError(f"USD export failed for {dest}")
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return dest


def _new_layer():
    """Return a fresh anonymous .usda Sdf.Layer."""
    from pxr import Sdf

    return Sdf.Layer.CreateAnonymous(".usda")


def _set_sublayers(layer, sublayers: list[str]) -> None:
    """Set the layer's sublayer stack (strong -> weak, first entry strongest).

    Applied AFTER prim authoring and just before export: an anonymous layer cannot
    resolve relative sublayer paths, so declaring them while a stage is open on it
    only spams harmless 'Could not load sublayer' warnings. On disk they resolve.
    """
    layer.subLayerPaths[:] = sublayers


def _author_world(stage) -> None:
    """Create the /World default prim (Xform, assembly kind) + a /World/Lighting scope."""
    from pxr import Kind, Usd, UsdGeom

    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    Usd.ModelAPI(world.GetPrim()).SetKind(Kind.Tokens.assembly)
    # Lighting scope: the anchor every light-rig layer authors into / overrides.
    UsdGeom.Scope.Define(stage, "/World/Lighting")


def _set_light_input(light_prim, name: str, type_name, value) -> None:
    """Set a UsdLux light input version-agnostically (schema helpers were renamed
    across USD releases; authoring the ``inputs:<name>`` attribute directly is stable)."""
    attr = light_prim.CreateAttribute(f"inputs:{name}", type_name)
    attr.Set(value)


# ── sequence ────────────────────────────────────────────────────────────────────

def create_sequence_usd_template(seq_path: Path, seq_label: str) -> dict:
    """Author the sequence root layer + its base light rig under *seq_path*.

    Idempotent: never overwrites layers that already exist (artist edits are kept).
    Returns {"ok": True, "created": [paths...]} or {"ok": False, "error": "..."}.
    """
    try:
        from pxr import Sdf, Usd, UsdLux
    except ImportError as exc:
        return {"ok": False, "error": f"usd-core indisponible : {exc}"}

    usd_dir = seq_path / USD_SUBDIR
    light_dir = usd_dir / LIGHTING_SUBDIR
    root_dest = usd_dir / f"{seq_label}.usda"
    light_dest = light_dir / f"{seq_label}_light.usda"
    light_rel = f"./{LIGHTING_SUBDIR}/{light_dest.name}"

    created: list[str] = []

    try:
        # 1. Sequence base light rig (weak) — a real starter rig: dome + key.
        if not light_dest.exists():
            llayer = _new_layer()
            lstage = Usd.Stage.Open(llayer)
            _author_world(lstage)
            dome = UsdLux.DomeLight.Define(lstage, "/World/Lighting/seq_dome")
            _set_light_input(dome.GetPrim(), "intensity", Sdf.ValueTypeNames.Float, 1.0)
            key = UsdLux.DistantLight.Define(lstage, "/World/Lighting/seq_key")
            _set_light_input(key.GetPrim(), "intensity", Sdf.ValueTypeNames.Float, 3.0)
            _set_light_input(key.GetPrim(), "angle", Sdf.ValueTypeNames.Float, 1.0)
            llayer.customLayerData = {"flux": {"role": "sequence_light_rig", "sequence": seq_label}}
            _export_atomic(llayer, light_dest)
            created.append(str(light_dest))

        # 2. Sequence root layer — default prim /World, sublayers the base light rig.
        if not root_dest.exists():
            rlayer = _new_layer()
            rstage = Usd.Stage.Open(rlayer)
            _author_world(rstage)
            # /World/Shots anchor: shots get added here as references/overrides.
            from pxr import UsdGeom
            UsdGeom.Scope.Define(rstage, "/World/Shots")
            rlayer.customLayerData = {"flux": {"role": "sequence_root", "sequence": seq_label}}
            del rstage  # drop the open stage before sublayers, so no recompose warning
            _set_sublayers(rlayer, [light_rel])
            _export_atomic(rlayer, root_dest)
            created.append(str(root_dest))
    except Exception as exc:  # noqa: BLE001 — never let USD failure break folder creation
        log.warning("create_sequence_usd_template failed for %s: %s", seq_label, exc)
        return {"ok": False, "error": str(exc), "created": created}

    log.info("Sequence USD template ready: %s (%d layer(s))", seq_label, len(created))
    return {"ok": True, "created": created, "root": str(root_dest)}


# ── shot ──────────────────────────────────────────────────────────────────────

def create_shot_usd_template(shot_path: Path, seq_label: str, shot_label: str) -> dict:
    """Author the shot-specific light rig under *shot_path* (the shot stage itself is
    generated by ``usd_assembler.shot_stage``, ADR 0020).

    Idempotent. Returns {"ok": True, "created": [...]} or {"ok": False, "error": ...}.
    """
    try:
        from pxr import Usd
    except ImportError as exc:
        return {"ok": False, "error": f"usd-core indisponible : {exc}"}

    usd_dir = shot_path / USD_SUBDIR
    light_dir = usd_dir / LIGHTING_SUBDIR
    entity = f"{seq_label}_{shot_label}"
    light_dest = light_dir / f"{entity}_light.usda"

    created: list[str] = []
    try:
        # 1. Shot-specific light rig (strong) — a structured override target, not empty:
        #    /World/Lighting scope ready for shot lights / overrides of the seq rig.
        if not light_dest.exists():
            llayer = _new_layer()
            lstage = Usd.Stage.Open(llayer)
            _author_world(lstage)
            llayer.customLayerData = {
                "flux": {"role": "shot_light_rig", "sequence": seq_label, "shot": shot_label}
            }
            _export_atomic(llayer, light_dest)
            created.append(str(light_dest))

        # 2. No shot root any more (ADR 0020): the shot stage is generated and versioned
        #    by features/usd_assembler/shot_stage.py (<SEQ>_<SHOT>_vNNN + LAST) from the
        #    Production casting and the published departments. Old roots stay readable.
    except Exception as exc:  # noqa: BLE001
        log.warning("create_shot_usd_template failed for %s: %s", entity, exc)
        return {"ok": False, "error": str(exc), "created": created}

    log.info("Shot USD template ready: %s (%d layer(s))", entity, len(created))
    return {"ok": True, "created": created, "light_rig": str(light_dest)}
