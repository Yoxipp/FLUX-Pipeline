# P5 (2026-10-23): the scheduler (01 §9): switch, idle without user / FLUX_ROOT, which
# watchers are armed where, cap, lock lost, scene_opened polling, on_publish, routes.

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flux_flows import engine, events, hooks, hosts, locations, scheduler
from routers import flows as flows_router
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows import _sched_helpers as s

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


def _flow(name: str, event_type: str, params=None):
    return s.record_flow(name, event_type, params or {})


class Switch(unittest.TestCase):
    def test_switch_off_means_no_scheduler(self) -> None:
        with mock.patch.dict(os.environ, {scheduler.SWITCH_ENV: "0"}):
            self.assertFalse(scheduler.enabled())
            self.assertIsNone(scheduler.start())
        self.assertTrue(scheduler.enabled())

    def test_start_and_stop_in_a_loop(self) -> None:
        async def scenario():
            with mock.patch.object(scheduler.Scheduler, "beat", new=mock.AsyncMock()):
                sched = scheduler.start()
                await asyncio.sleep(0)
                self.assertIs(scheduler.get(), sched)
                await scheduler.stop()
            return scheduler.get()

        self.assertIsNone(asyncio.run(scenario()))

    def test_idle_without_user_or_root(self) -> None:
        sched = scheduler.Scheduler(user_fn=lambda: None)
        asyncio.run(sched.beat(0))
        self.assertEqual(sched.reason, "pas d'utilisateur")
        sched = scheduler.Scheduler(user_fn=lambda: "ADAM")
        with mock.patch.object(locations, "extensions_dir", side_effect=RuntimeError("no root")):
            asyncio.run(sched.beat(0))
        self.assertEqual(sched.reason, "FLUX_ROOT inconnu")
        self.assertIsNone(sched.lock)


