# flux_nuke_menu.py — the FLUX menu shown INSIDE Nuke (V6 B1).
#
# Runs inside Nuke (GUI). Gives Nuke a visible FLUX entry point (like the Maya shelf
# / the ZBrush button / the Houdini HDA): a "FLUX" menu with Publish / Import that
# act on the selected node and talk to the running FLUX backend over HTTP
# (127.0.0.1:8765). Standalone on purpose: it imports only `nuke` + stdlib, NEVER
# the FLUX backend packages (those are not importable inside Nuke's Python).
#
# The pure helpers (compose_asset_filename, backend_url) are unit-testable from the
# backend; the menu wiring needs a live Nuke and is not unit-tested.

from __future__ import annotations

import json
import urllib.request

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8765

# Formats FLUX can publish from Nuke (Write formats + the comp script).
NUKE_FORMATS = [".exr", ".dpx", ".tif", ".png", ".mov", ".nk"]
CLASS_TOKENS = ["CHAR", "PROP", "SET", "FX", "SHOT"]


def backend_url(path: str) -> str:
    """Return the full FLUX backend URL for an API *path* (pure, testable)."""
    p = path if path.startswith("/") else f"/{path}"
    return f"http://{BACKEND_HOST}:{BACKEND_PORT}{p}"


def compose_asset_filename(class_tok: str, type_tok: str, name_tok: str, instance: str) -> str:
    """Compose the FLUX asset name CLASS_TYPE_NAME_INSTANCE (uppercased), pure."""
    inst = (instance or "null").strip() or "null"
    return "_".join([class_tok, type_tok, name_tok, inst]).upper()


def _post(path: str, payload: dict, timeout: float = 120.0) -> dict:
    """POST JSON to the FLUX backend and return the parsed response (or an error)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        backend_url(path), data=data, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - localhost only
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - surfaced to the artist in a Nuke dialog
        return {"ok": False, "error": str(exc)}


# ── menu commands (need Nuke GUI) ─────────────────────────────────────────────

def _selected_node_name():
    import nuke
    sel = nuke.selectedNodes()
    return sel[0].name() if sel else None


def publish_selection() -> None:
    """Ask for the FLUX tokens + format, then publish the selected node via FLUX."""
    import nuke

    node = _selected_node_name()
    if node is None:
        nuke.message("FLUX : sélectionne d'abord un node à publier.")
        return

    p = nuke.Panel("FLUX — Publier la sélection")
    p.addSingleLineInput("Projet", "")
    p.addEnumerationPulldown("Class", " ".join(CLASS_TOKENS))
    p.addSingleLineInput("Type", "REN")
    p.addSingleLineInput("Name", "")
    p.addSingleLineInput("Instance", "null")
    p.addEnumerationPulldown("Format", " ".join(NUKE_FORMATS))
    p.addSingleLineInput("Description", "")
    if not p.show():
        return

    project = p.value("Projet").strip()
    name = p.value("Name").strip()
    if not project or not name:
        nuke.message("FLUX : Projet et Name sont obligatoires.")
        return

    filename = compose_asset_filename(
        p.value("Class").strip(), p.value("Type").strip(), name, p.value("Instance").strip(),
    )
    result = _post("/dcc/nuke/publish", {
        "project_name": project,
        "filename": filename,
        "extension": p.value("Format").strip(),
        "node_name": node,
        "description": p.value("Description").strip(),
    })
    if result.get("ok"):
        nuke.message(f"FLUX : publié\n{result.get('path', '')}")
    else:
        nuke.message(f"FLUX : échec\n{result.get('error') or result.get('detail') or 'voir logs'}")


def import_from_flux() -> None:
    """Ask for the FLUX tokens, then create a Read node for the resolved publish."""
    import nuke

    p = nuke.Panel("FLUX — Importer")
    p.addSingleLineInput("Projet", "")
    p.addEnumerationPulldown("Class", " ".join(CLASS_TOKENS))
    p.addSingleLineInput("Type", "REN")
    p.addSingleLineInput("Name", "")
    p.addSingleLineInput("Instance", "null")
    p.addSingleLineInput("Iter (LAST/v001)", "LAST")
    if not p.show():
        return

    project = p.value("Projet").strip()
    name = p.value("Name").strip()
    if not project or not name:
        nuke.message("FLUX : Projet et Name sont obligatoires.")
        return

    result = _post("/dcc/nuke/import", {
        "project_name": project,
        "class_token": p.value("Class").strip(),
        "type_token": p.value("Type").strip(),
        "name_token": name,
        "instance": p.value("Instance").strip() or "null",
        "iter": p.value("Iter (LAST/v001)").strip() or "LAST",
    })
    if result.get("ok"):
        nuke.message(f"FLUX : Read créé ({result.get('node', '')})")
    else:
        nuke.message(f"FLUX : échec\n{result.get('error') or result.get('detail') or 'voir logs'}")


def register() -> bool:
    """Register the FLUX menu in Nuke's menu bar. GUI only; safe to call twice."""
    try:
        import nuke
    except Exception:
        return False
    if not getattr(nuke, "GUI", False):
        return False
    try:
        menubar = nuke.menu("Nuke")
        m = menubar.addMenu("FLUX")
        m.addCommand("Publier la sélection", publish_selection)
        m.addCommand("Importer depuis FLUX", import_from_flux)
        return True
    except Exception as exc:  # never break Nuke startup on a menu hiccup
        print(f"[FLUX] Nuke menu registration failed: {exc}")
        return False
