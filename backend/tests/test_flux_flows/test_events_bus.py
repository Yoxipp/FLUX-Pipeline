# P2 (2026-10-22): internal bus of the Flows (01 §10): filters, thread-safe emit, bounded queue.

from __future__ import annotations

import asyncio
import threading
import unittest

from flux_flows import events


class Bus(unittest.TestCase):
    def test_no_subscriber_is_a_no_op(self) -> None:
        events.emit({"type": "log", "text": "x"})   # must not raise

    def test_emit_from_a_thread_reaches_the_loop(self) -> None:
        async def scenario():
            sub = events.subscribe()
            try:
                t = threading.Thread(target=events.emit, args=({"type": "run_started", "run_id": "r1"},))
                t.start()
                t.join()
                return await asyncio.wait_for(sub.get(), 2)
            finally:
                events.unsubscribe(sub)

        self.assertEqual(asyncio.run(scenario())["run_id"], "r1")

    def test_filter_by_run(self) -> None:
        async def scenario():
            sub = events.subscribe()
            sub.set_filter(run_id="r2")
            try:
                events.emit({"type": "log", "run_id": "r1"})
                events.emit({"type": "log", "run_id": "r2"})
                events.emit({"type": "hello"})   # no run_id: always passes
                return [m.get("run_id") for m in sub.pending()]
            finally:
                events.unsubscribe(sub)

        self.assertEqual(asyncio.run(scenario()), ["r2", None])

    def test_full_queue_drops_logs_first_never_run_finished(self) -> None:
        async def scenario():
            sub = events.subscribe(max_queue=3)
            try:
                events.emit({"type": "node_state", "n": 1})
                events.emit({"type": "log", "n": 2})
                events.emit({"type": "run_finished", "n": 3})
                events.emit({"type": "node_state", "n": 4})   # drops the log
                events.emit({"type": "node_state", "n": 5})   # drops the oldest node_state
                events.emit({"type": "node_state", "n": 6})
                return [m["n"] for m in sub.pending()], sub.dropped
            finally:
                events.unsubscribe(sub)

        kept, dropped = asyncio.run(scenario())
        self.assertIn(3, kept)
        self.assertEqual((len(kept), dropped), (3, 3))
        self.assertNotIn(2, kept)


if __name__ == "__main__":
    unittest.main()
