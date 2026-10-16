# seq_shot_creator.py — create sequence and shot folder trees, register SEQ/SHOT tokens.

from __future__ import annotations

from pathlib import Path

import re

from core.constants import SEQ_SHOT_PADDING
from core.logger import get_logger
from core.paths import ensure_dir
from features.folder_manager.naming_validator import format_seq, format_shot
from features.folder_manager.houdini_render_scene import create_sequence_render_scene_async
from features.folder_manager.tokens import add_token, load_tokens

log = get_logger(__name__)


# ── public API ────────────────────────────────────────────────────────────────

def create_sequence(
    project_path: Path,
    seq_number: int,
    padding: int = SEQ_SHOT_PADDING,
    *,
    seq_label: str | None = None,
) -> Path:
    """Create /shot/<SEQ####>/ and register the SEQ token.

    The label is the existing SEQ token with that number (SEQ001 in an older project),
    else a new 4-digit one (SEQ0010), unless *seq_label* gives it.

    Returns the sequence Path.
    Raises FileExistsError if it already exists.
    """
    seq_label = seq_label or seq_label_for(project_path, seq_number, padding)
    seq_rel   = f"shot/{seq_label}"
    seq_path  = project_path / seq_rel

    if seq_path.exists():
        raise FileExistsError(f"Sequence '{seq_label}' already exists at {seq_path}")

    ensure_dir(seq_path)
    add_token(project_path, "SEQ", seq_label, seq_rel)
    # ADR 0038 (2026-09-28): no sequence USD layer, no sequence light rig / FLUX
    # Lighting scene any more: the lights are made in the render scene.
    # Default render scene of the sequence (the maintainer's template, ADR 0037), built in the background.
    create_sequence_render_scene_async(project_path, seq_label)
    log.info("Sequence created: %s", seq_path)
    return seq_path


def create_shot(
    project_path: Path,
    seq_number: int,
    shot_number: int,
    padding: int = SEQ_SHOT_PADDING,
    *,
    seq_label: str | None = None,
    shot_label: str | None = None,
) -> Path:
    """Create /shot/<SEQ###>/<SHOT###>/ with standard sub-folders.

    The parent sequence is created automatically if it does not exist.
    Returns the shot Path.
    Raises FileExistsError if the shot already exists.
    """
    seq_label  = seq_label or seq_label_for(project_path, seq_number, padding)
    shot_label = shot_label or shot_label_for(project_path, seq_label, shot_number, padding)
    shot_rel   = f"shot/{seq_label}/{shot_label}"
    shot_path  = project_path / shot_rel

    if shot_path.exists():
        raise FileExistsError(f"Shot '{shot_label}' already exists at {shot_path}")

    # Ensure parent sequence exists (does not raise if already there)
    seq_path = project_path / "shot" / seq_label
    if not seq_path.exists():
        seq_rel = f"shot/{seq_label}"
        ensure_dir(seq_path)
        add_token(project_path, "SEQ", seq_label, seq_rel)
        log.debug("Auto-created parent sequence %s", seq_label)

    _scaffold_shot(shot_path)

    # Token key uses "SEQ###/SHOT###" so shots are scoped under their sequence
    token_key = f"{seq_label}/{shot_label}"
    add_token(project_path, "SHOT", token_key, shot_rel)
    ensure_shot_base(project_path, seq_label, shot_label)
    # ADR 0038: no shot light layer / shot lighting scene (lights live in the render scene).
    # Same as a shot born in Production: its stage exists from the start (ADR 0020).
    _write_shot_stage(project_path, seq_label, shot_label)
    log.info("Shot created: %s", shot_path)
    return shot_path


def shot_department_dirs(project_path: Path, seq_label: str, shot_label: str) -> list[Path]:
    """Department folders every shot has (2026-09-19): one per TYPE_SHOT token whose
    folder lives inside the shot (layout, anim, cfx, fx, lighting, comp, render...). A
    token with its own root (LIGHT / COMP / RENDER of a project made before ADR 0055) is
    left to its publishes."""
    from core.constants import DEFAULT_SHOT_TYPE_TOKENS

    shot_rel = f"shot/{seq_label}/{shot_label}"
    departments = (load_tokens(project_path) or {}).get("TYPE_SHOT") or DEFAULT_SHOT_TYPE_TOKENS
    out: list[Path] = []
    for tpl in departments.values():
        rel = str(tpl).replace("\\", "/").replace("{seq}", seq_label).replace("{shot}", shot_label).strip("/")
        if "{" in rel or not rel.startswith(shot_rel + "/"):
            continue
        folder = project_path / rel
        if folder not in out:
            out.append(folder)
    return out


