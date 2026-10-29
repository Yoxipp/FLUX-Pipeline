# P5 (2026-10-23): event.new_file, first scan = baseline, one run per new file,
# stable size on two scans, seen files kept across restarts.

from __future__ import annotations

import unittest

from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows import _sched_helpers as s

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


class NewFile(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.env = s.Env()
        self.drop = self.env.tmp / "drop"
        self.drop.mkdir()

    def tearDown(self) -> None:
        self.env.close()

    def _flow(self, **params):
        flow = h.flow({"ev": ("event.new_file", {"folder": str(self.drop), **params}),
                       "rec": "action.t_record"},
                      ["ev.then->rec.exec", "ev.name->rec.value"], name="drop_watch")
        return self.env.active(flow)

    def _ticks(self, sched, af, actions):
        """actions: list of callables run before each tick. Returns the names recorded."""
        w = [w for w in sched._wanted() if w.af.name == af.name][0]

        async def scenario():
            for act in actions:
                if act:
                    act()
                await s.settle(*await sched.new_file_tick(w))

        s.run(scenario())
        return [value for _node, value in h.CALLS]

    def _write(self, name: str, text: str = "x"):
        return lambda: (self.drop / name).write_text(text, encoding="utf-8")

    def test_first_scan_is_a_baseline(self) -> None:
        (self.drop / "old.jpg").write_text("x", encoding="utf-8")
        af = self._flow(wait_stable=False)
        self.assertEqual(self._ticks(s.make(self.env, [af]), af, [None, None, self._write("new.jpg"), None]),
                         ["new.jpg"])

    def test_waits_for_a_stable_size(self) -> None:
        af = self._flow()
        names = self._ticks(s.make(self.env, [af]), af,
                            [None, self._write("a.jpg", "1"), self._write("a.jpg", "12"), None, None])
        self.assertEqual(names, ["a.jpg"])

    def test_pattern_filters_names(self) -> None:
        af = self._flow(pattern="*.jpg", wait_stable=False)
        names = self._ticks(s.make(self.env, [af]), af, [None, self._write("a.jpg"), self._write("b.txt"), None])
        self.assertEqual(names, ["a.jpg"])

    def test_files_dropped_while_closed_fire_at_restart(self) -> None:
        af = self._flow(wait_stable=False)
        self._ticks(s.make(self.env, [af]), af, [None])          # baseline saved
        (self.drop / "late.jpg").write_text("x", encoding="utf-8")
        self.assertEqual(self._ticks(s.make(self.env, [af]), af, [None]), ["late.jpg"])

    def test_missing_folder_is_reported_not_fired(self) -> None:
        flow = h.flow({"ev": ("event.new_file", {"folder": str(self.env.tmp / "nope")}), "rec": "action.t_record"},
                      ["ev.then->rec.exec"], name="drop_missing")
        af = self.env.active(flow)
        sched = s.make(self.env, [af])
        w = sched._wanted()[0]
        self.assertEqual(s.run(sched.new_file_tick(w)), [])
        self.assertIn("introuvable", w.state["error"])


if __name__ == "__main__":
    unittest.main()
