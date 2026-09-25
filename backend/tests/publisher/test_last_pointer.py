# test_last_pointer.py - ADR 0017: immutable vNNN, LAST as USD layer / copy / .link,
# legacy LAST compat, .bgeo.sc, project storage settings, locked LAST.

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.folder_manager.naming_validator import get_base_name, parse_filename, strip_version
from features.importer import importer_resolve as ir
from features.publisher import last_pointer as lp
from features.publisher.publish_layout import (
    archive_flat_last, find_last_file, highest_flat_version, last_version_label,
    next_publish_version, publish_into_layout,
)
from features.publisher.version_resolver import get_last_file

_BASE = "CHAR_MODEL_HERO_null"

_USDA = """#usda 1.0
(
    defaultPrim = "hero"
    metersPerUnit = 0.01
    upAxis = "Z"
    startTimeCode = 1001
    endTimeCode = 1100
)

def Xform "hero"
{
}
"""


def _src(dir_: Path, name: str, text: str = "x") -> Path:
    p = dir_ / name
    p.write_text(text)
    return p


class Classification(unittest.TestCase):
    def test_default_rules(self):
        self.assertEqual(lp.classify(".usd", 10), lp.MODE_LAYER)
        self.assertEqual(lp.classify(".usdc", 10), lp.MODE_LAYER)
        self.assertEqual(lp.classify(".usdz", 10), lp.MODE_COPY)
        self.assertEqual(lp.classify(".abc", 10), lp.MODE_COPY)
        self.assertEqual(lp.classify(".bgeo.sc", 10), lp.MODE_COPY)
        self.assertEqual(lp.classify(".vdb", 10), lp.MODE_LINK)
        self.assertEqual(lp.classify(".exr", 10, is_sequence=True), lp.MODE_LINK)

    def test_size_rule_wins_over_type_except_usd(self):
        big = 3 * 1024 ** 3
        self.assertEqual(lp.classify(".abc", big), lp.MODE_LINK)
        self.assertEqual(lp.classify(".usd", big), lp.MODE_LAYER)
        settings = {"last_mode": {".abc": "copy"}, "last_link_threshold_gb": 5}
        self.assertEqual(lp.classify(".abc", big, settings=settings), lp.MODE_COPY)

    def test_project_override(self):
        settings = {"last_mode": {".abc": "link", ".fbx": "layer"}, "last_link_threshold_gb": 2}
        self.assertEqual(lp.classify(".abc", 10, settings=settings), lp.MODE_LINK)
        # layer is meaningless outside USD: ignored
        self.assertEqual(lp.classify(".fbx", 10, settings=settings), lp.MODE_COPY)

    def test_storage_settings_from_project_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "project.json").write_text(json.dumps({"storage": {
                "last_mode": {"abc": "link", ".obj": "bogus"},
                "last_link_threshold_gb": 0.5,
            }}))
            dest = proj / "assets" / "hero" / "model"
            dest.mkdir(parents=True)
            s = lp.load_storage_settings(dest)
            self.assertEqual(s["last_mode"], {".abc": "link"})
            self.assertEqual(s["last_link_threshold_gb"], 0.5)
            _, ver = publish_into_layout(_src(proj, "a.abc"), dest, _BASE)
            self.assertTrue((dest / f"{_BASE}_LAST.abc.link").is_file())
            self.assertFalse((dest / f"{_BASE}_LAST.abc").exists())
            self.assertEqual(ver, 1)

    def test_storage_settings_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = lp.load_storage_settings(Path(tmp))
            self.assertEqual(s, {"last_mode": {}, "last_link_threshold_gb": 2.0})


class Names(unittest.TestCase):
    def test_parse_published_name(self):
        self.assertEqual(lp.parse_published_name("A_LAST.bgeo.sc"), ("A_LAST", ".bgeo.sc", "data"))
        self.assertEqual(lp.parse_published_name("A_LAST.abc.flux.json"), ("A_LAST", ".abc", "meta"))
        self.assertEqual(lp.parse_published_name("A_LAST.abc.link"), ("A_LAST", ".abc", "link"))
        self.assertEqual(lp.parse_published_name("A_v002.usd"), ("A_v002", ".usd", "data"))

    def test_bgeo_sc_naming(self):
        self.assertEqual(get_base_name(f"{_BASE}_LAST.bgeo.sc"), _BASE)
        self.assertEqual(get_base_name(f"{_BASE}_v003.bgeo.sc"), _BASE)
        self.assertEqual(strip_version(f"{_BASE}_v003.bgeo.sc"), f"{_BASE}.bgeo.sc")
        parsed = parse_filename(f"{_BASE}_LAST.bgeo.sc")
        self.assertEqual((parsed["INSTANCE"], parsed["ITER"], parsed["extension"]),
                         ("null", "LAST", "bgeo.sc"))