def ensure_shot_base(project_path: Path, seq_label: str, shot_label: str) -> list[Path]:
    """The one folder base of a shot, from the Folder Manager and from Production alike:
    the shot folder and its department folders. Create-only; returns what was created.
    Sub-task folders (anim/block, anim/dingo...) come only from a declared sub-task or
    a publish."""
    created = []
    shot_path = project_path / "shot" / seq_label / shot_label
    for folder in [shot_path] + shot_department_dirs(project_path, seq_label, shot_label):
        if not folder.exists():
            ensure_dir(folder)
            created.append(folder)
    return created


def _write_shot_stage(project_path: Path, seq_label: str, shot_label: str) -> None:
    try:
        from features.usd_assembler.shot_stage import write_stage

        write_stage(project_path, seq_label, shot_label)
    except Exception as exc:  # noqa: BLE001 - the folder stands even without a stage
        log.warning("Shot stage not written for %s_%s: %s", seq_label, shot_label, exc)


def update_sequence(
    project_path: Path,
    seq_number: int,
    shots: list[dict] | None = None,
    class_tokens: dict[str, str] | None = None,
    padding: int = SEQ_SHOT_PADDING,
    *,
    seq_label: str | None = None,
    shot_type_tokens: dict[str, str] | None = None,
    counts: dict[str, int] | None = None,
) -> Path:
    """Idempotent version of :func:`create_sequence`.

    Production passes its own names (*seq_label*, ``label`` of each shot) so an older
    SEQ001 / SHOT010 is never re-padded into a second folder.

    * Ensures the sequence folder exists.
    * For each entry in *shots* (``[{'number': int, 'tasks': [{'token': str,
      'subtasks': [str, ...]}]}]``), ensures the shot dir and — inside it —
      each task folder plus its subtask subfolders. Task→folder resolution
      uses *shot_type_tokens* (TYPE_SHOT, ADR 0019, e.g. ``FX → shot/{seq}/{shot}/fx``),
      then the legacy *class_tokens* (old projects), then the lowercased token
      under the shot.

    When *counts* is given, the folders really created are added to it under
    ``sequences`` / ``shots`` / ``tasks`` / ``subtasks`` (department folders of
    the shot base count as tasks).

    Never overwrites or deletes anything — only creates what is missing.
    """
    tally = {"sequences": 0, "shots": 0, "tasks": 0, "subtasks": 0}
    seq_label = seq_label or seq_label_for(project_path, seq_number, padding)
    seq_rel   = f"shot/{seq_label}"
    seq_path  = project_path / seq_rel

    new_seq = not seq_path.exists()
    if new_seq:
        ensure_dir(seq_path)
        add_token(project_path, "SEQ", seq_label, seq_rel)
        tally["sequences"] += 1
        log.info("Sequence created (via update): %s", seq_path)

    for shot in shots or []:
        n = shot.get("number") if isinstance(shot, dict) else shot
        if n is None:
            continue
        given = shot.get("label") if isinstance(shot, dict) else None
        shot_label = given or shot_label_for(project_path, seq_label, int(n), padding)
        shot_path  = project_path / "shot" / seq_label / shot_label
        if not shot_path.exists():
            _scaffold_shot(shot_path)
            token_key = f"{seq_label}/{shot_label}"
            add_token(project_path, "SHOT", token_key, f"shot/{seq_label}/{shot_label}")
            tally["shots"] += 1
            log.info("Shot created (via seq update): %s", shot_path)
        # Same base as a shot made in the Folder Manager (create-only, old shots too).
        base = ensure_shot_base(project_path, seq_label, shot_label)
        tally["tasks"] += sum(1 for p in base if p != shot_path)

        # Task + subtask folders inside the shot.
        for tsk in (shot.get("tasks", []) if isinstance(shot, dict) else []):
            token = (tsk.get("token") or "").strip().upper()
            if not token:
                continue
            task_dir = _resolve_shot_task_dir(project_path, seq_label, shot_label, token,
                                              class_tokens, shot_type_tokens)
            if task_dir is None:
                continue
            if not task_dir.exists():
                ensure_dir(task_dir)
                tally["tasks"] += 1
            for sub in tsk.get("subtasks", []) or []:
                sub_label = str(sub).strip()
                if not sub_label or sub_label.lower() == "null":
                    continue
                sub_dir = task_dir / sub_label.lower()
                if not sub_dir.exists():
                    ensure_dir(sub_dir)
                    tally["subtasks"] += 1

    if new_seq:
        # After the shots: the render scene gets one block per shot (at least 3, ADR 0037).
        create_sequence_render_scene_async(project_path, seq_label)
    if counts is not None:
        for key, value in tally.items():
            counts[key] = counts.get(key, 0) + value
    return seq_path


