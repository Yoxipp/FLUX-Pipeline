"""
Dev utility — build FLUX Houdini HDAs and save them to backend/resources/shelves/houdini/.

Requires a running Houdini instance connected to the FLUX backend (commandPort active).
Run from the repo root:

    python scripts/build_hdas.py

The resulting .hda files are bundled by PyInstaller via the ("resources", "resources")
rule in scripts/backend.spec.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make backend importable from repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from dcc.houdini.hda.flux_importer_hda import build_hda as build_importer
from dcc.houdini.hda.flux_exporter_hda import build_hda as build_exporter

_OUT_DIR = Path(__file__).parent.parent / "backend" / "resources" / "shelves" / "houdini"


def main() -> None:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    importer_path = str(_OUT_DIR / "flux_importer.hda")
    print(f"Building importer HDA → {importer_path}")
    r = build_importer(importer_path)
    if r.get("ok"):
        print("  ✓ flux_importer.hda built")
    else:
        print(f"  ✗ importer build failed: {r.get('error')}")
        sys.exit(1)

    exporter_path = str(_OUT_DIR / "flux_exporter.hda")
    print(f"Building exporter HDA → {exporter_path}")
    r = build_exporter(exporter_path)
    if r.get("ok"):
        print("  ✓ flux_exporter.hda built")
    else:
        print(f"  ✗ exporter build failed: {r.get('error')}")
        sys.exit(1)

    print("Done — HDAs written to backend/resources/shelves/houdini/")


if __name__ == "__main__":
    main()
