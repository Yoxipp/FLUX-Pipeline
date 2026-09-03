# seq_shot_creator.py — create sequence and shot folder trees, register SEQ/SHOT tokens.

from __future__ import annotations

from pathlib import Path

from core.constants import ANIM_INSTANCES, DEFAULT_PADDING
from core.logger import get_logger
from core.paths import ensure_dir
from features.folder_manager.naming_validator import format_seq, format_shot
from features.folder_manager.houdini_scene_template import (
    create_sequence_hip_scene,
    create_shot_hip_scene,
)
from features.folder_manager.sequence_template import (
    create_sequence_usd_template,
    create_shot_usd_template,
)
from features.folder_manager.tokens import add_token, load_tokens

log = get_logger(__name__)

# Shot sub-folders created at shot-init time
_SHOT_SUBDIRS = ("layout", "fx", "cfx")

# anim/<phase> folders generated under every shot
_ANIM_SUBDIRS = ANIM_INSTANCES  # ("block", "spline", "polish")


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
    # Author the shot USD template: strong shot light over the weak sequence rig.
    create_shot_usd_template(shot_path, seq_label, shot_label)
    # Author the shot lighting .hip (refines/overrides the seq rig). Non-fatal.
    try:
        create_shot_hip_scene(shot_path, seq_label, shot_label)
    except Exception as exc:  # noqa: BLE001
        log.warning("create_shot_hip_scene failed for %s: %s", f"{seq_label}_{shot_label}", exc)
    log.info("Shot created: %s", shot_path)
    return shot_path


def sequence_exists(project_path: Path, seq_number: int, padding: int = DEFAULT_PADDING) -> bool:
    seq_label = format_seq(seq_number, padding)
    return (project_path / "shot" / seq_label).exists()


def shot_exists(
    project_path: Path,
    seq_number: int,
    shot_number: int,
    padding: int = DEFAULT_PADDING,
) -> bool:
    seq_label  = format_seq(seq_number, padding)
    shot_label = format_shot(shot_number, padding)
    return (project_path / "shot" / seq_label / shot_label).exists()


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
    ensure_dir(shot_path)
    for sub in _SHOT_SUBDIRS:
        ensure_dir(shot_path / sub)
    anim_root = shot_path / "anim"
    for phase in _ANIM_SUBDIRS:
        ensure_dir(anim_root / phase)
    log.debug("Scaffolded shot at %s", shot_path)