def shot_task_template(
    task_token: str,
    class_tokens: dict[str, str] | None = None,
    shot_type_tokens: dict[str, str] | None = None,
) -> str | None:
    """Folder template of a shot task: TYPE_SHOT first (ADR 0019), then the legacy
    shot CLASS token of old projects. None when neither knows the token."""
    key = (task_token or "").strip().upper()
    if not key:
        return None
    for mapping in (shot_type_tokens, class_tokens):
        tpl = (mapping or {}).get(key)
        if tpl:
            return str(tpl)
    return None


def _resolve_shot_task_dir(
    project_path: Path,
    seq_label: str,
    shot_label: str,
    task_token: str,
    class_tokens: dict[str, str] | None,
    shot_type_tokens: dict[str, str] | None = None,
) -> Path | None:
    """Return the on-disk folder for a shot-level task, or None if unresolvable."""
    tpl = shot_task_template(task_token, class_tokens, shot_type_tokens)
    if tpl:
        rel = tpl.replace("\\", "/").replace("{seq}", seq_label).replace("{shot}", shot_label)
        if "{" in rel:
            return None  # unknown placeholder: never create a literal "{x}" folder
        return project_path / rel.strip("/")
    # Fallback: assume shot/<seq>/<shot>/<token lower>
    return project_path / "shot" / seq_label / shot_label / task_token.lower()


def list_sequences(project_path: Path) -> list[str]:
    """Return sorted SEQ token keys found in tokens.json."""
    tokens = load_tokens(project_path)
    return sorted(tokens.get("SEQ", {}).keys())


def list_shots(project_path: Path, seq_number: int | None = None, padding: int = SEQ_SHOT_PADDING) -> list[str]:
    """Return sorted SHOT token keys, optionally filtered to a single sequence."""
    tokens = load_tokens(project_path)
    shots = sorted(tokens.get("SHOT", {}).keys())
    if seq_number is None:
        return shots
    prefix = seq_label_for(project_path, seq_number, padding) + "/"
    return [s for s in shots if s.startswith(prefix)]


def seq_label_for(project_path: Path, number: int, padding: int = SEQ_SHOT_PADDING) -> str:
    """Existing SEQ token with this number (any width), else a new padded label."""
    for key in (load_tokens(project_path) or {}).get("SEQ", {}):
        if _number_of(key, "SEQ") == number:
            return key
    return format_seq(number, padding)


def shot_label_for(project_path: Path, seq_label: str, number: int,
                   padding: int = SEQ_SHOT_PADDING) -> str:
    """Existing SHOT token of *seq_label* with this number (any width), else a new label."""
    prefix = f"{seq_label}/"
    for key in (load_tokens(project_path) or {}).get("SHOT", {}):
        if key.startswith(prefix) and _number_of(key[len(prefix):], "SHOT") == number:
            return key[len(prefix):]
    return format_shot(number, padding)


def _number_of(label: str, prefix: str) -> int | None:
    m = re.fullmatch(prefix + r"(\d+)", label.upper())
    return int(m.group(1)) if m else None


# ── internals ─────────────────────────────────────────────────────────────────

def _scaffold_shot(shot_path: Path) -> None:
    # The shot root. Its department folders come from ensure_shot_base (2026-09-19,
    # replaces the 2026-09-09 "root only" rule); sub-task folders stay on demand.
    ensure_dir(shot_path)
    log.debug("Scaffolded shot at %s", shot_path)

