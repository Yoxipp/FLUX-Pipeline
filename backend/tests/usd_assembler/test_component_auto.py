# ADR 0023 (+ 0018 location, 0019 department layers): a component is created by hand from
# the project's departments; files (any number per department, any format) are toggled by
# one variantSet each; targets drive shaders / animations; a publish only updates a
# component that exists.

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdSkel

from features.folder_manager import tokens as tok
from features.usd_assembler import component_auto as ca
from features.usd_export import AnimData, LightAsset, MeshData, SkeletonData, publish_light_asset

_ID = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_NAME = "UTAH"
_NAME_REL = "assets/chara/UTAH"


def _asset(joints: list[str], mesh: str = "body", anim: AnimData | None = None) -> LightAsset:
    n = len(joints)
    return LightAsset(
        asset="tmp",
        skeleton=SkeletonData(joints=joints, bind_transforms=[_ID] * n, rest_transforms=[_ID] * n),
        meshes=[MeshData(name=mesh, points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                         face_vertex_counts=[3], face_vertex_indices=[0, 1, 2])],
        anim=anim,
    )


def _anim(joint: str = "Root/Hip") -> AnimData:
    # A clip is motion only (2026-09-18): the joint has to move.
    return AnimData(joints=[joint], times=[1.0, 2.0], translations=[[(0, 0, 0)], [(1, 0, 0)]],
                    rotations=[[(0, 0, 0, 1)]] * 2, scales=[[(1, 1, 1)]] * 2, fps=24.0)


