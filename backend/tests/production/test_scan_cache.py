"""scan_cache: single-flight, TTL reuse and invalidation of GET /production."""

import asyncio
import unittest
from unittest import mock

from features.production import scan_cache


class ScanCacheTests(unittest.TestCase):
    def setUp(self):
        scan_cache._reset_for_tests()
        self.calls = 0

    def _compute(self, value="a", delay=0.05):
        async def run():
            self.calls += 1
            await asyncio.sleep(delay)
            return {"v": value, "n": self.calls}
        return run

    def test_concurrent_callers_share_one_computation(self):
        async def main():
            return await asyncio.gather(*[scan_cache.get("P", self._compute()) for _ in range(20)])
        results = asyncio.run(main())
        self.assertEqual(self.calls, 1)
        self.assertEqual(len({r[1] for r in results}), 1)

    def test_result_reused_within_ttl_then_recomputed(self):
        async def main():
            await scan_cache.get("P", self._compute(delay=0))
            await scan_cache.get("p", self._compute(delay=0))      # project key is case-insensitive
            self.assertEqual(self.calls, 1)
            with mock.patch.object(scan_cache.time, "monotonic",
                                   return_value=scan_cache.time.monotonic() + scan_cache.TTL_S + 1):
                await scan_cache.get("P", self._compute(delay=0))
            self.assertEqual(self.calls, 2)
        asyncio.run(main())

    def test_invalidate_forces_fresh_read(self):
        async def main():
            r1, e1 = await scan_cache.get("P", self._compute("a", delay=0))
            scan_cache.invalidate_all()
            r2, e2 = await scan_cache.get("P", self._compute("b", delay=0))
            self.assertEqual(r2["v"], "b")
            self.assertNotEqual(e1, e2)
        asyncio.run(main())

    def test_invalidated_inflight_result_is_not_cached_nor_joined(self):
        async def main():
            first = asyncio.ensure_future(scan_cache.get("P", self._compute("old", delay=0.05)))
            await asyncio.sleep(0.01)
            scan_cache.invalidate_all()                 # a write landed during the scan
            second = await scan_cache.get("P", self._compute("new", delay=0))
            self.assertEqual(second[0]["v"], "new")
            await first
            third = await scan_cache.get("P", self._compute("x", delay=0))
            self.assertEqual(third[0]["v"], "new")      # the stale one never entered the cache
        asyncio.run(main())

    def test_error_is_not_cached(self):
        async def boom():
            self.calls += 1
            raise RuntimeError("no root")

        async def main():
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    await scan_cache.get("P", boom)
        asyncio.run(main())
        self.assertEqual(self.calls, 2)


if __name__ == "__main__":
    unittest.main()
