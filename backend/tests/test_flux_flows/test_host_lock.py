# P5 (2026-10-23): host lock between workstations (01 §9). Two backends are simulated
# with two HostLock objects on the same file, fake clocks and no real sleep.

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from flux_flows import hosts


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


async def _nosleep(_s: float) -> None:
    return None


class HostLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flux_host_lock_"))
        self.path = self.tmp / "runs" / "host.lock"
        self.wall = Clock()
        self.mono_a, self.mono_b = Clock(0.0), Clock(0.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lock(self, host: str, mono: Clock, wall: Clock = None) -> hosts.HostLock:
        return hosts.HostLock(self.path, user="ADAM", host=host, clock=wall or self.wall, mono=mono,
                              sleep=_nosleep, settle=(0, 0), confirm_s=0)

    def tick(self, lock: hosts.HostLock) -> bool:
        return asyncio.run(lock.tick())

    def test_first_backend_takes_the_free_lock(self) -> None:
        a = self._lock("PC-A", self.mono_a)
        self.assertTrue(self.tick(a))
        self.assertTrue(a.holder)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((data["host"], data["nonce"], data["beat"]), ("PC-A", a.nonce, 0))
        self.assertFalse(self.tick(a))       # renewal, still holder
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["beat"], 1)

    def test_second_backend_follows_while_the_lock_is_valid(self) -> None:
        a, b = self._lock("PC-A", self.mono_a), self._lock("PC-B", self.mono_b)
        self.tick(a)
        self.tick(b)
        self.assertFalse(b.holder)
        self.assertEqual(b.info()["holder"]["host"], "PC-A")

    def test_takeover_needs_expiry_and_a_still_beat(self) -> None:
        a, b = self._lock("PC-A", self.mono_a), self._lock("PC-B", self.mono_b)
        self.tick(a)
        self.tick(b)                          # B sees beat 0
        self.wall.t += 100                    # A's lock expired on the wall clock...
        self.mono_b.t += 30
        self.tick(b)
        self.assertFalse(b.holder)            # ...but B has not seen the beat still for 60 s
        self.mono_b.t += 31
        self.tick(b)
        self.assertTrue(b.holder)
        self.tick(a)                          # A reads another nonce: lost
        self.assertFalse(a.holder)

    def test_clock_skew_alone_never_steals_a_beating_lock(self) -> None:
        # B's wall clock is 10 minutes ahead: A's lock looks expired, but A keeps beating.
        a = self._lock("PC-A", self.mono_a)
        b = self._lock("PC-B", self.mono_b, wall=Clock(self.wall.t + 600))
        self.tick(a)
        for _ in range(10):
            self.tick(b)
            self.mono_b.t += 20
            self.tick(a)
        self.assertTrue(a.holder)
        self.assertFalse(b.holder)

    def test_clean_release_is_taken_at_once(self) -> None:
        a, b = self._lock("PC-A", self.mono_a), self._lock("PC-B", self.mono_b)
        self.tick(a)
        a.release()
        self.assertFalse(a.holder)
        self.tick(b)
        self.assertTrue(b.holder)

    def test_corrupt_or_empty_file_is_free(self) -> None:
        self.path.parent.mkdir(parents=True)
        for text in ("", "{not json", "[]", "{}"):
            self.path.write_text(text, encoding="utf-8")
            b = self._lock("PC-B", self.mono_b)
            self.tick(b)
            self.assertTrue(b.holder, text)

    def test_read_back_with_another_nonce_loses_the_race(self) -> None:
        a = self._lock("PC-A", self.mono_a)
        other = {"host": "PC-C", "nonce": "c" * 32, "expires": self.wall.t + 60, "beat": 0}

        async def thief(_s: float) -> None:      # PC-C writes during A's settle wait
            self.path.write_text(json.dumps(other), encoding="utf-8")

        a.sleep = thief
        asyncio.run(a.tick())
        self.assertFalse(a.holder)

    def test_unreachable_root_twice_loses_the_lock(self) -> None:
        a = self._lock("PC-A", self.mono_a)
        self.tick(a)
        broken = hosts.HostLock(self.tmp / "file" / "runs" / "host.lock", nonce=a.nonce, sleep=_nosleep)
        (self.tmp / "file").write_text("not a folder", encoding="utf-8")
        broken.holder = True
        self.assertFalse(self.tick(broken))   # one failure: still holder
        self.assertTrue(broken.holder)
        self.assertTrue(self.tick(broken))    # two: lost
        self.assertFalse(broken.holder)


if __name__ == "__main__":
    unittest.main()
