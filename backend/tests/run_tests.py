# run_tests.py — robust test entry point for the usd_assembler suite.
#
# Why this exists: usd-core on Windows/CPython 3.13 intermittently aborts with
# STATUS_BREAKPOINT (exit code 3) from a USD worker thread during teardown. The
# tests themselves pass — only the process exit code and buffered output are
# poisoned, which would make a plain ``python -m unittest`` look red at random.
#
# Strategy: a child process runs the suite and, the moment the run finishes
# (stopTestRun, before the crashing teardown), writes the real verdict to a
# sentinel JSON file. The parent judges on that sentinel, not on the child's
# exit code, and retries only when a flaky abort strikes *before* the verdict is
# written. Deterministic pass/fail; the USD teardown crash can no longer lie.
#
# Usage (from backend/):  python tests/run_tests.py

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
_SENTINEL_ENV = "USD_ASM_TEST_SENTINEL"
_MAX_ATTEMPTS = 4


class _SentinelResult(unittest.TextTestResult):
    """Persist the verdict at run end, before USD's flaky teardown can abort."""

    def stopTestRun(self) -> None:  # noqa: N802 (unittest API)
        super().stopTestRun()
        path = os.environ.get(_SENTINEL_ENV)
        if not path:
            return
        payload = {
            "success": self.wasSuccessful(),
            "run": self.testsRun,
            "failures": len(self.failures),
            "errors": len(self.errors),
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
            fh.flush()
            os.fsync(fh.fileno())


def _run_child() -> None:
    """In-child: run the suite, write the sentinel, hard-exit before teardown."""
    sys.path.insert(0, _BACKEND)
    suite = unittest.TestLoader().discover(start_dir=_HERE, pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2, resultclass=_SentinelResult)
    result = runner.run(suite)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.wasSuccessful() else 1)


def _run_parent() -> int:
    """Spawn the child, judging on the sentinel to survive flaky USD aborts."""
    fd, sentinel = tempfile.mkstemp(prefix="usd_asm_test_", suffix=".json")
    os.close(fd)
    os.unlink(sentinel)
    env = {
        **os.environ,
        _SENTINEL_ENV: sentinel,
        "_USD_ASM_TEST_CHILD": "1",
        # Pin stages alive for the run so a mid-run stage free can't abort a USD
        # worker thread before the verdict is written (see stage_factory).
        "USD_ASM_KEEPALIVE_STAGES": "1",
    }

    try:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            proc = subprocess.run([sys.executable, "-u", __file__], env=env)
            if os.path.exists(sentinel):
                verdict = json.loads(open(sentinel, encoding="utf-8").read())
                ok = verdict["success"]
                print(
                    f"\n[run_tests] verdict: {'PASS' if ok else 'FAIL'} "
                    f"(ran={verdict['run']} failures={verdict['failures']} "
                    f"errors={verdict['errors']}; child_exit={proc.returncode})"
                )
                return 0 if ok else 1
            print(
                f"[run_tests] flaky USD abort before verdict "
                f"(exit={proc.returncode}); retry {attempt}/{_MAX_ATTEMPTS}"
            )
        print("[run_tests] gave up: no verdict after retries")
        return 2
    finally:
        if os.path.exists(sentinel):
            os.unlink(sentinel)


if __name__ == "__main__":
    if os.environ.get("_USD_ASM_TEST_CHILD") == "1":
        _run_child()
    else:
        raise SystemExit(_run_parent())
