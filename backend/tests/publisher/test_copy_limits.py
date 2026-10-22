"""copy_limits: parallel cap and throughput cap of the source -> vNNN copy."""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from features.publisher import copy_limits


class CopyLimitsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FLUX_PUBLISH_MAX_PARALLEL", None)
            os.environ.pop("FLUX_PUBLISH_MAX_MBPS", None)
            self.assertEqual(copy_limits.max_parallel(), 10)
            self.assertEqual(copy_limits.max_mbps(), 0.0)

    def test_parallel_cap_is_respected(self):
        peak = 0
        lock = threading.Lock()

        def work():
            nonlocal peak
            with copy_limits.slot():
                with lock:
                    peak = max(peak, copy_limits.status()["active"])
                time.sleep(0.05)

        with mock.patch.dict(os.environ, {"FLUX_PUBLISH_MAX_PARALLEL": "2"}):
            threads = [threading.Thread(target=work) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(peak, 2)
        self.assertEqual(copy_limits.status()["active"], 0)
        self.assertEqual(copy_limits.status()["waiting"], 0)

    def test_throttled_copy_is_identical_and_slowed(self):
        src = self.root / "a.bin"
        src.write_bytes(os.urandom(2 * 1024 * 1024))
        dst = self.root / "b.bin"
        with mock.patch.dict(os.environ, {"FLUX_PUBLISH_MAX_MBPS": "10"}):
            start = time.monotonic()
            copy_limits.copy_file(src, dst)
            elapsed = time.monotonic() - start
        self.assertEqual(src.read_bytes(), dst.read_bytes())
        self.assertGreater(elapsed, 0.15)          # 2 MB at 10 MB/s ~ 0.2 s

    def test_tree_copy(self):
        (self.root / "src" / "sub").mkdir(parents=True)
        (self.root / "src" / "sub" / "f.txt").write_text("x")
        with mock.patch.dict(os.environ, {"FLUX_PUBLISH_MAX_MBPS": "50"}):
            copy_limits.copy_tree(self.root / "src", self.root / "dst")
        self.assertEqual((self.root / "dst" / "sub" / "f.txt").read_text(), "x")


class AdvancedSwitchCheckTests(unittest.TestCase):
    def test_validation(self):
        from features.settings import advanced as adv
        self.assertEqual(adv._check("publish_max_parallel", 3), 3)
        self.assertEqual(adv._check("publish_max_mbps", 0), 0.0)
        for bad in (0, 65, 2.5, True):
            with self.assertRaises(ValueError):
                adv._check("publish_max_parallel", bad)
        with self.assertRaises(ValueError):
            adv._check("publish_max_mbps", -1)
        self.assertEqual(adv._to_env("count", 4), "4")


if __name__ == "__main__":
    unittest.main()
