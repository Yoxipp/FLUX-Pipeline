# test_no_render_path.py - a Discord bot action never reaches a render or the farm
# (Dave's retake: the bot must not be able to kill a render).

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
NOTIFY = BACKEND / "features" / "notify"

# Anything that can submit, cancel, relaunch or kill a job or a DCC process.
FORBIDDEN = ("features.render", "features.dispatcher", "features.usd_assembler", "features.launcher",
             "flux_flows", "flux_actions", "routers.render", "routers.dcc", "dcc", "core.dcc_process")


def _forbidden(name: str) -> bool:
    return any(name == f or name.startswith(f + ".") for f in FORBIDDEN)


def _imports(path: Path) -> set[str]:
    """Every module imported anywhere in *path*, lazy imports inside functions included."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


class NoRenderPathTests(unittest.TestCase):
    def test_notify_imports_no_render_or_farm_module(self):
        for path in NOTIFY.rglob("*.py"):
            bad = sorted(n for n in _imports(path) if _forbidden(n))
            self.assertEqual(bad, [], path.name)

    def test_only_bot_host_starts_or_ends_processes(self):
        for path in NOTIFY.rglob("*.py"):
            if path.name == "bot_host.py":      # its own headless process, PID checked (test_bot_host)
                continue
            self.assertNotIn("subprocess", _imports(path), path.name)
            text = path.read_text(encoding="utf-8")
            for call in ("os.kill(", "taskkill", ".terminate(", ".kill("):
                self.assertNotIn(call, text, path.name)

    def test_bot_action_modules_load_no_render_module(self):
        # Transitive: everything a button, a slash command or its notifications import.
        mods: set[str] = set()
        for name in ("dm_actions", "discord_bot", "dispatch", "hooks"):
            mods.add(f"features.notify.{name}")
            mods.update(m for m in _imports(NOTIFY / f"{name}.py")
                        if m.startswith(("features.", "utils.", "core.")))
        code = (
            "import importlib, sys\n"
            f"for m in {sorted(mods)!r}:\n"
            "    try:\n"
            "        importlib.import_module(m)\n"
            "    except ModuleNotFoundError as e:\n"
            "        if e.name != m: raise\n"       # "from x import name": name is not a module
            "print(*sys.modules, sep=chr(10))\n"
        )
        out = subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND), capture_output=True,
                             text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        loaded = out.stdout.split()
        self.assertIn("features.production.production_store", loaded)
        self.assertEqual(sorted(n for n in loaded if _forbidden(n)), [])


if __name__ == "__main__":
    unittest.main()
