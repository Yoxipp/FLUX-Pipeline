# test_open_in_needs_hda.py - Open in Houdini keeps FLUX Import: a missing HDA is
# installed, never silently replaced by a Reference LOP (2026-09-26).

from __future__ import annotations

import unittest
from unittest import mock

from dcc.houdini import houdini_import as hi


class OpenInNeedsHda(unittest.TestCase):
    def _code(self, **kw) -> str:
        sent = {}
        with mock.patch.object(hi.houdini_client, "run", side_effect=lambda c: sent.setdefault("code", c) and {"ok": True}):
            hi.create_usd_context_import("$FLUX/P/a.usda", {"default_prim": "UTAH"},
                                         {"source_mode": "library", "lib_item": "component:UTAH"}, **kw)
        return sent["code"]

    def test_checks_the_hda_before_any_node(self):
        code = self._code()
        compile(code, "<houdini>", "exec")
        self.assertIn("FLUX_NEED_HDA", code)
        self.assertLess(code.index("FLUX_NEED_HDA"), code.index('createNode("flux_importer"'))
        self.assertIn("if True and not False:", code)

    def test_retry_may_fall_back(self):
        code = self._code(allow_fallback=True)
        compile(code, "<houdini>", "exec")
        self.assertIn("if True and not True:", code)


if __name__ == "__main__":
    unittest.main()
