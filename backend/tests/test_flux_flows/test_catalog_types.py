# P4 (2026-10-23): app/src/pages/flow_editor/portTypes.ts is the TS mirror of
# flux_flows/types.py (refusal while dragging a link, 03_EDITEUR §5). No front test
# runner: the TS literals are read as text and compared to the Python tables and to
# the "types" of GET /flows/catalog.

from __future__ import annotations

import re
import unittest
from pathlib import Path

from flux_flows import types
from flux_flows.nodes import registry

TS = Path(__file__).resolve().parents[3] / "app" / "src" / "pages" / "flow_editor" / "portTypes.ts"


def _ts() -> str:
    return TS.read_text(encoding="utf-8")


def _block(text: str, start: str) -> str:
    i = text.index(start)
    return text[i:text.index("}", i)]


class PortTypesMirror(unittest.TestCase):
    def test_scalars_match(self) -> None:
        line = re.search(r"export const SCALARS = \[(.*?)\]", _ts()).group(1)
        self.assertEqual(tuple(re.findall(r"'([^']+)'", line)), types.SCALARS)

    def test_implicit_matches(self) -> None:
        body = _block(_ts(), "export const IMPLICIT")
        ts = {k: tuple(re.findall(r"'([^']+)'", v)) for k, v in re.findall(r"(\w+): \[([^\]]*)\]", body)}
        self.assertEqual(ts, dict(types._IMPLICIT))

    def test_advice_pairs_match(self) -> None:
        body = _block(_ts(), "const ADVICE")
        ts = set(tuple(k.split(">")) for k in re.findall(r"'(\w+>[\w*]+)':", body))
        py = {k for k in types._ADVICE if k != ("any", "*")}   # any>* is a branch of canConnect
        self.assertEqual(ts, py)

    def test_catalog_types_are_the_mirrored_ones(self) -> None:
        listed = {t["id"]: t["implicit"] for t in registry.catalog(None)["types"]}
        for scalar in types.SCALARS:
            self.assertEqual(listed[scalar], list(types._IMPLICIT.get(scalar, ())))
        self.assertIn("list[T]", listed)
        self.assertIn("session[<soft>]", listed)


if __name__ == "__main__":
    unittest.main()
