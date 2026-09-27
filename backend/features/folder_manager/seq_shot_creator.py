# seq_shot_creator.py — create sequence and shot folder trees, register SEQ/SHOT tokens.

from __future__ import annotations

from pathlib import Path

from core.constants import DEFAULT_PADDING
from core.logger import get_logger
from core.paths import ensure_dir
from features.folder_manager.naming_validator import format_seq, format_shot
from features.folder_manager.houdini_scene_template import (
    create_sequence_hip_scene,
    create_shot_hip_scene,
)
from features.folder_manager.houdini_render_scene import create_sequence_render_scene_async
from features.folder_manager.sequence_template import (
    create_sequence_usd_template,
    create_shot_usd_template,
)
from features.folder_manager.tokens import add_token, load_tokens

log = get_logger(__name__)


# ── public API ────────────────────────────────────────────────────────────────

def create_sequence(
    project_path: Path,
    seq_number: int,
    padding: int = DEFAULT_PADDING,
) -> Path:
    """Create /shot/<SEQ###>/ and register the SEQ token.

    Returns the sequence Path.
    Raises FileExistsError if it already exists.
    """
    seq_label = format_seq(seq_number, padding)
    seq_rel   = f"shot/{seq_label}"
    seq_path  = project_path / seq_rel

    if seq_path.exists():
        raise FileExistsError(f"Sequence '{seq_label}' already exists at {seq_path}")

    ensure_dir(seq_path)
    add_token(project_path, "SEQ", seq_label, seq_rel)
    # Author the sequence USD template (root layer + base light rig). Never an
    # empty .usd — a failure here only logs, the folder/token still stand.
    create_sequence_usd_template(seq_path, seq_label)
    # Author the sequence lighting .hip (general light rig) next to the USD layers.
    # Non-fatal exactly like the USD template: a missing Houdini only logs.
    try:
        create_sequence_hip_scene(seq_path, seq_label)
    except Exception as exc:  # noqa: BLE001 — never let Houdini break folder creation
        log.warning("create_sequence_hip_scene failed for %s: %s", seq_label, exc)
    # Default render scene of the sequence (10 shots), built in the background.
    create_sequence_render_scene_async(project_path, seq_label)
    log.info("Sequence created: %s", seq_path)
    return seq_path


def create_shot(
    project_path: Path,
    seq_number: int,
    shot_number: int,
    padding: int = DEFAULT_PADDING,
) -> Path:
    """Create /shot/<SEQ###>/<SHOT###>/ with standard sub-folders.

    The parent sequence is created automatically if it does not exist.
    Returns the shot Path.
    Raises FileExistsError if the shot already exists.
    """
    seq_label  = format_seq(seq_number, padding)
    shot_label = format_shot(shot_number, padding)
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
        create_sequence_usd_template(seq_path, seq_label)
        try:
            create_sequence_hip_scene(seq_path, seq_label)
        except Exception as exc:  # noqa: BLE001
            log.warning("create_sequence_hip_scene failed for %s: %s", seq_label, exc)
        log.debug("Auto-created parent sequence %s", seq_label)

    _scaffold_shot(shot_path)

    # Token key uses "SEQ###/SHOT###" so shots are scoped under their sequence
    token_key = f"{seq_label}/{shot_label}"
    add_token(project_path, "SHOT", token_key, shot_rel)
    ensure_shot_base(project_path, seq_label, shot_label)
    # Author the shot USD template: strong shot light over the weak sequence rig.
    create_shot_usd_template(shot_path, seq_label, shot_label)
    # Author the shot lighting .hip (refines/overrides the seq rig). Non-fatal.
    try:
        create_shot_hip_scene(shot_path, seq_label, shot_label)
    except Exception as exc:  # noqa: BLE001
        log.warning("create_shot_hip_scene failed for %s: %s", f"{seq_label}_{shot_label}", exc)
    # Same as a shot born in Production: its stage exists from the start (ADR 0020).
    _write_shot_stage(project_path, seq_label, shot_label)
    log.info("Shot created: %s", shot_path)
    return shot_path


