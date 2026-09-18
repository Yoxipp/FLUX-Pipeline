# Live 2026-09-18: a Maya with no main window held the FLUX port and FLUX exported
# its empty scene. A proven ghost is never the target.

from __future__ import annotations

import unittest

from dcc.maya.maya_connection import GhostMayaError, pick_live_port


def _probe(states: dict[int, bool | None]):
    return lambda port: states.get(port)


class PickLivePort(unittest.TestCase):
    def test_a_visible_maya_is_kept(self) -> None:
        self.assertEqual(pick_live_port(7001, [7001, 7002], probe=_probe({7001: True, 7002: True})), 7001)

    def test_a_ghost_is_skipped_for_a_visible_instance(self) -> None:
        self.assertEqual(pick_live_port(7001, [7001, 7002], probe=_probe({7001: False, 7002: True})), 7002)

    def test_a_lone_ghost_is_refused_with_a_clear_message(self) -> None:
        with self.assertRaises(GhostMayaError) as ctx:
            pick_live_port(7001, [7001], probe=_probe({7001: False}))
        self.assertIn("Gestionnaire des taches", str(ctx.exception))

    def test_a_busy_maya_is_not_mistaken_for_a_ghost(self) -> None:
        # No answer (long command running) is not proof of a ghost.
        self.assertEqual(pick_live_port(7001, [7001, 7002], probe=_probe({7001: None, 7002: True})), 7001)


if __name__ == "__main__":
    unittest.main()
