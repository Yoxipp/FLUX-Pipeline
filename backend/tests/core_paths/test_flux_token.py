# test_flux_token.py - the $FLUX portable path token (priority n3, phase F0).
#
# Pure and offline: every case passes the root explicitly, so nothing depends on
# config.json / get_flux_root (except the two cases that assert its use, which
# mock it).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import paths


class ToFluxTokenTests(unittest.TestCase):
    def test_path_under_root_is_tokenised(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "DOSSIER_PROJETS" / "ZDDZ" / "body.exr"
            self.assertEqual(
                paths.to_flux_token(p, root=root),
                "$FLUX/DOSSIER_PROJETS/ZDDZ/body.exr",
            )

    def test_root_itself_is_bare_token(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(paths.to_flux_token(root, root=root), "$FLUX")

    def test_path_outside_root_is_left_absolute(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            root = Path(d1)
            outside = Path(d2) / "extern" / "tex.png"
            self.assertEqual(paths.to_flux_token(outside, root=root), str(outside))

    def test_no_root_returns_path_unchanged(self):
        with mock.patch.object(paths, "get_flux_root", return_value=None):
            p = Path("D:/whatever/x.exr")
            self.assertEqual(paths.to_flux_token(p), str(p))


class FromFluxTokenTests(unittest.TestCase):
    def test_token_resolves_under_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(
                paths.from_flux_token("$FLUX/DOSSIER_PROJETS/ZDDZ/body.exr", root=root),
                root / "DOSSIER_PROJETS" / "ZDDZ" / "body.exr",
            )

    def test_braced_form(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(
                paths.from_flux_token("${FLUX}/a/b", root=root), root / "a" / "b"
            )

    def test_backslash_token(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(
                paths.from_flux_token("$FLUX\\a\\b", root=root), root / "a" / "b"
            )

    def test_bare_token_is_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(paths.from_flux_token("$FLUX", root=root), root)

    def test_non_token_returned_unchanged(self):
        p = "D:/already/absolute/x.exr"
        self.assertEqual(paths.from_flux_token(p, root=Path("E:/root")), Path(p))

    def test_token_without_root_raises(self):
        with mock.patch.object(paths, "get_flux_root", return_value=None):
            with self.assertRaises(RuntimeError):
                paths.from_flux_token("$FLUX/x")


class RoundTripTests(unittest.TestCase):
    def test_round_trip_under_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "DOSSIER_PROJETS" / "SHOW" / "caches" / "sim.abc"
            token = paths.to_flux_token(p, root=root)
            self.assertEqual(paths.from_flux_token(token, root=root), p)


if __name__ == "__main__":
    unittest.main()