def shot_department_dirs(project_path: Path, seq_label: str, shot_label: str) -> list[Path]:
    """Department folders every shot has (2026-09-19): one per TYPE_SHOT token whose
    folder lives inside the shot (layout, anim, cfx, fx...). LIGHT and COMP have their
    own roots (``lighting/{seq}``, ``comp/{seq}/{shot}``) and are left to their publishes."""
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
    padding: int = DEFAULT_PADDING,
) -> Path:
    """Idempotent version of :func:`create_sequence`.

    * Ensures the sequence folder exists.
    * For each entry in *shots* (``[{'number': int, 'tasks': [{'token': str,
      'subtasks': [str, ...]}]}]``), ensures the shot dir and — inside it —
      each task folder plus its subtask subfolders. Task→folder resolution
      uses *class_tokens* (e.g. ``ANIM → shot/{seq}/{shot}/anim``), falling
      back to lowercased token names.

    Never overwrites or deletes anything — only creates what is missing.
    """
    seq_label = format_seq(seq_number, padding)
    seq_rel   = f"shot/{seq_label}"
    seq_path  = project_path / seq_rel

    new_seq = not seq_path.exists()
    if new_seq:
        ensure_dir(seq_path)
        add_token(project_path, "SEQ", seq_label, seq_rel)
        create_sequence_usd_template(seq_path, seq_label)
        try:
            create_sequence_hip_scene(seq_path, seq_label)
        except Exception as exc:  # noqa: BLE001
            log.warning("create_sequence_hip_scene failed for %s: %s", seq_label, exc)
        log.info("Sequence created (via update): %s", seq_path)

    for shot in shots or []:
        n = shot.get("number") if isinstance(shot, dict) else shot
        if n is None:
            continue
        shot_label = format_shot(int(n), padding)
        shot_path  = project_path / "shot" / seq_label / shot_label
        if not shot_path.exists():
            _scaffold_shot(shot_path)
            token_key = f"{seq_label}/{shot_label}"
            add_token(project_path, "SHOT", token_key, f"shot/{seq_label}/{shot_label}")
            create_shot_usd_template(shot_path, seq_label, shot_label)
            try:
                create_shot_hip_scene(shot_path, seq_label, shot_label)
            except Exception as exc:  # noqa: BLE001
                log.warning("create_shot_hip_scene failed for %s: %s", f"{seq_label}_{shot_label}", exc)
            log.info("Shot created (via seq update): %s", shot_path)
        # Same base as a shot made in the Folder Manager (create-only, old shots too).
        ensure_shot_base(project_path, seq_label, shot_label)

        # Task + subtask folders inside the shot.
        for tsk in (shot.get("tasks", []) if isinstance(shot, dict) else []):
            token = (tsk.get("token") or "").strip().upper()
            if not token:
                continue
            task_dir = _resolve_shot_task_dir(project_path, seq_label, shot_label, token, class_tokens)
            if task_dir is None:
                continue
            if not task_dir.exists():
                ensure_dir(task_dir)
            for sub in tsk.get("subtasks", []) or []:
                sub_label = str(sub).strip()
                if not sub_label or sub_label.lower() == "null":
                    continue
                sub_dir = task_dir / sub_label.lower()
                if not sub_dir.exists():
                    ensure_dir(sub_dir)

    if new_seq:
        # After the shots: their tokens are in the render scene next to the 10 default ones.
        create_sequence_render_scene_async(project_path, seq_label)
    return seq_path


def _resolve_shot_task_dir(
    project_path: Path,
    seq_label: str,
    shot_label: str,
    task_token: str,
    class_tokens: dict[str, str] | None,
) -> Path | None:
    """Return the on-disk folder for a shot-level task, or None if unresolvable."""
    tpl = (class_tokens or {}).get(task_token.upper())
    if tpl:
        rel = tpl.replace("{seq}", seq_label).replace("{shot}", shot_label)
        return project_path / rel
    # Fallback: assume shot/<seq>/<shot>/<token lower>
    return project_path / "shot" / seq_label / shot_label / task_token.lower()


def list_sequences(project_path: Path) -> list[str]:
    """Return sorted SEQ token keys found in tokens.json."""
    tokens = load_tokens(project_path)
    return sorted(tokens.get("SEQ", {}).keys())


def list_shots(project_path: Path, seq_number: int | None = None, padding: int = DEFAULT_PADDING) -> list[str]:
    """Return sorted SHOT token keys, optionally filtered to a single sequence."""
    tokens = load_tokens(project_path)
    shots = sorted(tokens.get("SHOT", {}).keys())
    if seq_number is None:
        return shots
    prefix = format_seq(seq_number, padding) + "/"
    return [s for s in shots if s.startswith(prefix)]


# ── internals ─────────────────────────────────────────────────────────────────

def _scaffold_shot(shot_path: Path) -> None:
    # The shot root. Its department folders come from ensure_shot_base (2026-09-19,
    # replaces the 2026-09-09 "root only" rule); sub-task folders stay on demand.
    ensure_dir(shot_path)
    log.debug("Scaffolded shot at %s", shot_path)

