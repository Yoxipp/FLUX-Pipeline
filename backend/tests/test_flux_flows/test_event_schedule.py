# P5 (2026-10-23): event.schedule, slots noted before the run, catch up once (decision 22).

from __future__ import annotations

import unittest
from datetime import datetime

from flux_flows import scheduler
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows import _sched_helpers as s

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816

THU_0900 = datetime(2026, 10, 22, 9, 0, 30)     # a Thursday


class Slots(unittest.TestCase):
    def test_last_and_next_slot(self) -> None:
        self.assertEqual(scheduler.last_slot(THU_0900, "daily", "08:00"), datetime(2026, 10, 22, 8, 0))
        self.assertEqual(scheduler.last_slot(THU_0900, "daily", "10:00"), datetime(2026, 10, 21, 10, 0))
        self.assertEqual(scheduler.last_slot(THU_0900, "mon", "08:00"), datetime(2026, 10, 19, 8, 0))
        self.assertEqual(scheduler.next_slot(THU_0900, "sat,sun", "08:00"), datetime(2026, 10, 24, 8, 0))
        self.assertIsNone(scheduler.last_slot(THU_0900, "funday", "08:00"))

    def test_param_errors(self) -> None:
        self.assertIsNone(scheduler.schedule_param_error("days", "mon, fri"))
        self.assertIsNotNone(scheduler.schedule_param_error("days", "lundi"))
        self.assertIsNotNone(scheduler.schedule_param_error("time", "25:00"))
        self.assertIsNotNone(scheduler.schedule_param_error("time", "8h"))
        self.assertIsNotNone(scheduler.schedule_param_error("missed", "always"))

    def test_validation_reports_a_bad_time(self) -> None:
        from flux_flows import validate

        flow = s.record_flow("sched_bad", "event.schedule", {"time": "8h"})
        codes = [(i.code, i.port) for i in validate.validate(flow, validate.Env())]
        self.assertIn(("E_PARAM_INVALID", "time"), codes)


class ScheduleTick(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.env = s.Env()

    def tearDown(self) -> None:
        self.env.close()

    def _watcher(self, sched, af):
        sched_w = sched._wanted()
        return [w for w in sched_w if w.af.name == af.name][0]

    def test_on_time_slot_fires_once(self) -> None:
        af = self.env.active(s.record_flow("sched_a", "event.schedule", {"days": "daily", "time": "09:00"}))
        sched = s.make(self.env, [af], now=THU_0900)
        w = self._watcher(sched, af)

        async def scenario():
            first = await sched.schedule_tick(w)
            second = await sched.schedule_tick(w)
            return await s.settle(first), second

        (rec,), second = s.run(scenario())
        self.assertEqual(rec["status"], "ok")
        self.assertIsNone(second)
        self.assertEqual(len(h.CALLS), 1)
        self.assertEqual(rec["trigger"]["payload"]["missed"], "false")
        self.assertEqual(self.env.state("sched_a")["last_schedule"]["ev"]["slot"], "2026-10-22T09:00:00")

    def test_missed_slot_catches_up_once(self) -> None:
        af = self.env.active(s.record_flow("sched_b", "event.schedule", {"time": "08:00"}))
        sched = s.make(self.env, [af], now=THU_0900)
        w = self._watcher(sched, af)

        async def scenario():
            recs = [await sched.schedule_tick(w) for _ in range(3)]
            return await s.settle(*recs)

        recs = s.run(scenario())
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["trigger"]["payload"]["missed"], "true")
        self.assertEqual(recs[0]["trigger"]["payload"]["fired_at"], "2026-10-22T08:00:00")

    def test_missed_slot_skip_notes_without_firing(self) -> None:
        af = self.env.active(s.record_flow("sched_c", "event.schedule", {"time": "08:00", "missed": "skip"}))
        sched = s.make(self.env, [af], now=THU_0900)
        self.assertIsNone(s.run(sched.schedule_tick(self._watcher(sched, af))))
        self.assertEqual(h.CALLS, [])
        noted = self.env.state("sched_c")["last_schedule"]["ev"]
        self.assertEqual((noted["slot"], noted["ran_at"]), ("2026-10-22T08:00:00", None))

    def test_activation_notes_the_last_slot(self) -> None:
        af = self.env.active(s.record_flow("sched_d", "event.schedule", {"time": "08:00"}))
        scheduler.note_activation(self.env.team, "sched_d", af.flow, now=THU_0900)
        sched = s.make(self.env, [af], now=THU_0900)
        self.assertIsNone(s.run(sched.schedule_tick(self._watcher(sched, af))))
        self.assertEqual(h.CALLS, [])

    def test_two_backends_fire_a_slot_once(self) -> None:
        af = self.env.active(s.record_flow("sched_e", "event.schedule", {"time": "09:00"}))
        a, b = s.make(self.env, [af], now=THU_0900), s.make(self.env, [af], now=THU_0900)

        async def scenario():
            ra = await a.schedule_tick(self._watcher(a, af))
            rb = await b.schedule_tick(self._watcher(b, af))
            return await s.settle(ra, rb)

        self.assertEqual(len(s.run(scenario())), 1)
        self.assertEqual(len(h.CALLS), 1)


if __name__ == "__main__":
    unittest.main()
