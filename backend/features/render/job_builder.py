"""Build a Tractor job (Alfred .alf script + JSON submission) for a farm render.

Pure functions, no Tractor import (ADR 0015: the Tractor API is Python 2.7 and
proprietary, it is only reached through the external bridge).

Both v1 renderers go through husk on a published USD:
  * Karma      -> husk --renderer BRAY_HdKarma
  * RenderMan  -> husk --renderer HdPrmanLoaderRendererPlugin (RenderMan for Houdini)

Every path written in the job must be UNC or relative: jobs run under a
service account that has no drive letters (ECOLE_ENV.md).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RENDERER_DELEGATES: Dict[str, str] = {
    "karma": "BRAY_HdKarma",
    "renderman": "HdPrmanLoaderRendererPlugin",
}

_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")
_UNSAFE_TCL = re.compile(r"[{}\\\[\]$]")


class JobValidationError(ValueError):
    """Raised when a job cannot be sent to the farm as is."""


@dataclass
class RenderJobSpec:
    title: str
    project: str  # Tractor "projects" attribute = the team (fair share key)
    user: str
    usd_path: str
    output_pattern: str  # e.g. //srv/flux/PROJ/shots/sh010/render/v003/sh010.$F4.exr
    frame_start: int
    frame_end: int
    renderer: str = "karma"
    chunk_size: int = 5
    frame_step: int = 1
    priority: int = 100
    maxactive: int = 0  # 0 = no per-job cap
    service: str = ""  # Tractor service key expression, empty = any blade
    envkeys: List[str] = field(default_factory=list)
    husk: str = "husk"
    metadata: Dict[str, str] = field(default_factory=dict)
    start_after: str = ""  # "YYYY-MM-DDTHH:MM" local time, empty = start now
    max_task_minutes: int = 0  # RemoteCmd -maxrunsecs: a chunk running longer is killed (error). 0 = no bound
    retry_exit_codes: List[int] = field(default_factory=list)  # RemoteCmd -retryrc: ready again on these codes
    # Freeze when the job starts (scheduled job): a first task writes usd_path from this
    # source with blade/flux_freeze_at_start.py, then the chunks render it. Empty = no such task.
    freeze_source: str = ""
    freeze_script: str = ""
    freeze_python: str = ""   # Tractor's python on the blades (local path, drive letter allowed)
    freeze_houdini: str = ""  # Houdini folder on the blades: the script runs again with its python
    # RenderSettings prim of the shot stage render layer (ADR 0060), "" = husk's default.
    render_settings: str = ""


def after_clause(start_after: str) -> str:
    """Alfred '-after {month day hour:minute}' value (format to confirm at school, phase 0)."""
    try:
        when = datetime.strptime(start_after[:16], "%Y-%m-%dT%H:%M")
    except ValueError:
        raise JobValidationError(f"date de lancement invalide : '{start_after}' (attendu AAAA-MM-JJTHH:MM)") from None
    return f"{when.month} {when.day} {when.hour:02d}:{when.minute:02d}"


def is_drive_letter_path(path: str) -> bool:
    return bool(_DRIVE_LETTER.match(path or ""))


def is_unc_path(path: str) -> bool:
    p = path or ""
    return p.startswith("\\\\") or p.startswith("//")


def validate_farm_path(path: str, what: str, strict: bool = True) -> str:
    """Return the path with forward slashes, refuse drive letters (unless not strict: simulation)."""
    if not path:
        raise JobValidationError(f"{what}: empty path")
    if strict and is_drive_letter_path(path):
        raise JobValidationError(
            f"{what}: drive letter path '{path}' is not visible from the farm service account, use a UNC path"
        )
    return path.replace("\\", "/")


def chunk_frames(start: int, end: int, size: int, step: int = 1) -> List[Tuple[int, int]]:
    """Split [start, end] into inclusive (first, last) chunks of `size` frames."""
    if end < start:
        raise JobValidationError(f"frame range {start}-{end}: end before start")
    if size < 1 or step < 1:
        raise JobValidationError("chunk size and frame step must be >= 1")
    frames = list(range(start, end + 1, step))
    return [(frames[i], frames[min(i + size, len(frames)) - 1]) for i in range(0, len(frames), size)]


def husk_command(spec: RenderJobSpec, first: int, last: int) -> List[str]:
    count = (last - first) // spec.frame_step + 1
    settings = ["--settings", spec.render_settings] if spec.render_settings else []
    return [
        spec.husk,
        "--renderer", RENDERER_DELEGATES[spec.renderer],
        *settings,
        # Verbosity 1 + Alfred progress: ALF_PROGRESS lines, read by Tractor as the task's % done.
        "-Va1",
        "--frame", str(first),
        "--frame-count", str(count),
        "--frame-inc", str(spec.frame_step),
        "--make-output-path",
        "--output", spec.output_pattern,
        spec.usd_path,
    ]


def freeze_command(spec: RenderJobSpec) -> List[str]:
    return [spec.freeze_python, spec.freeze_script, "--houdini", spec.freeze_houdini, spec.freeze_source, spec.usd_path]


def validate_spec(spec: RenderJobSpec, strict: bool = True) -> RenderJobSpec:
    if spec.renderer not in RENDERER_DELEGATES:
        raise JobValidationError(f"unknown renderer '{spec.renderer}' (expected: {', '.join(RENDERER_DELEGATES)})")
    spec.usd_path = validate_farm_path(spec.usd_path, "USD", strict)
    spec.output_pattern = validate_farm_path(spec.output_pattern, "output", strict)
    if not spec.project:
        raise JobValidationError("missing Tractor project (team)")
    texts = [spec.title, spec.project, spec.user, spec.service, spec.husk, spec.usd_path, spec.output_pattern]
    if spec.freeze_source:
        spec.freeze_source = validate_farm_path(spec.freeze_source, "USD a geler", strict)
        spec.freeze_script = validate_farm_path(spec.freeze_script, "script de gel", strict)
        if not spec.freeze_python or not spec.freeze_houdini:
            raise JobValidationError("freeze at start: missing Tractor python or Houdini folder")
        spec.freeze_python = spec.freeze_python.replace("\\", "/")
        spec.freeze_houdini = spec.freeze_houdini.replace("\\", "/")
        texts += [spec.freeze_source, spec.freeze_script, spec.freeze_python, spec.freeze_houdini]
    texts += spec.envkeys + list(spec.metadata.keys()) + list(spec.metadata.values())
    for text in texts:
        # $F4 is the only '$' allowed (husk frame token), it is protected by braces in Tcl.
        if _UNSAFE_TCL.search(text.replace("$F", "")):
            raise JobValidationError(f"unsupported character in '{text}' (braces, brackets, backslash, $)")
    chunk_frames(spec.frame_start, spec.frame_end, spec.chunk_size, spec.frame_step)
    if not isinstance(spec.max_task_minutes, int) or spec.max_task_minutes < 0:
        raise JobValidationError("max_task_minutes must be an integer >= 0 (0 = no bound)")
    if not all(isinstance(c, int) and not isinstance(c, bool) and c != 0 for c in spec.retry_exit_codes):
        raise JobValidationError("retry exit codes must be non-zero integers (0 = success)")
    if spec.start_after:
        after_clause(spec.start_after)
    return spec


def _tcl(value: str) -> str:
    return "{" + value + "}"


def _tcl_cmd(argv: List[str]) -> str:
    return "{" + " ".join(_tcl(a) if " " in a or not a else a for a in argv) + "}"


def to_alf(spec: RenderJobSpec, strict: bool = True) -> str:
    """Alfred job script. Only documented Job / Task / RemoteCmd attributes are used."""
    spec = validate_spec(spec, strict)
    job_attrs = [
        f"-title {_tcl(spec.title)}",
        f"-projects {_tcl(spec.project)}",
        f"-priority {spec.priority}",
    ]
    if spec.maxactive > 0:
        job_attrs.append(f"-maxactive {spec.maxactive}")
    if spec.start_after:
        job_attrs.append(f"-after {_tcl(after_clause(spec.start_after))}")
    if spec.service:
        job_attrs.append(f"-service {_tcl(spec.service)}")
    if spec.envkeys:
        job_attrs.append(f"-envkey {_tcl(' '.join(spec.envkeys))}")
    if spec.metadata:
        # Values carry no braces (validate_spec), so the JSON braces stay balanced inside the Tcl word.
        job_attrs.append(f"-metadata {_tcl(json.dumps(spec.metadata, sort_keys=True))}")

    service = f" -service {_tcl(spec.service)}" if spec.service else ""
    pad = "    "
    if spec.freeze_source:
        # Freeze task first, then the chunks (in parallel) once it has succeeded.
        job_attrs.append("-serialsubtasks 1")
    lines = ["##AlfredToDo 3.0", "Job " + " ".join(job_attrs) + " -subtasks {"]
    if spec.freeze_source:
        lines.append(f"    Task -title {{gel au demarrage}} -cmds {{")
        lines.append(f"        RemoteCmd {_tcl_cmd(freeze_command(spec))}{service}")
        lines.append("    }")
        lines.append("    Task -title {rendu} -subtasks {")
        pad = "        "
    # Render commands only: the freeze task is short and must never be retried blindly.
    render_opts = service
    if spec.max_task_minutes > 0:
        render_opts += f" -maxrunsecs {spec.max_task_minutes * 60}"
    if spec.retry_exit_codes:
        render_opts += f" -retryrc {_tcl(' '.join(str(c) for c in spec.retry_exit_codes))}"
    for first, last in chunk_frames(spec.frame_start, spec.frame_end, spec.chunk_size, spec.frame_step):
        cmd = _tcl_cmd(husk_command(spec, first, last))
        lines.append(f"{pad}Task -title {_tcl(f'frames {first}-{last}')} -cmds {{")
        lines.append(f"{pad}    RemoteCmd {cmd}{render_opts}")
        lines.append(f"{pad}}}")
    if spec.freeze_source:
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_submission(spec: RenderJobSpec, strict: bool = True) -> Dict:
    """JSON sent to the external bridge (verb 'spool')."""
    spec = validate_spec(spec, strict)
    return {
        "verb": "spool",
        "spec": asdict(spec),
        "chunks": chunk_frames(spec.frame_start, spec.frame_end, spec.chunk_size, spec.frame_step),
        "alf": to_alf(spec, strict),
    }


def dry_run(spec: RenderJobSpec, out_dir: Path, name: Optional[str] = None,
            strict: bool = True) -> Dict[str, str]:
    """Write <name>.alf and <name>.json without spooling (phase 0 not done yet)."""
    submission = to_submission(spec, strict)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name or re.sub(r"[^A-Za-z0-9_.-]+", "_", spec.title) or "job"
    alf_path = out_dir / f"{stem}.alf"
    json_path = out_dir / f"{stem}.json"
    alf_path.write_text(submission["alf"], encoding="utf-8")
    json_path.write_text(json.dumps(submission, indent=2), encoding="utf-8")
    return {"alf": str(alf_path), "json": str(json_path)}
