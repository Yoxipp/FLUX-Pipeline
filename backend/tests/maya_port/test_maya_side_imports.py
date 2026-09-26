# Maya's Python has no yaml, no FastAPI and no FLUX action engine (0d5e4708: "No module
# named yaml" at a Maya USD export). Every module FLUX runs inside Maya must import
# without them, including the imports made inside its functions.

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]

_MAYA_SIDE = (
    "dcc.maya.maya_import", "dcc.maya.maya_update", "dcc.maya.maya_export",
    "dcc.maya.maya_usd_light_export", "dcc.maya.maya_usd_look_export", "dcc.maya.maya_layout",
    "dcc.maya.maya_usd_presets", "dcc.maya.maya_usd_preview", "dcc.maya.maya_keys",
    "dcc.maya.maya_connection", "features.usd_export", "features.usd_export.contract",
    "features.usd_assembler.structure.naming", "core.constants",
)

_PROBE = f'''
import importlib, sys
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("yaml", "flux_core", "flux_actions", "fastapi", "uvicorn", "pydantic"):
            raise ImportError("not in Maya: " + name)
        return None
sys.meta_path.insert(0, _Block())
bad = []
for mod in {_MAYA_SIDE!r}:
    try:
        importlib.import_module(mod)
    except Exception as exc:
        bad.append(mod + ": " + repr(exc))
print("BAD=" + repr(bad))
'''


class MayaSideImports(unittest.TestCase):
    def test_maya_side_modules_import_without_yaml_or_the_engine(self) -> None:
        out = subprocess.run([sys.executable, "-c", _PROBE], cwd=_BACKEND, capture_output=True,
                             text=True, timeout=120)
        line = next((ln for ln in out.stdout.splitlines() if ln.startswith("BAD=")), None)
        self.assertIsNotNone(line, out.stderr[-2000:])
        self.assertEqual(line, "BAD=[]")


if __name__ == "__main__":
    unittest.main()
