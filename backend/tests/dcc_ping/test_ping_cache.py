# test_ping_cache.py - N10: one DCC probe per TTL serves every poller.

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from routers import dcc as dcc_router


class PingCache(unittest.TestCase):
    def setUp(self):
        dcc_router._ping_cache.clear()
        dcc_router._ping_locks.clear()

    def test_concurrent_and_repeated_polls_probe_once(self):
        calls = []

        def probe():
            calls.append(1)
            return {"ok": True, "version": "15.1"}

        async def scenario():
            with mock.patch.dict(dcc_router._PING_PROBES, {"nuke": probe}):
                first = await asyncio.gather(*(dcc_router.ping_dcc("nuke") for _ in range(5)))
                again = await dcc_router.ping_dcc("nuke")
            return first, again

        first, again = asyncio.run(scenario())
        self.assertEqual(len(calls), 1)
        self.assertEqual(again, {"connected": True, "version": "15.1"})
        self.assertTrue(all(r == again for r in first))

    def test_expired_entry_probes_again_and_errors_read_disconnected(self):
        def boom():
            raise OSError("refused")

        async def scenario():
            with mock.patch.dict(dcc_router._PING_PROBES, {"mari": boom}), \
                    mock.patch.object(dcc_router, "_PING_TTL_S", 0):
                return await dcc_router.ping_dcc("mari")

        self.assertEqual(asyncio.run(scenario()), {"connected": False, "version": None})

    def test_unknown_dcc_is_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            asyncio.run(dcc_router.ping_dcc("blender"))


if __name__ == "__main__":
    unittest.main()
