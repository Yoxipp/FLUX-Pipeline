# External Tractor bridge script: JSON protocol without Tractor (the API calls are verified at school).
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "features" / "render" / "bridge" / "flux_tractor_bridge.py"


def _run(stdin: str) -> dict:
    proc = subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True, text=True, timeout=30)
    return json.loads(proc.stdout)


class BridgeScriptTests(unittest.TestCase):
    def test_ping(self):
        out = _run(json.dumps({"verb": "ping"}))
        self.assertTrue(out["ok"])
        self.assertIn("version", out["result"])

    def test_unknown_verb(self):
        self.assertFalse(_run(json.dumps({"verb": "nope"}))["ok"])

    def test_garbage_request(self):
        out = _run("not json")
        self.assertFalse(out["ok"])
        self.assertIn("illisible", out["error"])

    def test_tractor_missing_is_reported(self):
        out = _run(json.dumps({"verb": "jobs", "user": "adam"}))
        self.assertFalse(out["ok"])  # no tractor module in the backend Python

    def test_python2_compatible_syntax(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"\bf\"|\bf'")
        self.assertNotRegex(text, r"\)\s*->")  # return annotations


if __name__ == "__main__":
    unittest.main()