class LayerLast(unittest.TestCase):
    def test_usda_pointer_repeats_root_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            path, ver = publish_into_layout(_src(tmp, "a.usda", _USDA), dest, _BASE, user="adam")
            self.assertEqual((path, ver), (dest / f"{_BASE}_LAST.usda", 1))
            text = path.read_text()
            self.assertIn(f"@./{_BASE}_v001.usda@", text)
            self.assertIn('defaultPrim = "hero"', text)
            self.assertIn("metersPerUnit = 0.01", text)
            self.assertIn('upAxis = "Z"', text)
            self.assertIn("startTimeCode = 1001.0", text)
            flux = lp.read_layer_flux(path)
            self.assertEqual(flux["version"], "v001")
            self.assertEqual(flux["target"], f"{_BASE}_v001.usda")
            self.assertEqual(flux["user"], "adam")
            self.assertEqual((dest / f"{_BASE}_v001.usda").read_text(), _USDA)
            self.assertFalse((dest / f"{_BASE}_LAST.usda.flux.json").exists())

            publish_into_layout(_src(tmp, "b.usda", _USDA), dest, _BASE)
            self.assertEqual(last_version_label(dest, _BASE, ".usda"), "v002")
            self.assertEqual(highest_flat_version(dest, _BASE, ".usda"), 2)

    def test_pointer_layer_opens_in_usd(self):
        try:
            from pxr import Sdf, Usd
        except ImportError:
            self.skipTest("pxr not available")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            path, _ = publish_into_layout(_src(tmp, "a.usda", _USDA), dest, _BASE)
            stage = Usd.Stage.Open(str(path))
            self.assertTrue(stage.GetPrimAtPath("/hero").IsValid())
            self.assertEqual(stage.GetDefaultPrim().GetName(), "hero")
            del stage
            # crate pointer for .usdc
            crate_src = tmp / "c.usdc"
            Sdf.Layer.OpenAsAnonymous(str(_src(tmp, "c.usda", _USDA))).Export(str(crate_src))
            cpath, _ = publish_into_layout(crate_src, dest, _BASE)
            self.assertEqual(cpath, dest / f"{_BASE}_LAST.usdc")
            self.assertFalse(cpath.read_bytes().startswith(b"#usda"))
            self.assertEqual(lp.read_layer_flux(cpath)["version"], "v001")
            stage = Usd.Stage.Open(str(cpath))
            self.assertTrue(stage.GetPrimAtPath("/hero").IsValid())
            del stage

    def test_one_last_per_usd_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            publish_into_layout(_src(tmp, "a.usda", _USDA), dest, _BASE)
            publish_into_layout(_src(tmp, "b.usda", _USDA), dest, _BASE)
            _, ver = publish_into_layout(_src(tmp, "c.usd", _USDA), dest, _BASE)
            self.assertEqual(ver, 1)
            self.assertEqual(last_version_label(dest, _BASE, ".usda"), "v002")
            self.assertEqual(last_version_label(dest, _BASE, ".usd"), "v001")


class LinkLast(unittest.TestCase):
    def test_heavy_file_gets_a_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            settings = {"last_mode": {}, "last_link_threshold_gb": 1e-9}
            publish_into_layout(_src(tmp, "a.abc", "small-copy"), dest, _BASE,
                                settings={"last_mode": {}, "last_link_threshold_gb": 2})
            self.assertTrue((dest / f"{_BASE}_LAST.abc").is_file())
            path, ver = publish_into_layout(_src(tmp, "b.abc", "heavy"), dest, _BASE,
                                            settings=settings)
            self.assertEqual((path, ver), (dest / f"{_BASE}_v002.abc", 2))
            link = dest / f"{_BASE}_LAST.abc.link"
            data = json.loads(link.read_text())
            self.assertEqual(data["target"], f"{_BASE}_v002.abc")
            self.assertEqual(data["version"], "v002")
            # stale copy + sidecar removed, both versions kept
            self.assertFalse((dest / f"{_BASE}_LAST.abc").exists())
            self.assertFalse((dest / f"{_BASE}_LAST.abc.flux.json").exists())
            self.assertEqual((dest / f"{_BASE}_v001.abc").read_text(), "small-copy")
            # readers follow the link
            self.assertEqual(find_last_file(dest, _BASE, "abc"), dest / f"{_BASE}_v002.abc")
            self.assertEqual(get_last_file(dest, _BASE).read_text(), "heavy")
            self.assertEqual(next_publish_version(dest, _BASE, ".abc"), 3)

    def test_importer_follows_link(self):
        from features.folder_manager.tokens import build_default_tokens, save_tokens
        from features.publisher.publish_core import resolve_publish_path
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            save_tokens(proj, build_default_tokens())
            base = "CHAR_RIG_CECILE_ALL"
            dest = resolve_publish_path(proj, f"{base}_LAST.abc")
            publish_into_layout(_src(proj, "a.abc", "heavy"), dest, base,
                                settings={"last_mode": {".abc": "link"}})
            ir._BCACHE.clear()
            self.assertEqual(ir.get_available_iters(proj, "CHAR", "RIG", "CECILE", "all"),
                             ["LAST", "v001"])
            res = ir.resolve_import_path(proj, "CHAR", "RIG", "CECILE", "all", "LAST")
            self.assertTrue(res["ok"], res)
            self.assertEqual(Path(res["path"]), dest / f"{base}_v001.abc")
            self.assertEqual(res["ext"], ".abc")