class Arming(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.env = s.Env()

    def tearDown(self) -> None:
        self.env.close()

    def _kinds(self, sched):
        return sorted((w.af.scope, w.kind) for w in sched._wanted())

    def test_global_events_only_on_the_holder_perso_always(self) -> None:
        team = self.env.active(_flow("t_when", "event.when", {"condition": True}))
        perso = scheduler.ActiveFlow("perso", None, "p_when", 1, _flow("p_when", "event.when", {"condition": True}),
                                     self.env.team)
        scene = self.env.active(_flow("t_scene", "event.scene_opened", {"soft": "maya"}))
        follower = s.make(self.env, [team, perso, scene], holder=False)
        self.assertEqual(self._kinds(follower), [("perso", "event.when"), ("team", "event.scene_opened")])
        holder = s.make(self.env, [team, perso, scene], holder=True)
        self.assertEqual(len(self._kinds(holder)), 3)

    def test_cap_of_watchers(self) -> None:
        flows = [self.env.active(_flow(f"cap_{i}", "event.when", {"condition": True})) for i in range(4)]
        sched = s.make(self.env, flows, max_watchers=2)

        async def scenario():
            await sched._arm()
            armed, over = len(sched.watchers), list(sched.skipped)
            await sched._disarm_all("test")
            return armed, over

        armed, over = s.run(scenario())
        self.assertEqual((armed, len(over)), (2, 2))

    def test_lost_lock_interrupts_the_global_runs(self) -> None:
        flow = h.flow({"ev": ("event.when", {"condition": True}), "slow": ("action.t_sleep", {"seconds": 5})},
                      ["ev.then->slow.exec"], name="slow_when")
        af = self.env.active(flow)
        sched = s.make(self.env, [af])

        async def scenario():
            rec = await sched.fire(af, "ev", {}, track=True)
            await asyncio.sleep(0.05)
            sched.lock.holder = False
            await sched._interrupt_global("verrou perdu")
            return await engine.manager().wait(rec["run_id"])

        rec = s.run(scenario())
        self.assertEqual((rec["status"], rec["error"]), ("interrupted", "verrou perdu"))

    def test_beat_elects_and_arms(self) -> None:
        af = self.env.active(_flow("beat_when", "event.when", {"condition": True}))
        lock = hosts.HostLock(self.env.tmp / "runs" / "host.lock", user="ADAM", sleep=mock.AsyncMock(),
                              settle=(0, 0), confirm_s=0)
        sched = scheduler.Scheduler(user_fn=lambda: "ADAM", lock=lock, scan_fn=lambda _u: [af])
        seen = []

        async def scenario():
            sub = events.subscribe()
            with mock.patch.object(locations, "extensions_dir", return_value=self.env.tmp):
                await sched.beat(0)
            seen.extend(sub.pending())
            events.unsubscribe(sub)
            kinds = [w.kind for w in sched.watchers.values()]
            await sched.stop()
            return kinds

        self.assertEqual(s.run(scenario()), ["event.when"])
        self.assertTrue(lock.holder is False)                 # released by stop
        self.assertEqual(seen[0]["type"], "host")
        self.assertTrue(seen[0]["is_holder"])


class SceneOpened(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.env = s.Env()

    def tearDown(self) -> None:
        self.env.close()

    def test_scene_change_fires_after_a_baseline(self) -> None:
        af = self.env.active(h.flow({"ev": ("event.scene_opened", {"soft": "houdini"}), "rec": "action.t_record"},
                                    ["ev.then->rec.exec", "ev.scene->rec.value"], name="on_scene"))
        scenes = {48884: "a.hip"}
        sched = s.make(self.env, [af], instances_fn=lambda dcc: [{"port": p, "pid": 7} for p in scenes],
                       context_fn=lambda dcc, port: {"scene": scenes[port]})

        async def scenario():
            for w in sched._wanted():          # armed without the poller task: the test drives the ticks
                sched.watchers[w.key] = w
            out = []

            async def tick():
                recs = await sched.scene_tick("houdini")
                await s.settle(*recs)            # run_policy skip_if_running: one at a time
                out.append(recs)

            await tick()
            scenes[48884] = "b.hip"
            await tick()
            await tick()
            scenes[48885] = "c.hip"              # a new instance with a scene
            await tick()
            return [len(r) for r in out]

        self.assertEqual(s.run(scenario()), [0, 1, 0, 1])
        self.assertEqual([v for _n, v in h.CALLS], ["b.hip", "c.hip"])


class OnPublish(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.env = s.Env()

    def tearDown(self) -> None:
        self.env.close()

    def test_matching_filters(self) -> None:
        af = self.env.active(_flow("pub_usd", "event.on_publish", {"type": "usd", "name": "chair_*"}))
        sig = {"user": "ADAM", "filename": "chair_model_v003.usd", "project": "P", "dest_folder": "/p/pub"}
        self.assertEqual(len(hooks.matching([af], sig)), 1)
        self.assertEqual(hooks.matching([af], {**sig, "filename": "chair_model_v003.ma"}), [])
        self.assertEqual(hooks.matching([af], {**sig, "filename": "table_model_v003.usd"}), [])
        # The soft comes from the extension: a .usd has none, a .hip is houdini.
        hou = self.env.active(_flow("pub_hou", "event.on_publish", {"soft": "houdini"}))
        self.assertEqual(hooks.matching([hou], sig), [])
        self.assertEqual(len(hooks.matching([hou], {**sig, "filename": "fx_v002.hip"})), 1)
        payload = hooks.matching([af], sig)[0][2]
        self.assertEqual((payload["publish"]["version"], payload["project"]), (3, "P"))

    def test_publish_done_starts_the_flow(self) -> None:
        flow = h.flow({"ev": ("event.on_publish", {}), "rec": "action.t_record"},
                      ["ev.then->rec.exec", "ev.project->rec.value"], name="pub_any")
        af = self.env.active(flow)
        sched = s.make(self.env, [af])

        async def scenario():
            sched._listener = events.listen("publish_done", sched._on_publish)
            try:
                events.publish_done("ADAM", "a_v001.ma", "PROJ", "/x")
                with mock.patch.dict(os.environ, {events.HOOKS_ENV: "0"}):
                    events.publish_done("ADAM", "b_v001.ma", "OFF", "/x")
                for _ in range(50):
                    await asyncio.sleep(0.01)
                    mgr = engine.manager()
                    if h.CALLS and not mgr.live:
                        break
            finally:
                events.unlisten("publish_done", sched._listener)

        s.run(scenario())
        self.assertEqual([v for _n, v in h.CALLS], ["PROJ"])


class Routes(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(flows_router.router, prefix="/flows")
        self.client = TestClient(app)

    def test_host_without_scheduler(self) -> None:
        with mock.patch.object(scheduler, "_SCHEDULER", None):
            got = self.client.get("/flows/host").json()
        self.assertEqual((got["running"], got["holder"]), (False, None))

    def test_events_route(self) -> None:
        self.assertEqual(self.client.post("/flows/events/explode", json={}).status_code, 400)
        with mock.patch.object(scheduler, "_SCHEDULER", None):
            r = self.client.post("/flows/events/scene_opened", json={"soft": "maya", "scene": "a.ma"})
        self.assertEqual(r.status_code, 409)
        fake = mock.Mock(scene_watchers=lambda soft: [])
        with mock.patch.object(scheduler, "_SCHEDULER", fake):
            r = self.client.post("/flows/events/scene_opened", json={"soft": "maya", "scene": "a.ma"})
        self.assertEqual(r.json(), {"started": []})


if __name__ == "__main__":
    unittest.main()