class ManualComponent(unittest.TestCase):
    def setUp(self) -> None:
        # deterministic: the proxy hook is an opt-in of the project, not of these tests
        env = mock.patch.dict(os.environ, {"FLUX_PROXY_USD": "0"})
        env.start()
        self.addCleanup(env.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "PROJ"
        self.project.mkdir()
        tokens = tok.build_default_tokens()
        tokens["NAME"][_NAME] = _NAME_REL
        tok.save_tokens(self.project, tokens)
        self.usd_dir = self.project / _NAME_REL / "usd"

    # ── helpers ────────────────────────────────────────────────────────────
    def _publish(self, task: str, sub: str, joints: list[str], instance: str = "null",
                 mesh: str = "body", anim: AnimData | None = None, fmt: str = "usd") -> dict:
        dest = self.project / _NAME_REL / sub / instance
        return publish_light_asset(_asset(joints, mesh, anim), self.project, fmt=fmt, dest_dir=dest,
                                   base_name=f"CHAR_{task}_{_NAME}_{instance}", user="adam")

    def _add_publishes(self, recipe: dict, **overrides) -> dict:
        for p in ca.proposed_files(self.project, _NAME, recipe, ca.available_departments(self.project)):
            fid = f"{p['department'].lower()}_{p['instance']}"
            recipe["files"].append({"id": fid, "department": p["department"], "source": "publish",
                                    "base": p["base"], "instance": p["instance"],
                                    "format": p["format"], **overrides.get(fid, {})})
        return recipe

    def _stage(self) -> Usd.Stage:
        return Usd.Stage.Open(str(self.usd_dir / f"{_NAME}_LAST.usda"))

    def _manual(self, rel: str, prim: str = "/X") -> str:
        path = self.project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.Mesh.Define(stage, prim)
        stage.SetDefaultPrim(stage.GetPrimAtPath(prim.split("/")[1] and "/" + prim.split("/")[1]))
        stage.GetRootLayer().Save()
        return rel

    # ── creation ───────────────────────────────────────────────────────────
    def test_publish_never_creates_a_component(self) -> None:
        res = self._publish("GEO", "model", ["Root"])
        self.assertIsNone(res["component"])
        self.assertFalse(self.usd_dir.exists() and any(self.usd_dir.iterdir()))

    def test_manual_creation_with_existing_departments_only(self) -> None:
        res = ca.create_component(self.project, _NAME, ["GEO", "SHADING"])
        self.assertEqual(res["version"], "v001")
        recipe = ca.current_recipe(self.project, _NAME)
        self.assertEqual((recipe["departments"], recipe["files"]), (["GEO", "SHADING"], []))
        self.assertEqual([b["name"] for b in recipe["blocks"]], ["model", "look", "rig"])     # ADR 0024
        with self.assertRaisesRegex(ValueError, "existe deja"):
            ca.create_component(self.project, _NAME, ["GEO"])

    def test_unknown_or_duplicate_department_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "inexistant"):
            ca.create_component(self.project, _NAME, ["GEO", "NOPE"])
        with self.assertRaisesRegex(ValueError, "double"):
            ca.create_component(self.project, _NAME, ["GEO", "GEO"])
        with self.assertRaisesRegex(ValueError, "inexistant"):
            ca.create_component(self.project, _NAME, ["MULT"])
        self.assertFalse(ca.exists(self.project, _NAME))

    def test_publish_updates_a_created_component(self) -> None:
        self._publish("GEO", "model", ["Root"])
        ca.create_component(self.project, _NAME, ["GEO"])
        recipe = self._add_publishes(ca.current_recipe(self.project, _NAME))
        self.assertEqual(ca.save_component(self.project, _NAME, recipe)["version"], "v002")
        res = self._publish("GEO", "model", ["Root"])          # new GEO version
        self.assertEqual(res["component"], "v003")
        files = ca.entry_signature(self.usd_dir / "UTAH_v003" / "UTAH.usda")
        self.assertEqual(files["geo_null"]["version"], "v002")
        # A publish of a department the component does not use changes nothing.
        self.assertIsNone(self._publish("RIG", "rig", ["Root"])["component"])

    def test_unreadable_latest_version_is_skipped(self) -> None:
        """2026-09-26: UTAH_v017/UTAH.usda unreadable (OneDrive), LAST on v016:
        the component page showed the pxr error and no link at all."""
        from features.usd_assembler.library import list_components

        self._publish("GEO", "model", ["Root"])
        ca.create_component(self.project, _NAME, ["GEO"])
        recipe = self._add_publishes(ca.current_recipe(self.project, _NAME))
        ca.save_component(self.project, _NAME, recipe)                    # v002, LAST
        broken = self.usd_dir / "UTAH_v003"
        broken.mkdir()
        (broken / "UTAH.usda").write_text("#usda 1.0\n(\n  customLayerData = {")
        self.assertEqual(ca.unreadable_versions(self.usd_dir, _NAME), ["v003"])
        got = ca.current_recipe(self.project, _NAME)
        self.assertEqual([f["id"] for f in got["files"]], ["geo_null"])
        info = next(c for c in list_components(self.project) if c["name"] == _NAME)
        self.assertEqual((info["version"], [f["id"] for f in info["files"]]), ("v002", ["geo_null"]))
        self.assertTrue(any("v003" in w and "illisible" in w for w in info["warnings"]))
        # Next write goes past the broken folder, never over it.
        self.assertEqual(self._publish("GEO", "model", ["Root"])["component"], "v004")

    def test_non_usd_publishes_are_proposed_as_files(self) -> None:
        """2026-09-26: GEO published in .abc only, the model block offered nothing."""
        import json
        folder = self.project / _NAME_REL / "model" / "null"
        folder.mkdir(parents=True)
        (folder / "CHAR_GEO_UTAH_null_v003.abc").write_bytes(b"abc")
        (folder / "CHAR_GEO_UTAH_null_LAST.abc").write_bytes(b"abc")
        (folder / "CHAR_GEO_UTAH_null_LAST.abc.flux.json").write_text(json.dumps({"version": "v003"}))
        ca.create_component(self.project, _NAME, ["GEO"])
        recipe = ca.current_recipe(self.project, _NAME)
        got = ca.proposed_files(self.project, _NAME, recipe, ["GEO"])
        self.assertEqual([(p["base"], p["format"], p["version"], p["path"]) for p in got],
                         [("CHAR_GEO_UTAH_null", "abc", "v003", f"{_NAME_REL}/model/null/CHAR_GEO_UTAH_null_LAST.abc")])
        # Linked as a file, it is not offered again; "Tout ajouter" leaves it to the artist.
        recipe["files"].append({"id": "geo_null_abc", "department": "GEO", "source": "manual",
                                "path": got[0]["path"], "format": "abc"})
        self.assertEqual(ca.proposed_files(self.project, _NAME, recipe, ["GEO"]), [])
        self.assertIsNone(ca.add_proposed(self.project, _NAME))

    def test_new_publish_is_proposed_not_added(self) -> None:
        self._publish("GEO", "model", ["Root"])
        ca.create_component(self.project, _NAME, ["GEO"])
        ca.save_component(self.project, _NAME, self._add_publishes(ca.current_recipe(self.project, _NAME)))
        self._publish("GEO", "model", ["Root"], instance="B", mesh="hat")
        recipe = ca.current_recipe(self.project, _NAME)
        self.assertEqual([f["id"] for f in recipe["files"]], ["geo_null"])
        self.assertEqual([p["base"] for p in ca.proposed_files(self.project, _NAME, recipe)], ["CHAR_GEO_UTAH_B"])

    # ── files ──────────────────────────────────────────────────────────────
    def test_several_geometries_active_at_once_and_toggled_alone(self) -> None:
        self._publish("GEO", "model", ["Root"])
        self._publish("GEO", "model", ["Root"], instance="B", mesh="hat")
        ca.create_component(self.project, _NAME, ["GEO"])
        ca.save_component(self.project, _NAME, self._add_publishes(ca.current_recipe(self.project, _NAME)))
        stage = self._stage()
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/render/body").IsValid())
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/render/hat").IsValid())
        stage.GetPrimAtPath("/UTAH").GetVariantSet("geo_B").SetVariantSelection("off")
        self.assertFalse(stage.GetPrimAtPath("/UTAH/geo/render/hat").IsValid())
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/render/body").IsValid())

    def test_groom_without_default_prim_is_referenced_at_its_root(self) -> None:
        """2026-09-26: a Houdini groom file has no defaultPrim; the component
        referenced a prim named after the file (unresolved, empty groom)."""
        rel = f"{_NAME_REL}/groom/procedural/CHAR_GROOM_UTAH_PROCEDURAL_WINGS_v001.usda"
        path = self.project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.Xform.Define(stage, "/groom_procedural_WINGS")
        UsdGeom.BasisCurves.Define(stage, "/groom_procedural_WINGS/guides")
        stage.GetRootLayer().Save()
        ca.create_component(self.project, _NAME, ["GROOM"])
        recipe = ca.current_recipe(self.project, _NAME)
        recipe["files"].append({"id": "wings", "department": "GROOM", "source": "manual", "path": rel})
        ca.save_component(self.project, _NAME, recipe)
        self.assertEqual(ca.current_recipe(self.project, _NAME)["files"][0].get("kind"), "groom")
        comp = self._stage()
        guides = [p for p in comp.Traverse() if p.IsA(UsdGeom.BasisCurves)]
        self.assertEqual([str(p.GetPath()) for p in guides], ["/UTAH/groom/wings/guides"])

    def test_a_default_prim_that_does_not_exist_is_not_referenced(self) -> None:
        """A groom whose defaultPrim names a prim the file does not hold."""
        rel = f"{_NAME_REL}/groom/procedural/CHAR_GROOM_UTAH_PROCEDURAL_TAIL_v001.usda"
        path = self.project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        layer = Sdf.Layer.CreateNew(str(path))
        stage = Usd.Stage.Open(layer)
        UsdGeom.BasisCurves.Define(stage, "/groom_procedural_TAIL/guides")
        layer.defaultPrim = "CHAR_GROOM_UTAH_PROCEDURAL_TAIL"
        layer.Save()
        from features.usd_assembler.resolve.flux_resolver import _default_prim
        self.assertEqual(_default_prim(path), "groom_procedural_TAIL")

    def test_texture_in_look_becomes_a_material_bound_on_its_targets(self) -> None:
        """2026-09-26: a .tx linked in the look block with the grooms as targets."""
        groom_rel = f"{_NAME_REL}/groom/procedural/WINGS_v001.usda"
        gp = self.project / groom_rel
        gp.parent.mkdir(parents=True, exist_ok=True)
        st = Usd.Stage.CreateNew(str(gp))
        UsdGeom.BasisCurves.Define(st, "/Utah/groom/wings")
        st.GetRootLayer().Save()
        tex_rel = f"{_NAME_REL}/shading/tex/CHAR_SHADING_UTAH_TEX_FEATHERS_LAST.tx"
        tp = self.project / tex_rel
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_bytes(b"tx")
        ca.create_component(self.project, _NAME, ["GROOM", "SHADING"])
        recipe = ca.current_recipe(self.project, _NAME)
        recipe["files"] += [
            {"id": "wings", "department": "GROOM", "source": "manual", "path": groom_rel},
            {"id": "feathers", "department": "SHADING", "source": "manual", "path": tex_rel,
             "kind": "shader", "targets": ["wings"]},
        ]
        ca.save_component(self.project, _NAME, recipe)
        stage = self._stage()
        from pxr import UsdShade
        mat = UsdShade.Material(stage.GetPrimAtPath("/UTAH/mtl/feathers"))
        self.assertTrue(mat)
        tex = UsdShade.Shader(stage.GetPrimAtPath("/UTAH/mtl/feathers/tex"))
        self.assertTrue(tex.GetInput("file").Get().path.endswith("CHAR_SHADING_UTAH_TEX_FEATHERS_LAST.tx"))
        self.assertTrue(tex.GetInput("file").Get().resolvedPath)
        surf = mat.ComputeSurfaceSource()[0]
        self.assertEqual(surf.GetIdAttr().Get(), "UsdPreviewSurface")
        bound = UsdShade.MaterialBindingAPI(stage.GetPrimAtPath("/UTAH/groom/wings/groom/wings")).ComputeBoundMaterial()[0]
        self.assertEqual(str(bound.GetPath()), "/UTAH/mtl/feathers")

    def test_manual_files_of_any_format(self) -> None:
        ca.create_component(self.project, _NAME, ["GEO"])
        recipe = ca.current_recipe(self.project, _NAME)
        for i, ext in enumerate(("usd", "usda", "usdc")):
            rel = self._manual(f"{_NAME_REL}/model/extra/part{i}.{ext}", f"/P{i}")
            recipe["files"].append({"id": f"m_{ext}", "department": "GEO", "source": "manual", "path": rel})
        for ext in ("abc", "fbx"):
            path = self.project / _NAME_REL / "model" / "extra" / f"part.{ext}"
            path.write_bytes(b"")
            recipe["files"].append({"id": f"m_{ext}", "department": "GEO", "source": "manual",
                                    "path": f"{_NAME_REL}/model/extra/part.{ext}", "prim": "/part"})
        res = ca.save_component(self.project, _NAME, recipe)
        saved = ca.current_recipe(self.project, _NAME)
        self.assertEqual([f["format"] for f in saved["files"]], ["usd", "usda", "usdc", "abc", "fbx"])
        self.assertTrue(any(".fbx : lu par Houdini seulement" in w for w in res["warnings"]), res["warnings"])
        self.assertTrue(any(".abc : lu par Houdini" in w for w in res["warnings"]), res["warnings"])
        self.assertFalse(any(".usd" in w for w in res["warnings"]), res["warnings"])
        stage = self._stage()
        self.assertEqual(stage.GetPrimAtPath("/UTAH").GetTypeName(), "")    # never retyped
        for ext in ("usd", "usda", "usdc"):
            self.assertTrue(stage.GetPrimAtPath(f"/UTAH/geo/render/m_{ext}").IsA(UsdGeom.Mesh), ext)

    def test_file_without_extension_is_refused(self) -> None:
        ca.create_component(self.project, _NAME, ["GEO"])
        recipe = ca.current_recipe(self.project, _NAME)
        recipe["files"].append({"id": "noext", "department": "GEO", "source": "manual", "path": "a/b/file"})
        with self.assertRaisesRegex(ValueError, "format non identifiable"):
            ca.save_component(self.project, _NAME, recipe)

    # ── targets ────────────────────────────────────────────────────────────
    def test_incompatible_target_is_refused(self) -> None:
        self._publish("GEO", "model", ["Root"])
        self._publish("RIG", "rig", ["Root", "Root/Hip"])
        ca.create_component(self.project, _NAME, ["GEO", "RIG", "ANIM"])
        recipe = self._add_publishes(ca.current_recipe(self.project, _NAME))
        clip = self._manual(f"{_NAME_REL}/anim/walk.usda", "/C")
        recipe["files"].append({"id": "walk", "department": "ANIM", "source": "manual", "path": clip,
                                "targets": ["geo_null"]})
        with self.assertRaisesRegex(ValueError, "cible incompatible"):
            ca.save_component(self.project, _NAME, recipe)

    def test_animation_binds_its_target_rig_only_and_is_off_by_default(self) -> None:
        self._publish("GEO", "model", ["Root", "Root/Hip"])
        self._publish("RIG", "rig", ["Root", "Root/Hip"])
        self._publish("ANIM", "anim", ["Root", "Root/Hip"], instance="walk", anim=_anim(), fmt="usda")
        ca.create_component(self.project, _NAME, ["GEO", "RIG", "ANIM"])
        recipe = self._add_publishes(ca.current_recipe(self.project, _NAME),
                                     anim_walk={"targets": ["rig_null"], "active": True})
        res = ca.save_component(self.project, _NAME, recipe)
        anim = next(f for f in ca.current_recipe(self.project, _NAME)["files"] if f["id"] == "anim_walk")
        self.assertFalse(anim["active"])                        # preview only: never on by default
        stage = self._stage()
        root = stage.GetPrimAtPath("/UTAH")
        self.assertEqual(root.GetVariantSet("anim_walk").GetVariantSelection(), "off")
        skel = UsdSkel.BindingAPI(stage.GetPrimAtPath("/UTAH/skel/Skeleton"))
        self.assertFalse(skel.GetAnimationSourceRel().GetTargets())
        root.GetVariantSet("anim_walk").SetVariantSelection("on")
        self.assertEqual(skel.GetAnimationSourceRel().GetTargets(), [Sdf.Path("/UTAH/anims/anim_walk")])
        self.assertTrue(stage.GetPrimAtPath("/UTAH/anims/anim_walk").IsA(UsdSkel.Animation))
        self.assertEqual(res["warnings"], [])

    def test_two_animations_on_one_rig_warn_and_keep_both(self) -> None:
        from features.usd_assembler import component_recipe as cr

        recipe = cr.normalize({"departments": ["RIG", "ANIM"], "files": [
            {"id": "rig", "department": "RIG", "source": "manual", "path": "r.usd"},
            {"id": "walk", "department": "ANIM", "source": "manual", "path": "w.usd", "targets": ["rig"]},
            {"id": "run", "department": "ANIM", "source": "manual", "path": "u.usd", "targets": ["rig"]},
        ]}, ["RIG", "ANIM"])
        active = {"walk": True, "run": True}
        warns = cr.warnings(recipe, active)
        self.assertTrue(any("plusieurs animations ciblent le meme rig" in w for w in warns), warns)
        self.assertEqual(cr.effective(recipe, active), {"rig": True, "walk": True, "run": True})

    def test_shader_greyed_without_active_target_keeps_its_state(self) -> None:
        from features.usd_assembler import component_recipe as cr

        recipe = cr.normalize({"departments": ["GEO", "SHADING"], "files": [
            {"id": "body", "department": "GEO", "source": "manual", "path": "b.usd"},
            {"id": "hat", "department": "GEO", "source": "manual", "path": "h.usd"},
            {"id": "skin", "department": "SHADING", "source": "manual", "path": "s.usd",
             "targets": ["body", "hat"]},
        ]}, ["GEO", "SHADING"])
        self.assertEqual(cr.greyed(recipe, {"body": False}), set())
        self.assertEqual(cr.greyed(recipe, {"body": False, "hat": False}), {"skin"})
        self.assertFalse(cr.effective(recipe, {"body": False, "hat": False})["skin"])
        self.assertTrue(cr.active_map(recipe, {"body": False, "hat": False})["skin"])   # memorized
        self.assertTrue(cr.effective(recipe, {"body": True, "hat": False})["skin"])     # restored

    def test_linked_proxy_replaces_generated_one(self) -> None:
        self._publish("GEO", "model", ["Root"])
        self._publish("GEO", "model", ["Root"], instance="low", mesh="low")
        ca.create_component(self.project, _NAME, ["GEO"])
        recipe = self._add_publishes(ca.current_recipe(self.project, _NAME),
                                     geo_low={"proxy_of": ["geo_null"]})
        ca.save_component(self.project, _NAME, recipe)
        stage = self._stage()
        proxy = stage.GetPrimAtPath("/UTAH/geo/proxy/geo_low")
        self.assertTrue(proxy.IsValid())
        self.assertEqual(UsdGeom.Imageable(proxy).ComputePurpose(), "proxy")
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/proxy/geo_low/low").IsValid())
        self.assertNotEqual(UsdGeom.Imageable(stage.GetPrimAtPath("/UTAH/geo/render/body")).ComputePurpose(),
                            "proxy")

    # ── blocks and links (ADR 0024) ────────────────────────────────────────
    def test_link_arcs_reference_payload_sublayer(self) -> None:
        ca.create_component(self.project, _NAME)
        recipe = ca.current_recipe(self.project, _NAME)
        for fid, arc in (("ref", "reference"), ("pay", "payload"), ("sub", "sublayer")):
            # a sublayer contributes under the asset root only: its file is authored there
            prim = f"/{_NAME}/SUB" if arc == "sublayer" else f"/{fid.upper()}"
            rel = self._manual(f"{_NAME_REL}/model/extra/{fid}.usda", prim)
            recipe["files"].append({"id": fid, "block": "model", "department": "GEO", "source": "manual",
                                    "path": rel, "arc": arc})
        ca.save_component(self.project, _NAME, recipe)
        stage = self._stage()
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/render/ref/REF").IsValid() or
                        stage.GetPrimAtPath("/UTAH/geo/render/ref").IsA(UsdGeom.Mesh))
        pay = stage.GetPrimAtPath("/UTAH/geo/render/pay")
        self.assertTrue(pay.HasAuthoredPayloads())
        self.assertTrue(pay.IsA(UsdGeom.Mesh))
        self.assertTrue(stage.GetPrimAtPath("/UTAH/SUB").IsA(UsdGeom.Mesh))
        payload = Sdf.Layer.FindOrOpen(str(self.usd_dir / "UTAH_v002" / "UTAH_payload.usda"))
        self.assertEqual([p.rsplit("/", 1)[-1] for p in payload.subLayerPaths], ["UTAH_model.usda", "sub.usda"])
        view = ca.component_files(self.project, _NAME)
        self.assertEqual({f["id"]: f["variant_set"] for f in view["files"]}, {"ref": "ref", "pay": "pay", "sub": ""})

    def test_importer_gets_the_department_layers_to_compose_itself(self) -> None:
        # ADR 0032: FLUX Import may compose each department layer with its own arc.
        self._publish("GEO", "model", ["Root"])
        ca.create_component(self.project, _NAME, ["GEO"])
        recipe = self._add_publishes(ca.current_recipe(self.project, _NAME))
        rel = self._manual(f"{_NAME_REL}/model/extra/sub.usda", f"/{_NAME}/SUB")
        recipe["files"].append({"id": "sub", "block": "model", "department": "GEO", "source": "manual",
                                "path": rel, "arc": "sublayer"})
        ca.save_component(self.project, _NAME, recipe)
        layers = ca.component_files(self.project, _NAME)["layers"]
        self.assertEqual([(l["id"], l["link"]) for l in layers], [("model", False), ("sub", True)])
        self.assertTrue(all(Path(l["path"]).is_file() for l in layers))
        # Referenced alone under the importer's prim, the department brings its geometry.
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/assets/UTAH")
        prim.GetReferences().AddReference(layers[0]["path"])
        prim.GetVariantSets().GetVariantSet("geo_null").SetVariantSelection("on")
        meshes = [p for p in Usd.PrimRange(prim) if p.IsA(UsdGeom.Mesh)]
        self.assertTrue(meshes)

    def test_variants_are_exclusive_in_their_block(self) -> None:
        ca.create_component(self.project, _NAME)
        recipe = ca.current_recipe(self.project, _NAME)
        for fid, variant in (("red", "red"), ("blue", "blue")):
            rel = self._manual(f"{_NAME_REL}/model/extra/{fid}.usda", f"/{fid.upper()}")
            recipe["files"].append({"id": fid, "block": "look", "department": "GEO", "source": "manual",
                                    "path": rel, "variant": variant})
        recipe["blocks"] = [dict(b, variant="blue") if b["name"] == "look" else b for b in recipe["blocks"]]
        ca.save_component(self.project, _NAME, recipe)
        saved = ca.current_recipe(self.project, _NAME)
        self.assertEqual({f["id"]: f["active"] for f in saved["files"]}, {"red": False, "blue": True})
        stage = self._stage()
        vset = stage.GetPrimAtPath("/UTAH").GetVariantSet("look")
        self.assertEqual(sorted(vset.GetVariantNames()), ["blue", "red"])
        self.assertEqual(vset.GetVariantSelection(), "blue")
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/render/blue").IsValid())
        self.assertFalse(stage.GetPrimAtPath("/UTAH/geo/render/red").IsValid())
        vset.SetVariantSelection("red")
        self.assertTrue(stage.GetPrimAtPath("/UTAH/geo/render/red").IsValid())
        self.assertFalse(stage.GetPrimAtPath("/UTAH/geo/render/blue").IsValid())
        view = ca.component_files(self.project, _NAME)
        self.assertEqual({(f["id"], f["variant_set"], f["variant"]) for f in view["files"]},
                         {("red", "look", "red"), ("blue", "look", "blue")})

    def test_proxy_checkbox_stands_in_for_its_block(self) -> None:
        self._publish("GEO", "model", ["Root"])
        self._publish("GEO", "model", ["Root"], instance="low", mesh="low")
        ca.create_component(self.project, _NAME)
        recipe = self._add_publishes(ca.current_recipe(self.project, _NAME),
                                     geo_low={"block": "model", "proxy": True},
                                     geo_null={"block": "model"})
        ca.save_component(self.project, _NAME, recipe)
        low = next(f for f in ca.current_recipe(self.project, _NAME)["files"] if f["id"] == "geo_low")
        self.assertEqual(low["proxy_of"], ["geo_null"])
        stage = self._stage()
        proxy = stage.GetPrimAtPath("/UTAH/geo/proxy/geo_low")
        self.assertEqual(UsdGeom.Imageable(proxy).ComputePurpose(), "proxy")

    def test_proxy_menu_names_the_file_it_stands_in_for(self) -> None:
        # 2026-09-26: the menu beside "Proxy" picks one file of the component, any
        # block (a groom's proxy geometry sits in model, the groom in hair).
        from features.usd_assembler import component_recipe as cr

        link = {"source": "manual", "path": "a/x.usda"}
        r = cr.normalize({"blocks": [{"name": "model"}, {"name": "hair"}], "files": [
            dict(link, id="body", block="model", department="GEO"),
            dict(link, id="fur_low", block="model", department="GEO", proxy=True, proxy_of=["fur"]),
            dict(link, id="fur", block="hair", department="GROOM"),
            dict(link, id="body_low", block="model", department="GEO", proxy=True),
        ]}, ["GEO", "GROOM"])
        by_id = {f["id"]: f for f in r["files"]}
        self.assertEqual(by_id["fur_low"]["proxy_of"], ["fur"])
        self.assertEqual(by_id["body_low"]["proxy_of"], ["body"])      # no pick: its block

    def test_block_and_link_rules(self) -> None:
        from features.usd_assembler import component_recipe as cr

        def norm(blocks, files):
            return cr.normalize({"blocks": blocks, "files": files}, ["GEO", "SHADING", "RIG"])

        link = {"id": "a", "department": "GEO", "source": "manual", "path": "a.usd"}
        self.assertEqual(norm(["model"], [dict(link, block="model")])["departments"], ["GEO"])
        with self.assertRaisesRegex(ValueError, "block en double"):
            norm(["model", "Model"], [])
        with self.assertRaisesRegex(ValueError, "nom de block invalide"):
            norm(["my block"], [])
        with self.assertRaisesRegex(ValueError, "absent du component"):
            norm(["model"], [dict(link, block="look")])
        with self.assertRaisesRegex(ValueError, "ni proxy ni variante"):
            norm(["model"], [dict(link, block="model", arc="sublayer", variant="v1")])
        with self.assertRaisesRegex(ValueError, "arc inconnu"):
            norm(["model"], [dict(link, block="model", arc="inherit")])
        with self.assertRaisesRegex(ValueError, "proxy doit etre"):
            norm(["look"], [dict(link, block="look", department="SHADING", proxy=True)])
        # A block without blocks key (recipe before ADR 0024): one per task, named after it.
        old = cr.normalize({"departments": ["GEO", "SHADING"], "files": [link]}, ["GEO", "SHADING"])
        self.assertEqual(([b["name"] for b in old["blocks"]], old["files"][0]["block"]),
                         (["model", "look"], "model"))

    # ── compatibility ──────────────────────────────────────────────────────
    def test_component_before_adr_0023_is_read_as_a_recipe(self) -> None:
        self._publish("GEO", "model", ["Root"])
        self._publish("GEO", "model", ["Root"], instance="B", mesh="hat")
        folder = self.usd_dir / "UTAH_v001"
        folder.mkdir(parents=True)
        layer = Sdf.Layer.CreateNew(str(folder / "UTAH.usda"))
        Sdf.PrimSpec(layer, _NAME, Sdf.SpecifierDef)
        layer.customLayerData = {"flux": {"component": _NAME, "version": "v001", "slots": {
            "model": {"task": "GEO", "default": "null", "version": "v001", "variants": {
                "null": {"instance": "null", "variante": "", "path": "x", "prim": _NAME, "version": "v001"},
                "B": {"instance": "B", "variante": "", "path": "y", "prim": _NAME, "version": "v001"}}}}}}
        layer.Save()
        recipe = ca.current_recipe(self.project, _NAME)
        self.assertEqual(recipe["departments"], ["GEO"])
        self.assertEqual({f["id"]: f["active"] for f in recipe["files"]}, {"GEO_B": False, "GEO_null": True})
        res = self._publish("GEO", "model", ["Root"])           # migrated on the next update
        self.assertEqual(res["component"], "v002")
        self.assertTrue(ca._entry_flux(self.usd_dir / "UTAH_v002" / "UTAH.usda").get("recipe"))

    def test_importer_view_never_saves_its_choices(self) -> None:
        self._publish("GEO", "model", ["Root"])
        ca.create_component(self.project, _NAME, ["GEO"])
        ca.save_component(self.project, _NAME, self._add_publishes(ca.current_recipe(self.project, _NAME)))
        view = ca.component_files(self.project, _NAME, "LAST", {"geo_null": False})
        self.assertEqual([(f["id"], f["variant_set"]) for f in view["files"]], [("geo_null", "geo_null")])
        self.assertTrue(ca.current_recipe(self.project, _NAME)["files"][0]["active"])
        self.assertFalse((self.usd_dir / "UTAH_v003").exists())

    def test_regeneration_is_logged_like_a_publish(self) -> None:
        import json

        self._publish("GEO", "model", ["Root"])
        ca.create_component(self.project, _NAME, ["GEO"], user="adam")
        entries = json.loads((self.usd_dir / "modif_logs.json").read_text(encoding="utf-8"))
        self.assertEqual((entries[-1]["name"], entries[-1]["version"], entries[-1]["user"]),
                         (_NAME, "v001", "adam"))
        self.assertIn("component cree", entries[-1]["modification"])


if __name__ == "__main__":
    unittest.main()
