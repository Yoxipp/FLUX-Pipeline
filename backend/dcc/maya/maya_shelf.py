# maya_shelf.py — programmatic Flux shelf creation inside Maya.
# Not called at startup any more (the old flux_bridge.py was archived to old/, 2026-09-18).

from __future__ import annotations

from core.constants import DCC_PORTS
from core.logger import get_logger

log = get_logger(__name__)

try:
    import maya.cmds as cmds  # type: ignore[import]
    import maya.mel as mel    # type: ignore[import]
    _IN_MAYA = True
except ImportError:
    cmds = None
    mel = None
    _IN_MAYA = False

_SHELF_NAME = "Flux"
_MAYA_PORT  = DCC_PORTS["Maya"]

# Build Connect command without nested quotes
_CONNECT_CMD = (
    "import maya.cmds as mc; "
    f"mc.commandPort(name='127.0.0.1:{_MAYA_PORT}', sourceType='python')"
)

_BUTTONS: list[dict[str, str]] = [
    {
        "label":      "Publish",
        "annotation": "Flux · Publish scene to pipeline",
        "command":    "from dcc.maya import maya_publish; maya_publish.publish()",
    },
    {
        "label":      "Import",
        "annotation": "Flux · Import asset from pipeline",
        "command":    "from dcc.maya import maya_import; maya_import.open_importer()",
    },
    {
        "label":      "Connect",
        "annotation": f"Flux · Open commandPort (port {_MAYA_PORT})",
        "command":    _CONNECT_CMD,
    },
    {
        "label":      "Hub",
        "annotation": "Flux · Open Flux Hub",
        "command":    "from dcc.maya import maya_connection; maya_connection.open_hub()",
    },
]


def _get_shelf_top_level() -> str:
    return mel.eval("$_ = $gShelfTopLevel")  # type: ignore[union-attr]


def _shelf_exists() -> bool:
    return bool(cmds.shelfLayout(_SHELF_NAME, exists=True))  # type: ignore[union-attr]


def create_flux_shelf() -> bool:
    """Create the Flux shelf tab with all buttons.

    No-op and returns True if the shelf already exists.
    Returns False on failure or when not inside Maya.
    """
    if not _IN_MAYA:
        log.error("create_flux_shelf: not running inside Maya")
        return False
    if _shelf_exists():
        log.debug("Flux shelf already present — skipping creation")
        return True
    try:
        shelf_top = _get_shelf_top_level()
        cmds.shelfLayout(_SHELF_NAME, parent=shelf_top)  # type: ignore[union-attr]
        for btn in _BUTTONS:
            cmds.shelfButton(  # type: ignore[union-attr]
                label=btn["label"],
                annotation=btn["annotation"],
                image1="commandButton.png",
                sourceType="python",
                command=btn["command"],
                parent=_SHELF_NAME,
            )
        log.info("Flux shelf created (%d buttons)", len(_BUTTONS))
        return True
    except Exception as exc:
        log.error("create_flux_shelf failed: %s", exc)
        return False


def remove_flux_shelf() -> bool:
    """Delete the Flux shelf tab from Maya. Returns True on success."""
    if not _IN_MAYA:
        log.error("remove_flux_shelf: not running inside Maya")
        return False
    if not _shelf_exists():
        return True
    try:
        cmds.deleteUI(_SHELF_NAME, layout=True)  # type: ignore[union-attr]
        log.info("Flux shelf removed")
        return True
    except Exception as exc:
        log.error("remove_flux_shelf failed: %s", exc)
        return False

