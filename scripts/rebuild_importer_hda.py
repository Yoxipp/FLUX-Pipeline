"""
Rebuild + reinstall the FLUX Houdini importer/exporter HDAs into the running
Houdini, applying any fix in the HDA builders (e.g. the format_switch expression).

Run from the repo root WITH Houdini open and connected to the FLUX backend:

    python scripts/rebuild_importer_hda.py

It live-builds the HDAs from source into every houdiniX.Y/otls/ dir, refreshes
the offline staging copy, and reloads the definition in the running session.
After it finishes, create a fresh FLUX import node (the old cached definition is
replaced) and import again.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from dcc.houdini.client import houdini_client            # noqa: E402
from features.shelf_manager import shelf_core            # noqa: E402


def _detect_version() -> str | None:
    """Houdini X.Y from the connected session, else from ~/houdiniX.Y dirs."""
    state = houdini_client.state()
    ver = state.get("version") if isinstance(state, dict) else None
    if ver:
        m = re.search(r"(\d+\.\d+)", str(ver))
        if m:
            return m.group(1)
    for d in sorted(Path.home().glob("houdini*.*"), reverse=True):
        m = re.search(r"houdini(\d+\.\d+)", d.name)
        if m:
            return m.group(1)
    return None


def main() -> None:
    if not houdini_client.is_connected():
        print("✗ Houdini is not reachable (FLUX server not listening).")
        print("  Open Houdini and make sure the FLUX autostart server started, then retry.")
        sys.exit(1)

    version = _detect_version()
    if not version:
        print("✗ Could not detect the Houdini version.")
        sys.exit(1)

    print(f"→ Rebuilding FLUX HDAs live for Houdini {version} …")
    ok, msg = shelf_core.install_hdas(version)
    print(("  ✓ " if ok else "  ✗ ") + msg)
    if not ok:
        sys.exit(1)
    print("Done. Create a NEW FLUX import node and import again.")


if __name__ == "__main__":
    main()
