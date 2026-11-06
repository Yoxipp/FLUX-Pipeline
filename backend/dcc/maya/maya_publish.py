# maya_publish.py — full publish workflow triggered from Maya shelf.
# Runs inside Maya (Python 3.10): export scene → publish_core.publish_file().

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

try:
    import maya.cmds as cmds  # type: ignore[import]
    _IN_MAYA = True
except ImportError:
    cmds = None
    _IN_MAYA = False


# ── helpers ───────────────────────────────────────────────────────────────────

def _show_error(message: str) -> None:
    """Show an error dialog inside Maya (or just log it when outside Maya)."""
    log.error(message)
    if _IN_MAYA:
        cmds.confirmDialog(title="Flux · Publish Error", message=message, button=["OK"])  # type: ignore[union-attr]


def _show_info(message: str) -> None:
    if _IN_MAYA:
        cmds.confirmDialog(title="Flux · Published", message=message, button=["OK"])  # type: ignore[union-attr]


# ── public API ────────────────────────────────────────────────────────────────

def get_scene_publish_name() -> str | None:
    """Return the stem of the current Maya scene filename, or None if untitled."""
    if not _IN_MAYA:
        return None
    scene = cmds.file(q=True, sceneName=True)  # type: ignore[union-attr]
    return Path(scene).stem if scene else None


def publish(
    project_path: Path | str | None = None,
    description: str = "",
    user: str = "",
    extension: str = ".mb",
) -> Path | None:
    """Publish the current Maya scene to the Flux pipeline.

    Workflow:
      1. Resolve project path from prefs when not provided
      2. Get scene stem as publish filename candidate
      3. Validate naming convention
      4. Export scene to temp directory
      5. Call publish_core.publish_file()
      6. Clean up temp directory
    Returns the destination LAST path on success, None on failure.
    """
    if not _IN_MAYA:
        log.error("publish: not running inside Maya")
        return None

    # 1. Resolve project path
    if project_path is None:
        try:
            from core import config, paths
            last = config.get_last_project()
            if not last:
                _show_error("No active project found. Open the Flux Hub and select a project first.")
                return None
            project_path = paths.get_project_path(last)
        except Exception as exc:
            _show_error(f"Cannot resolve project path:\n{exc}")
            return None

    project_path = Path(project_path)

    # Resolve user from prefs
    if not user:
        try:
            from core import config
            user = config.get_current_user() or "unknown"
        except Exception:
            user = "unknown"

    # 2. Get scene stem
    scene_stem = get_scene_publish_name()
    if not scene_stem:
        _show_error("Scene is untitled. Save it with a valid Flux filename first.\nFormat: CLASS_TYPE_NAME_instance_ITER.mb")
        return None

    ext = extension if extension.startswith(".") else f".{extension}"
    filename = f"{scene_stem}{ext}"

    # 3. Validate naming
    try:
        from features.folder_manager.naming_validator import validate_filename
        err = validate_filename(filename)
        if err:
            _show_error(f"Invalid filename: {filename}\n\n{err}")
            return None
    except Exception as exc:
        log.warning("Naming validation skipped: %s", exc)

    # 4. Export to temp directory
    tmp_dir = Path(tempfile.mkdtemp(prefix="flux_pub_"))
    try:
        from dcc.maya.maya_export import export_scene
        exported = export_scene(tmp_dir / filename, ext)
        if exported is None:
            _show_error("Scene export failed. Check the Maya Script Editor for details.")
            return None

        # 5. Publish via publish_core
        from features.publisher.publish_core import publish_file
        dest = publish_file(exported, project_path, description, user, project_path.name, soft="maya")
        if dest is None:
            _show_error("Publish failed. Check the Flux log for details.")
            return None

        log.info("Published → %s", dest)
        _show_info(f"Published successfully:\n{dest.name}")
        return dest

    except Exception as exc:
        _show_error(f"Publish error:\n{exc}")
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

