# P3 (2026-10-23): call_function v1 limited to FLUX's packages (01 §16, decided by the maintainer).

from __future__ import annotations

import unittest

from flux_actions.commands.call_function import check_function_ref, resolve_function


class CallFunctionScope(unittest.TestCase):
    def test_flux_packages_allowed(self) -> None:
        func = resolve_function("core.paths:to_flux_token")
        self.assertTrue(callable(func))
        self.assertEqual(check_function_ref("features.production.archive:archive_folder"),
                         ("features.production.archive", "archive_folder"))

    def test_other_modules_refused(self) -> None:
        for ref in ("os:remove", "subprocess:run", "shutil:rmtree", "builtins:eval",
                    "flux_actions.runner:run_publish_action", "corex.paths:x", "core._private:x",
                    "core..paths:x", "core.paths:_hidden", "core.paths", ":x"):
            with self.assertRaises(ValueError, msg=ref):
                resolve_function(ref)

    def test_refusal_names_the_rule(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_function("os:remove")
        self.assertIn("features, core, dcc", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
