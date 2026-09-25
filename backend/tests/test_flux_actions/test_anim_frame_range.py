# test_anim_frame_range.py — animated single-file exports (abc / USD) over a frame range.
#
# ANIMATION (one file with time samples) is independent of SEQUENCE ($F4 folder).
# Maya: the commandPort command carries frame_start/end/step for .abc AND USD.
# Houdini: a SOP .usd export uses the SOP "ROP USD Output" (usdexport), never
# rop_geometry (which wrote classic geo under a .usd name), and drives its frame
# range through trange + Execute since SOP ROPs have no render().

from __future__ import annotations

import asyncio
import logging
import unittest
from pathlib import Path
from unittest import mock

from dcc.maya import maya_export_client
from dcc.houdini import houdini_export


class MayaBuildCommand(unittest.TestCase):
    def _cmd(self, ext, fr):
        return maya_export_client._build_command(
            Path("C:/tmp/out" + ext), Path("C:/tmp/res.json"), ext, "scene", fr, None)

    def test_usd_carries_range_and_step(self):
        cmd = self._cmd(".usd", (1, 24, 2))
        self.assertIn("frame_start=1, frame_end=24, frame_step=2.0", cmd)

    def test_abc_range_without_step_defaults_to_one(self):
        self.assertIn("frame_start=10, frame_end=20, frame_step=1.0", self._cmd(".abc", (10, 20)))

    def test_static_formats_ignore_range(self):
        self.assertNotIn("frame_start", self._cmd(".mb", (1, 24, 1)))

    def test_no_range_is_static(self):
        self.assertNotIn("frame_start", self._cmd(".usda", None))


class MayaExportCommandRange(unittest.TestCase):
    def test_three_value_range_reaches_client(self):
        from flux_actions.commands.maya_export import MayaExport

        captured = {}

        def fake_export(out_path, extension, scope, **kw):
            captured.update(kw)
            Path(out_path).write_bytes(b"x")
            return Path(out_path), []

        with mock.patch("flux_actions.commands.maya_export.run_maya_export", side_effect=fake_export):
            asyncio.run(MayaExport().run(
                {"filename": "CHAR_ANIM_X_null.usd", "extension": ".usd", "scope": "scene",
                 "frame_range": [1, 48, 2]},
                None, logging.getLogger("test")))
        self.assertEqual(captured["frame_range"], (1.0, 48.0, 2.0))


class HoudiniExportViaNode(unittest.TestCase):
    def _code(self, ext, fr):
        with mock.patch.object(houdini_export.houdini_client, "run", return_value={"ok": True}) as run:
            houdini_export.export_via_node("/obj/geo1/xf", ext, Path("C:/tmp/out" + ext), fr)
        return run.call_args[0][0]

    def test_usd_uses_sop_usd_rop(self):
        code = self._code(".usd", (1, 24, 1))
        self.assertIn("'usdexport'", code)
        self.assertIn("_fr = (1, 24, 1)", code)
        self.assertIn("pressButton()", code)

    def test_abc_keeps_alembic_rop(self):
        self.assertIn("'rop_alembic'", self._code(".abc", (1, 24, 1)))


if __name__ == "__main__":
    unittest.main()
