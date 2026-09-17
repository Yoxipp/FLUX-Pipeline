# test_library_import.py — USD library + free path sources of the Houdini importer HDA.

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from pxr import Usd, UsdSkel
except ImportError:  # pragma: no cover
    Usd = None

from features.importer import library_import


def _lib(tmp: Path) -> dict:
    comp_dir = tmp / "assets" / "chara" / "HERO" / "usd"
    (comp_dir / "HERO_v002").mkdir(parents=True)
    (comp_dir / "HERO_v002" / "HERO.usda").write_text("#usda 1.0\n", encoding="utf-8")
    (comp_dir / "HERO_LAST.usda").write_text("#usda 1.0\n", encoding="utf-8")
    asm = tmp / "usd" / "assembly"
    asm.mkdir(parents=True)
    (asm / "TOWN.usda").write_text("#usda 1.0\n", encoding="utf-8")
    (asm / "PARK" / "PARK_v003").mkdir(parents=True)
    (asm / "PARK" / "PARK_v003" / "PARK.usda").write_text("#usda 1.0\n", encoding="utf-8")
    (asm / "PARK" / "PARK_LAST.usda").write_text("#usda 1.0\n", encoding="utf-8")
    return {
        "components": [{"name": "HERO", "dir": str(comp_dir), "last": str(comp_dir / "HERO_LAST.usda"),
                        "versions": ["v001", "v002"]}],
        "assemblies": [{"name": "TOWN", "file": str(asm / "TOWN.usda"), "instances": [], "legacy": True},
                       {"name": "PARK", "file": str(asm / "PARK" / "PARK_LAST.usda"), "instances": [],
                        "legacy": False, "versions": ["v001", "v003"]}],
    }


class LibraryImport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_libimp_"))
        self.lib = _lib(self.tmp)
        patcher = mock.patch("features.usd_assembler.library.build_library", return_value=self.lib)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_items_list_components_then_assemblies_with_versions(self):
        items = library_import.library_items(self.tmp)
        self.assertEqual([i["key"] for i in items], ["component:HERO", "assembly:TOWN", "assembly:PARK"])
        self.assertEqual(items[0]["versions"], ["LAST", "v002", "v001"])
        self.assertEqual(items[2]["versions"], ["LAST", "v003", "v001"])

    def test_resolve_last_frozen_and_assembly(self):
        last = library_import.resolve_library_item(self.tmp, "component:HERO", "LAST")
        self.assertTrue(last["ok"])
        self.assertTrue(last["path"].endswith("HERO_LAST.usda"))
        v2 = library_import.resolve_library_item(self.tmp, "component:HERO", "v002")
        self.assertTrue(v2["path"].endswith(str(Path("HERO_v002") / "HERO.usda")))
        self.assertTrue(library_import.resolve_library_item(self.tmp, "assembly:TOWN")["ok"])

    def test_resolve_frozen_assembly(self):
        r = library_import.resolve_library_item(self.tmp, "assembly:PARK", "v003")
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["path"].endswith(str(Path("PARK_v003") / "PARK.usda")))
        # A legacy flat assembly has a single file whatever the version asked.
        self.assertTrue(library_import.resolve_library_item(self.tmp, "assembly:TOWN", "v002")["ok"])

    def test_importer_source_library_entries(self):
        comp = self.tmp / "assets" / "chara" / "HERO" / "usd"
        src = library_import.importer_source_for_file
        self.assertEqual(src(self.tmp, comp / "HERO_LAST.usda"),
                         {"source_mode": "library", "lib_item": "component:HERO", "lib_version": "LAST"})
        self.assertEqual(src(self.tmp, comp / "HERO_v002" / "HERO.usda")["lib_version"], "v002")
        park = self.tmp / "usd" / "assembly" / "PARK"
        self.assertEqual(src(self.tmp, park / "PARK_v003" / "PARK.usda"),
                         {"source_mode": "library", "lib_item": "assembly:PARK", "lib_version": "v003"})
        self.assertEqual(src(self.tmp, self.tmp / "usd" / "assembly" / "TOWN.usda")["lib_item"], "assembly:TOWN")

    def test_importer_source_tokens_only_when_they_resolve_to_the_file(self):
        folder = self.tmp / "assets" / "chara" / "HERO" / "rig" / "null"
        root = folder / "CHAR_RIG_HERO_null_v004" / "CHAR_RIG_HERO_null.usd"
        skel = root.with_name("CHAR_RIG_HERO_null_skel.usd")
        tok = {"CLASS": "CHAR", "TYPE": "RIG", "NAME": "HERO", "INSTANCE": "NULL"}
        with mock.patch("features.importer.importer_resolve.path_to_tokens", return_value=tok), \
             mock.patch("features.importer.importer_resolve.resolve_import_path",
                        return_value={"ok": True, "path": str(root)}) as res:
            self.assertEqual(library_import.importer_source_for_file(self.tmp, root), {
                "source_mode": "tokens", "flux_class": "CHAR", "flux_type": "RIG", "flux_name": "HERO",
                "flux_instance": "null", "flux_iter": "v004"})
            self.assertEqual(res.call_args.args[-1], "v004")
            self.assertEqual(library_import.importer_source_for_file(self.tmp, skel),
                             {"source_mode": "file", "free_path": str(skel)})

    def test_resolve_errors(self):
        self.assertFalse(library_import.resolve_library_item(self.tmp, "component:HERO", "v009")["ok"])
        self.assertFalse(library_import.resolve_library_item(self.tmp, "component:NOPE")["ok"])
        self.assertFalse(library_import.resolve_library_item(self.tmp, "bad")["ok"])
        self.assertFalse(library_import.resolve_library_item(self.tmp, "component:HERO", "../x")["ok"])


@unittest.skipIf(Usd is None, "pxr not available")
class ProbeFile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_probefile_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flux_token_is_expanded_and_skeleton_reported(self):
        f = self.tmp / "DOSSIER_PROJETS" / "anim.usda"
        f.parent.mkdir(parents=True)
        st = Usd.Stage.CreateNew(str(f))
        UsdSkel.Skeleton.Define(st, "/A/Skeleton")
        st.GetRootLayer().Save()
        with mock.patch("core.paths.get_flux_root", return_value=self.tmp):
            r = library_import.probe_file("$FLUX/DOSSIER_PROJETS/anim.usda")
        self.assertTrue(r["ok"] and r["has_skel"])
        self.assertEqual(r["path"], "$FLUX/DOSSIER_PROJETS/anim.usda")

    def test_missing_or_empty(self):
        self.assertFalse(library_import.probe_file("")["ok"])
        self.assertFalse(library_import.probe_file(str(self.tmp / "nope.usd"))["ok"])


if __name__ == "__main__":
    unittest.main()
