# P7 (2026-10-24): page data on the graph side: PageDataRead, PageDataWrite and the
# event.page_data watcher (baseline, one run per new record, every author) (ADR 0066 n°6).

from __future__ import annotations

import time
import unittest
from unittest import mock

from flux_flows import locations, page_data, page_store, pages
from tests.test_flux_flows import _flow_helpers as h
from tests.test_flux_flows import _sched_helpers as s

setUpModule = h.setUpModule        # noqa: N816
tearDownModule = h.tearDownModule  # noqa: N816


def _page() -> pages.Page:
    return pages.parse_page({"page": 1, "id": "team", "label": "Team", "icon": "users",
                             "data": [{"id": "messages", "fields": [{"id": "text", "type": "text"}]}],
                             "layout": [{"row": [{"id": "chat", "kind": "feed", "source": {"data": "messages"}}]}]})


class PageNodes(unittest.TestCase):
    def setUp(self) -> None:
        h.reset()
        self.env = s.Env()
        self.roots = {"shipped": self.env.tmp / "shipped", "team": self.env.tmp / "ext" / "pages",
                      "project": self.env.tmp / "proj" / "_flux_setup" / "pages"}
        self._patch = mock.patch.object(locations, "page_roots", side_effect=lambda project: dict(self.roots))
        self._patch.start()
        page_store.save_page(self.roots, "team", _page(), user="ADAM")
        self.folder = page_data.locate("team", "messages", "demo")[0]

    def tearDown(self) -> None:
        self._patch.stop()
        self.env.close()

    def _say(self, user: str, text: str) -> str:
        spec = page_data.locate("team", "messages", "demo")[1]
        return page_data.write_ops(self.folder, spec, [{"op": "put", "fields": {"text": text}}], user=user)["rids"][0]

    def test_write_then_read(self) -> None:
        where = {"page": "team", "collection": "messages", "project": "demo"}
        flow = h.flow({"m": "event.manual",
                       "w": ("flux.page_data_write", {**where, "fields": {"text": "Rendu fini"}}),
                       "r": ("flux.page_data_read", where), "rec": "action.t_record"},
                      ["m.then->w.exec", "w.then->r.exec", "r.then->rec.exec", "r.count->rec.value"], name="poster")
        rec = h.run_flow(flow)
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(h.CALLS, [("rec", 1)])
        got = page_data.read_records(self.folder)["records"]
        self.assertEqual((got[0]["text"], got[0]["_by"]), ("Rendu fini", "ADAM"))

    def test_dry_run_writes_nothing(self) -> None:
        flow = h.flow({"m": "event.manual",
                       "w": ("flux.page_data_write", {"page": "team", "collection": "messages", "project": "demo",
                                                     "fields": {"text": "x"}})},
                      ["m.then->w.exec"], name="poster")
        rec = h.run_flow(flow, mode="dry")
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        self.assertEqual(page_data.read_records(self.folder)["records"], [])

    def test_bad_page_is_a_node_error(self) -> None:
        flow = h.flow({"m": "event.manual", "r": ("flux.page_data_read", {"page": "nothing", "collection": "x", "project": "demo"})},
                      ["m.then->r.exec"], name="reader")
        rec = h.run_flow(flow)
        self.assertEqual(rec["status"], "error")
        self.assertIn("introuvable", rec["error"])

    def _watch(self, on: str = "added"):
        flow = s.record_flow("on_message", "event.page_data", {"page": "team", "collection": "messages", "on": on},
                             links=["ev.user->rec.value"])
        af = self.env.active(flow, scope="project", project="demo")
        sched = s.make(self.env, [af])
        return sched, [w for w in sched._wanted() if w.af.name == "on_message"][0]

    def _tick(self, sched, w):
        async def go():
            return await s.settle(*await sched.page_data_tick(w))
        return s.run(go())

    def test_baseline_then_one_run_per_message(self) -> None:
        self._say("ADAM", "deja la")
        sched, w = self._watch()
        self.assertEqual(self._tick(sched, w), [])                 # baseline
        self._say("BOB", "salut")
        self._say("ZOE", "hello")
        done = self._tick(sched, w)
        self.assertEqual([r["status"] for r in done], ["ok", "ok"])
        self.assertEqual(sorted(v for _, v in h.CALLS), ["BOB", "ZOE"])
        self.assertEqual(self._tick(sched, w), [])                 # nothing new

    def test_seen_survives_a_restart(self) -> None:
        sched, w = self._watch()
        self._tick(sched, w)
        self._say("BOB", "pendant la fermeture")
        sched2 = s.make(self.env, [w.af])                          # a new backend: state from seen_<node>.json
        w2 = sched2._wanted()[0]
        self.assertEqual(len(self._tick(sched2, w2)), 1)

    def test_changed(self) -> None:
        rid = self._say("ADAM", "v1")
        sched, w = self._watch("changed")
        self._tick(sched, w)
        self._say("BOB", "nouveau")                               # added: not wanted
        self.assertEqual(self._tick(sched, w), [])
        time.sleep(0.002)
        spec = page_data.locate("team", "messages", "demo")[1]
        page_data.write_ops(self.folder, spec, [{"op": "put", "rid": rid, "fields": {"text": "v2"}}], user="ZOE")
        self.assertEqual([v for _, v in h.CALLS], [])
        self.assertEqual(len(self._tick(sched, w)), 1)
        self.assertEqual([v for _, v in h.CALLS], ["ZOE"])

    def test_shipped_team_flows_run(self) -> None:
        # The Team template flows: today's event gives a reminder, a message gives a line (dry run: nothing posted).
        from datetime import datetime

        from flux_flows import locations as loc
        from flux_flows.model import load_flow_text

        today = datetime.now().strftime("%Y-%m-%dT09:30")
        page_store.save_page(self.roots, "team", pages.parse_page({
            **pages.to_document(_page()), "data": [{"id": "messages", "fields": [{"id": "text", "type": "text"}, {"id": "channel", "type": "str"}]},
                                                     {"id": "events", "fields": [{"id": "title", "type": "str"}, {"id": "when", "type": "datetime"}]}]}),
            user="ADAM", base_rev=page_store.read_page(self.roots, "team", "team")["rev"])
        events_dir, events_spec, _ = page_data.locate("team", "events", "demo")
        page_data.write_ops(events_dir, events_spec, [{"op": "put", "fields": {"title": "Review lighting", "when": today}},
                                                      {"op": "put", "fields": {"title": "Plus tard", "when": "2099-01-01T10:00"}}], user="ADAM")
        text = (loc.shipped_dir() / "team_reminders.flow.yml").read_text(encoding="utf-8")
        flow = load_flow_text(text)
        flow.nodes["read"].params["project"] = "demo"
        rec = h.run_flow(flow, mode="dry")
        self.assertEqual(rec["status"], "ok", rec.get("error"))
        lines = " ".join(str(r.get("text_fr")) for r in rec["report"])
        self.assertIn("Rappel : Review lighting", lines)
        self.assertNotIn("Plus tard", lines)

    def test_shipped_templates_load(self) -> None:
        from flux_flows import locations as loc

        roots = {"shipped": loc.shipped_dir() / "pages", "team": None, "project": None}
        ids = sorted(t["id"] for t in page_store.list_templates(roots))
        self.assertEqual(ids, ["annonces", "board", "controle_usd", "daily_render", "livraison_plan", "team"])   # + T1 examples (ADR 0069)
        for tid in ids:
            got = page_store.read_page(roots, "shipped", tid)
            self.assertEqual([i.code for i in pages.validate_page(got["page"]) if i.level == "error"], [], tid)

    def test_global_event_only_on_the_holder(self) -> None:
        flow = s.record_flow("on_message", "event.page_data", {"page": "team", "collection": "messages"})
        af = self.env.active(flow, scope="project", project="demo")
        self.assertEqual(s.make(self.env, [af], holder=False)._wanted(), [])


if __name__ == "__main__":
    unittest.main()
