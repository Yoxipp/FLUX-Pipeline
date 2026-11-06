# P5 (2026-10-23): event.when, pure condition evaluated each tick, fires on false -> true.

from __future__ import annotations

import unittest

from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows import _sched_helpers as s

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


class When(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.env = s.Env()
        self.flag = self.env.tmp / "done.txt"

    def tearDown(self) -> None:
        self.env.close()

    def _flow(self):
        flow = h.flow({"ex": ("logic.exists", {"path": str(self.flag)}), "ev": "event.when",
                       "rec": "action.t_record"},
                      ["ex.result->ev.condition", "ev.then->rec.exec"], name="when_done")
        return self.env.active(flow)

    def test_fires_on_false_to_true_only(self) -> None:
        af = self._flow()
        sched = s.make(self.env, [af])
        w = sched._wanted()[0]

        async def scenario():
            out = []
            for act in (None, lambda: self.flag.write_text("x"), None, lambda: self.flag.unlink(),
                        lambda: self.flag.write_text("x")):
                if act:
                    act()
                out.append(await sched.when_tick(w))
            await s.settle(*out)
            return [bool(r) for r in out]

        self.assertEqual(s.run(scenario()), [False, True, False, False, True])

    def test_true_at_first_is_a_baseline(self) -> None:
        self.flag.write_text("x")
        af = self._flow()
        sched = s.make(self.env, [af])
        w = sched._wanted()[0]
        self.assertIsNone(s.run(sched.when_tick(w)))
        self.assertEqual(h.CALLS, [])


if __name__ == "__main__":
    unittest.main()
