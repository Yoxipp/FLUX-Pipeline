# P5 (2026-10-23): event.on_publish is emitted by activity_writer.log_publish
# (01 §9 A9). Without an active flow a publish is byte for byte the same; the switch
# FLUX_FLOWS_HOOKS=0 emits nothing; a failing emission never fails the publish.

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from features.activity import activity_writer
from features.publisher import publish_core
from flux_flows import events


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class PublishHooks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_pub_hooks_"))
        self.src = self.tmp / "src" / "chair_model.ma"
        self.src.parent.mkdir()
        self.src.write_text("//Maya ASCII scene\n", encoding="utf-8")
        self._patches = [mock.patch.object(activity_writer, "log_event", return_value=True),
                         mock.patch("features.publisher.usd_publish_hooks.after_usd_publish")]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _publish(self, folder: str) -> dict:
        dest = self.tmp / folder
        out = publish_core.copy_publish(self.src, dest, "chair_model.ma", "test", "ADAM", "PROJ")
        self.assertIsNotNone(out)
        tree = _tree(dest)
        # modif_logs.json holds a date: compare its keys only.
        return {k: (v if not k.endswith(".json") else len(v) > 0) for k, v in tree.items()}

    def test_without_listener_the_publish_is_unchanged(self) -> None:
        self.assertFalse(events.has_listeners("publish_done"))
        with mock.patch.object(events, "signal") as signal:
            plain = self._publish("a")
        signal.assert_not_called()
        self.assertEqual(plain, self._publish("b"))

    def test_listener_gets_the_publish(self) -> None:
        got = []

        async def scenario():
            handle = events.listen("publish_done", got.append)
            try:
                tree = self._publish("c")
                await asyncio.sleep(0.01)
            finally:
                events.unlisten("publish_done", handle)
            return tree

        tree = asyncio.run(scenario())
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["filename"], got[0]["project"], got[0]["user"]), ("chair_model_v001.ma", "PROJ", "ADAM"))
        self.assertEqual(tree, self._publish("d"))

    def test_switch_off_emits_nothing(self) -> None:
        got = []

        async def scenario():
            handle = events.listen("publish_done", got.append)
            try:
                with mock.patch.dict(os.environ, {events.HOOKS_ENV: "0"}):
                    self._publish("e")
                await asyncio.sleep(0.01)
            finally:
                events.unlisten("publish_done", handle)

        asyncio.run(scenario())
        self.assertEqual(got, [])

    def test_an_emission_that_raises_never_fails_the_publish(self) -> None:
        with mock.patch.object(events, "has_listeners", side_effect=RuntimeError("boom")):
            self.assertTrue(activity_writer.log_publish("ADAM", "a_v001.ma", "PROJ", "/x"))
        with mock.patch.object(events, "publish_done", side_effect=RuntimeError("boom")):
            self.assertTrue(activity_writer.log_publish("ADAM", "a_v001.ma", "PROJ", "/x"))
            self._publish("f")


if __name__ == "__main__":
    unittest.main()
