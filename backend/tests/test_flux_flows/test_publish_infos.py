# R1 retakes 3 and 10: the infos output of PublishRequest and OnPublish and the
# data.publish_infos node that splits it. Bodies called directly with a fake ctx.

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from flux_flows.nodes import registry
from flux_flows.nodes.contract import NodeError
from flux_flows.nodes.flux import PUBLISH_INFO_KEYS, publish_infos


def _call(node_type, ctx, inputs=None, params=None):
    out = registry.get_node(node_type).func(ctx, dict(inputs or {}), dict(params or {}))
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def _ctx(interface=None, payload=None):
    return SimpleNamespace(interface=dict(interface or {}), payload=dict(payload or {}),
                           context={"project": "DEMO", "user": "ADAM"})


class PublishInfosTest(unittest.TestCase):
    def test_asset_and_shot_names(self):
        a = publish_infos("CHAR_RIG_HERO_body_v003.ma", project="DEMO")
        self.assertEqual((a["mode"], a["task"], a["class"], a["asset"], a["instance"], a["version"], a["soft"]),
                         ("asset", "RIG", "CHAR", "HERO", "body", 3, "maya"))
        s = publish_infos("SEQ010_SHOT020_ANIM_main_LAST.abc")
        self.assertEqual((s["mode"], s["task"], s["seq"], s["shot"], s["asset"], s["version"]),
                         ("shot", "ANIM", "SEQ010", "SHOT020", "", None))
        self.assertEqual(publish_infos("notes.png")["mode"], "")
        self.assertEqual(set(a), set(PUBLISH_INFO_KEYS))

    def test_publish_request_keeps_values_and_adds_infos(self):
        ctx = _ctx({"name": "CHAR_RIG_HERO_null", "format": ".ma", "scope": "scene"}, {"soft": "maya"})
        out = _call("event.publish_request", ctx, params={"soft": "maya"})
        self.assertEqual(out["values"]["scope"], "scene")          # the P6a outputs are unchanged
        self.assertEqual((out["name"], out["soft"]), ("CHAR_RIG_HERO_null", "maya"))
        infos = out["infos"]
        self.assertEqual((infos["mode"], infos["task"], infos["asset"], infos["soft"], infos["project"], infos["user"]),
                         ("asset", "RIG", "HERO", "maya", "DEMO", "ADAM"))
        self.assertIsNone(infos["version"])

    def test_on_publish_gives_infos(self):
        rec = {"file": "SEQ010_SHOT020_ANIM_main_v004.abc", "path": "/p/SEQ010_SHOT020_ANIM_main_v004.abc",
               "user": "ADAM", "version": 4}
        out = _call("event.on_publish", _ctx(payload={"publish": rec, "project": "DEMO"}))
        self.assertEqual((out["infos"]["mode"], out["infos"]["shot"], out["infos"]["version"]), ("shot", "SHOT020", 4))
        dry = _call("event.on_publish", _ctx())                     # editor Run: an example publish
        self.assertEqual(dry["infos"]["mode"], "asset")
        self.assertEqual((dry["publish"]["user"], dry["infos"]["user"]), ("ADAM", "ADAM"))   # T1: {user} resolves

    def test_run_by_hand_says_when_the_filters_refuse_the_example(self):
        logs = []
        ctx = _ctx()
        ctx.log = lambda text, level="info": logs.append((level, text))
        _call("event.on_publish", ctx, params={"task": "ANIM"})     # the example is a RIG publish
        self.assertEqual([lv for lv, _ in logs], ["warn"])
        logs.clear()
        _call("event.on_publish", ctx, params={"task": "RIG"})
        self.assertEqual(logs, [])

    def test_soft_sent_by_the_publisher_wins_over_the_extension(self):
        from flux_flows import hooks

        signal = {"user": "ADAM", "filename": "CHAR_GEO_HERO_null_v002.abc", "project": "DEMO", "dest_folder": ""}
        self.assertEqual(hooks.publish_payload(signal)["publish"]["soft"], "")       # .abc: no soft from the extension
        sent = hooks.publish_payload({**signal, "soft": "maya"})
        self.assertEqual((sent["publish"]["soft"], sent["infos"]["soft"]), ("maya", "maya"))
        self.assertTrue(hooks.wants({"soft": "maya"}, sent["publish"], sent["infos"]))

    def test_node_splits_infos_record_and_path(self):
        infos = publish_infos("CHAR_RIG_HERO_null_v003.ma", project="DEMO")
        out = _call("data.publish_infos", _ctx(), {"infos": infos})
        self.assertEqual((out["mode"], out["task"], out["asset"], out["project"], out["version"]),
                         ("asset", "RIG", "HERO", "DEMO", 3))
        rec = {"path": "/p/SEQ010_SHOT020_ANIM_main_v002.abc", "file": "SEQ010_SHOT020_ANIM_main_v002.abc",
               "user": "ADAM", "version": 2}
        self.assertEqual(_call("data.publish_infos", _ctx(), {"infos": rec})["seq"], "SEQ010")
        self.assertEqual(_call("data.publish_infos", _ctx(), {"infos": "CHAR_MOD_TREE_null_LAST.usd"})["asset"], "TREE")
        with self.assertRaises(NodeError):
            _call("data.publish_infos", _ctx(), {"infos": None})


if __name__ == "__main__":
    unittest.main()