class LegacyAndConcurrency(unittest.TestCase):
    def test_legacy_last_is_archived_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            dest.mkdir()
            (dest / f"{_BASE}_v001.abc").write_text("old1")
            (dest / f"{_BASE}_LAST.abc").write_text("old2")   # pre 0017: no version file
            self.assertEqual(next_publish_version(dest, _BASE, ".abc"), 3)
            path, ver = publish_into_layout(_src(tmp, "n.abc", "new"), dest, _BASE)
            self.assertEqual(ver, 3)
            self.assertEqual((dest / f"{_BASE}_v002.abc").read_text(), "old2")
            self.assertEqual((dest / f"{_BASE}_v003.abc").read_text(), "new")
            self.assertEqual(path.read_text(), "new")
            self.assertEqual(last_version_label(dest, _BASE, ".abc"), "v003")

    def test_legacy_usd_copy_is_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            dest.mkdir()
            (dest / f"{_BASE}_LAST.usda").write_text(_USDA)
            _, ver = publish_into_layout(_src(tmp, "n.usda", _USDA), dest, _BASE)
            self.assertEqual(ver, 2)
            self.assertEqual((dest / f"{_BASE}_v001.usda").read_text(), _USDA)

    def test_existing_target_bumps_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            dest.mkdir()
            (dest / f"{_BASE}_v001.abc").write_text("other publisher")
            path, ver = lp.write_version(_src(tmp, "a.abc", "mine"), dest, _BASE, ".abc", 1)
            self.assertEqual((path.name, ver), (f"{_BASE}_v002.abc", 2))
            self.assertEqual((dest / f"{_BASE}_v001.abc").read_text(), "other publisher")
            self.assertEqual([p for p in dest.iterdir() if lp.is_temp_name(p.name)], [])

    def test_locked_last_keeps_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            publish_into_layout(_src(tmp, "a.abc", "v1"), dest, _BASE)
            real_replace = os.replace

            def locked(src, dst):
                if Path(dst).name == f"{_BASE}_LAST.abc":
                    raise PermissionError("locked by a DCC")
                return real_replace(src, dst)

            with mock.patch.object(lp.os, "replace", side_effect=locked), \
                    mock.patch.object(lp, "REPLACE_DELAY_S", 0):
                path, ver = publish_into_layout(_src(tmp, "b.abc", "v2"), dest, _BASE)
            self.assertEqual((path, ver), (dest / f"{_BASE}_v002.abc", 2))
            self.assertEqual((dest / f"{_BASE}_LAST.abc").read_text(), "v1")
            self.assertEqual(last_version_label(dest, _BASE, ".abc"), "v001")
            self.assertEqual([p for p in dest.iterdir() if lp.is_temp_name(p.name)], [])

    def test_bgeo_sc_single_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            publish_into_layout(_src(tmp, "a.bgeo.sc", "1"), dest, _BASE)
            path, ver = publish_into_layout(_src(tmp, "b.bgeo.sc", "2"), dest, _BASE)
            self.assertEqual((path.name, ver), (f"{_BASE}_LAST.bgeo.sc", 2))
            self.assertTrue((dest / f"{_BASE}_v002.bgeo.sc").is_file())
            self.assertTrue((dest / f"{_BASE}_LAST.bgeo.sc.flux.json").is_file())
            self.assertEqual(highest_flat_version(dest, _BASE, ".bgeo.sc"), 2)
            self.assertEqual(highest_flat_version(dest, _BASE, ".sc"), 0)


class RopWriterCompat(unittest.TestCase):
    def test_archive_flat_last_on_derived_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dest = tmp / "pub"
            publish_into_layout(_src(tmp, "a.abc", "v1"), dest, _BASE)
            self.assertEqual(archive_flat_last(dest, _BASE, ".abc"), 1)
            # metadata dropped, no duplicate version written
            self.assertFalse((dest / f"{_BASE}_LAST.abc.flux.json").exists())
            self.assertFalse((dest / f"{_BASE}_v002.abc").exists())
            # the ROP then renders straight into LAST: the next publish archives it
            (dest / f"{_BASE}_LAST.abc").write_text("rop v2")
            _, ver = publish_into_layout(_src(tmp, "c.abc", "v3"), dest, _BASE)
            self.assertEqual(ver, 3)
            self.assertEqual((dest / f"{_BASE}_v002.abc").read_text(), "rop v2")

    def test_archive_flat_last_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / f"{_BASE}_LAST.abc").write_text("old")
            self.assertEqual(archive_flat_last(dest, _BASE, ".abc"), 1)
            self.assertEqual((dest / f"{_BASE}_v001.abc").read_text(), "old")
            self.assertEqual((dest / f"{_BASE}_LAST.abc").read_text(), "old")
            self.assertIsNone(archive_flat_last(dest, _BASE, ".fbx"))


if __name__ == "__main__":
    unittest.main()
