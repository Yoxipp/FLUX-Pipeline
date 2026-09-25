# test_move_to_local_token.py - move_to_local resolves a portable $FLUX token (F2).
#
# The HDA may hand a "$FLUX/..." path to /houdini/import/move_to_local when portable
# paths are on. move_to_local must resolve it back to a local absolute before copying.
# Offline: an explicit dest_folder avoids any Houdini round-trip.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import paths
from dcc.houdini.houdini_import import move_to_local


class MoveToLocalTokenTests(unittest.TestCase):
    def test_flux_token_is_resolved_before_copy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "DOSSIER_PROJETS" / "ZDDZ" / "tex.exr"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(b"pixels")
            dest = root / "local"

            token = paths.to_flux_token(src, root=root)
            self.assertTrue(token.startswith("$FLUX"))

            with mock.patch.object(paths, "get_flux_root", return_value=root):
                result = move_to_local(token, dest_folder=dest)

            self.assertTrue(result["ok"], result)
            self.assertEqual(Path(result["abs_path"]).read_bytes(), b"pixels")
            self.assertEqual(Path(result["abs_path"]).parent, dest)

    def test_plain_absolute_path_still_works(self):
        # from_flux_token is a no-op on a normal path: no regression when portable
        # paths are off and the caller passes a resolved absolute.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "tex.png"
            src.write_bytes(b"data")
            dest = root / "local"
            result = move_to_local(str(src), dest_folder=dest)
            self.assertTrue(result["ok"], result)
            self.assertEqual(Path(result["abs_path"]).read_bytes(), b"data")


if __name__ == "__main__":
    unittest.main()
