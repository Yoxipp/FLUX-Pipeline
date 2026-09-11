# maya_export_client.py — hub-side (Python 3.13) driver for a Maya export.
#
# The flux_actions engine runs in the hub, not inside Maya. A Maya export must
# execute in the Maya process, so this sends a one-line command over the Maya
# commandPort that calls the SAME dcc.maya.maya_export.run_publish_export the
# legacy publish endpoint uses. No export logic is reimplemented here: this is
# only the transport + result-envelope glue, returned as (path, logs).
#
# This runs a blocking socket call; async callers wrap it in an executor.

from __future__ import annotations

import base64
import json
from pathlib import Path

from core.logger import get_logger
from dcc.maya.maya_connection import send_command_direct

log = get_logger(__name__)

# backend/ root, prepended to the Maya command so dcc.maya.* imports even in a
# Maya session started before the autostart was installed.
_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent.parent)

# Animated ABC over many frames can be slow; everything else is quick.
_DEFAULT_TIMEOUT = 120.0
_ABC_SEQUENCE_TIMEOUT = 600.0


def _build_command(
    out_path: Path,
    result_path: Path,
    extension: str,
    scope: str,
    frame_range: tuple[int, int] | None,
    options: dict | None,
) -> str:
    """Compose the single-line Python command Maya's commandPort will exec()."""
    out_fwd = str(out_path).replace("\\", "/")
    res_fwd = str(result_path).replace("\\", "/")

    # Options travel as base64(JSON) so the single-line command stays quote-safe.
    opts_b64 = ""
    if options:
        opts_b64 = base64.b64encode(json.dumps(options).encode("utf-8")).decode("ascii")

    # Drop the cached export module so a running Maya picks up updated backend code
    # without a restart (Maya keeps sys.modules across commandPort calls).
    prefix = (
        f"import sys; sys.path.insert(0, r'{_BACKEND_ROOT}'); "
        f"sys.modules.pop('dcc.maya.maya_export', None)"
    )

    call = (
        f"from dcc.maya.maya_export import run_publish_export; "
        f"run_publish_export(r'{out_fwd}', '{extension}', '{scope}', r'{res_fwd}', "
    )
    if extension == ".abc" and frame_range is not None:
        fs, fe = frame_range
        call += f"frame_start={fs}, frame_end={fe}, options_b64='{opts_b64}')"
    else:
        call += f"options_b64='{opts_b64}')"

    return f"{prefix}; {call}"


def _read_envelope(result_path: Path) -> tuple[list[dict], list[str]]:
    """Return (all log records, error messages) from the JSON envelope Maya wrote."""
    logs: list[dict] = []
    errors: list[str] = []
    if not result_path.exists():
        return logs, errors
    try:
        envelope = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Could not read Maya export envelope: %s", exc)
        return logs, errors
    for rec in envelope.get("logs", []):
        lvl = str(rec.get("level", "INFO")).upper()
        msg = str(rec.get("msg", ""))
        logs.append({"level": lvl, "msg": msg})
        # Mirror into the hub logger so Maya's own logs reach the Flux console.
        text = f"[Maya] {msg}"
        if lvl in ("ERROR", "CRITICAL"):
            log.error(text)
            errors.append(msg)
        elif lvl == "WARNING":
            log.warning(text)
        else:
            log.info(text)
    return logs, errors


def run_maya_export(
    out_path: Path,
    extension: str,
    scope: str,
    *,
    port: int | None = None,
    frame_range: tuple[int, int] | None = None,
    options: dict | None = None,
    timeout: float | None = None,
) -> tuple[Path | None, list[dict]]:
    """Export the open Maya scene/selection to *out_path* via the commandPort.

    *scope* is 'scene' for a full-scene export, anything else exports the
    selection. *extension* is the dotted format ('.mb', '.abc', ...). Returns
    ``(exported_path or None, log_records)``; log_records mirror Maya's own logs
    so the caller can surface the real failure reason.
    """
    out_path = Path(out_path)
    result_path = out_path.parent / "_flux_export_result.json"
    scope_norm = "scene" if scope == "scene" else "selection"

    if timeout is None:
        timeout = _ABC_SEQUENCE_TIMEOUT if (extension == ".abc" and frame_range) else _DEFAULT_TIMEOUT

    cmd = _build_command(out_path, result_path, extension, scope_norm, frame_range, options)
    response = send_command_direct(cmd, timeout=timeout, port=port or _maya_port())
    if response is None:
        log.error("Maya did not respond on the commandPort (export aborted)")
        return None, [{"level": "ERROR", "msg": "Maya ne répond pas sur le commandPort"}]

    logs, errors = _read_envelope(result_path)
    if not out_path.exists():
        reason = f" ({' | '.join(errors)})" if errors else ""
        log.error("Maya export failed, file missing: %s%s", out_path, reason)
        return None, logs

    return out_path, logs


def _maya_port() -> int:
    from core.constants import DCC_PORTS
    return DCC_PORTS["Maya"]
