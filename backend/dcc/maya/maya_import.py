# maya_import.py — import / reference files into the current Maya scene.
# Runs inside Maya (Python 3.10). Also exposes open_importer() for shelf button.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

try:
    import maya.cmds as cmds  # type: ignore[import]
    _IN_MAYA = True
except ImportError:
    cmds = None
    _IN_MAYA = False

_FILE_TYPES: dict[str, str] = {
    ".mb":  "mayaBinary",
    ".ma":  "mayaAscii",
    ".fbx": "FBX",
    ".obj": "OBJ",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _ensure_plugin(plugin: str) -> bool:
    try:
        if not cmds.pluginInfo(plugin, q=True, loaded=True):  # type: ignore[union-attr]
            cmds.loadPlugin(plugin, quiet=True)  # type: ignore[union-attr]
        return True
    except Exception as exc:
        log.error("Cannot load plugin %s: %s", plugin, exc)
        return False


# ── public API ────────────────────────────────────────────────────────────────

def import_file(file_path: str | Path) -> list[str] | None:
    """Import *file_path* into the current Maya scene.

    Supported extensions: .mb .ma .abc .fbx .obj
    Returns the list of created node names on success, None on failure.
    """
    if not _IN_MAYA:
        log.error("import_file: not running inside Maya")
        return None

    src = Path(file_path)
    ext = src.suffix.lower()

    try:
        if ext == ".abc":
            if not _ensure_plugin("AbcImport"):
                return None
            result = cmds.AbcImport(str(src).replace("\\", "/"), mode="import")  # type: ignore[union-attr]
            nodes = [result] if isinstance(result, str) else (result or [])
            log.info("Imported (ABC) %s → %d nodes", src.name, len(nodes))
            return nodes

        if ext == ".fbx":
            _ensure_plugin("fbxmaya")

        file_type = _FILE_TYPES.get(ext, "mayaBinary")
        nodes = cmds.file(  # type: ignore[union-attr]
            str(src),
            i=True,
            type=file_type,
            ignoreVersion=True,
            returnNewNodes=True,
        )
        nodes = nodes or []
        log.info("Imported %s → %d nodes", src.name, len(nodes))
        return nodes
    except Exception as exc:
        log.error("import_file failed for %s: %s", src.name, exc)
        return None


def reference_file(file_path: str | Path) -> str | None:
    """Create a Maya reference from *file_path*.

    Supported extensions: .mb .ma .abc .fbx .obj
    Returns the reference node name on success, None on failure.
    """
    if not _IN_MAYA:
        log.error("reference_file: not running inside Maya")
        return None

    src = Path(file_path)
    ext = src.suffix.lower()

    try:
        if ext == ".fbx":
            _ensure_plugin("fbxmaya")

        nodes = cmds.file(  # type: ignore[union-attr]
            str(src),
            reference=True,
            ignoreVersion=True,
            returnNewNodes=True,
        )
        ref_node = nodes[0] if nodes else None
        log.info("Referenced %s → %s", src.name, ref_node)
        return ref_node
    except Exception as exc:
        log.error("reference_file failed for %s: %s", src.name, exc)
        return None


def open_importer() -> None:
    """Launch the Flux Hub to use its importer. Called from Maya shelf button."""
    from dcc.maya.maya_connection import open_hub
    open_hub()

